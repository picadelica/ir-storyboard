"""CRUD operations on the persistent matrix."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .models import (
    LAYERS, LayerSpec, SubsectionSpec, layer_by_id, subsection_by_id,
    channel_can_fill,
    FLAG_GREEN, FLAG_RED, FLAG_GREY,
    ALL_CHANNELS,
)


# ---------- bootstrap reference data ----------

def seed_layers(conn: sqlite3.Connection) -> None:
    """Insert the canonical 8 layers + their subsections (idempotent)."""
    cur = conn.cursor()
    for L in LAYERS:
        cur.execute(
            """INSERT OR IGNORE INTO layers (id, code, name, intimacy, primary_channels)
                VALUES (?, ?, ?, ?, ?)""",
            (L.id, L.code, L.name, L.intimacy, json.dumps(L.primary_channels)),
        )
        for s in L.subsections:
            cur.execute(
                """INSERT OR IGNORE INTO subsections
                    (id, layer_id, code, name, description, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                (s.id, L.id, s.code, s.name, s.description, s.sort_order),
            )
    conn.commit()


# ---------- clients ----------

def upsert_client(conn: sqlite3.Connection, client_id: str, name: str,
                  sector: str = "", one_liner: str = "",
                  founder_name: str = "", founder_handle: str = "",
                  aliases: Optional[List[str]] = None, notes: str = "") -> None:
    conn.execute(
        """INSERT INTO clients (id, name, sector, one_liner, founder_name, founder_handle, aliases, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, sector=excluded.sector, one_liner=excluded.one_liner,
                founder_name=excluded.founder_name, founder_handle=excluded.founder_handle,
                aliases=excluded.aliases, notes=excluded.notes""",
        (client_id, name, sector, one_liner,
         founder_name, founder_handle, json.dumps(aliases or []), notes),
    )
    conn.commit()


def count_client_facts(conn: sqlite3.Connection, client_id: str) -> int:
    row = conn.execute(
        """SELECT COUNT(*) FROM facts f
            JOIN cells c ON c.id = f.cell_id
            WHERE c.client_id = ?""",
        (client_id,),
    ).fetchone()
    return row[0] if row else 0


def list_clients(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM clients ORDER BY name"))


# ---------- cells ----------

def get_or_create_cell(conn: sqlite3.Connection, client_id: str, subsection_id: str) -> int:
    row = conn.execute(
        "SELECT id FROM cells WHERE client_id=? AND subsection_id=?",
        (client_id, subsection_id),
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO cells (client_id, subsection_id) VALUES (?, ?)",
        (client_id, subsection_id),
    )
    conn.commit()
    return cur.lastrowid


def ensure_full_grid(conn: sqlite3.Connection, client_id: str) -> None:
    """Ensure every (client, subsection) cell exists. New cells start empty (= implicit grey)."""
    for L in LAYERS:
        for s in L.subsections:
            get_or_create_cell(conn, client_id, s.id)


# ---------- sources ----------

def add_source(conn: sqlite3.Connection, channel: str, title: str = "",
               url: str = "", notes: str = "") -> int:
    if channel not in ALL_CHANNELS:
        raise ValueError(f"unknown channel {channel}")
    cur = conn.execute(
        "INSERT INTO sources (channel, title, url, notes) VALUES (?, ?, ?, ?)",
        (channel, title, url, notes),
    )
    conn.commit()
    return cur.lastrowid


# ---------- facts ----------

def add_fact(conn: sqlite3.Connection, *, client_id: str, subsection_id: str,
             text: str, flag: str, source_id: Optional[int] = None,
             confidence: float = 1.0, valid_until: Optional[str] = None) -> int:
    if flag not in (FLAG_GREEN, FLAG_RED, FLAG_GREY):
        raise ValueError(f"bad flag {flag}")
    # methodological guard: warn if source channel can't really fill this layer
    layer_id = int(subsection_id.split(".")[0])
    if source_id is not None:
        ch = conn.execute("SELECT channel FROM sources WHERE id=?", (source_id,)).fetchone()
        if ch and not channel_can_fill(ch["channel"], layer_id):
            # we don't refuse — but record a methodological warning in notes
            conn.execute(
                "UPDATE sources SET notes = COALESCE(notes,'') || ? WHERE id=?",
                (f"\n[warn] channel {ch['channel']} not primary for layer {layer_id}", source_id),
            )

    cell_id = get_or_create_cell(conn, client_id, subsection_id)
    cur = conn.execute(
        """INSERT INTO facts (cell_id, text, flag, source_id, confidence, valid_until)
            VALUES (?, ?, ?, ?, ?, ?)""",
        (cell_id, text, flag, source_id, confidence, valid_until),
    )
    conn.commit()
    return cur.lastrowid


def facts_for_cell(conn: sqlite3.Connection, client_id: str,
                   subsection_id: str) -> List[sqlite3.Row]:
    return list(conn.execute(
        """SELECT f.*, s.channel AS source_channel, s.title AS source_title, s.url AS source_url
            FROM facts f
            JOIN cells c ON c.id = f.cell_id
            LEFT JOIN sources s ON s.id = f.source_id
            WHERE c.client_id=? AND c.subsection_id=?
            ORDER BY f.captured_at DESC""",
        (client_id, subsection_id),
    ))


def get_fact(conn: sqlite3.Connection, fact_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        """SELECT f.*, s.channel AS source_channel, s.title AS source_title, s.url AS source_url,
                  c.client_id, c.subsection_id
            FROM facts f
            JOIN cells c ON c.id = f.cell_id
            LEFT JOIN sources s ON s.id = f.source_id
            WHERE f.id=?""",
        (fact_id,),
    ).fetchone()


def update_fact(conn: sqlite3.Connection, fact_id: int, *,
                text: Optional[str] = None, flag: Optional[str] = None,
                confidence: Optional[float] = None) -> None:
    sets, params = [], []
    if text is not None:
        sets.append("text=?"); params.append(text)
    if flag is not None:
        if flag not in (FLAG_GREEN, FLAG_RED, FLAG_GREY):
            raise ValueError(f"bad flag {flag}")
        sets.append("flag=?"); params.append(flag)
    if confidence is not None:
        sets.append("confidence=?"); params.append(confidence)
    if not sets:
        return
    params.append(fact_id)
    conn.execute(f"UPDATE facts SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()


def delete_fact(conn: sqlite3.Connection, fact_id: int) -> None:
    conn.execute("DELETE FROM facts WHERE id=?", (fact_id,))
    conn.commit()


def list_sources(conn: sqlite3.Connection, channel: Optional[str] = None) -> List[sqlite3.Row]:
    if channel:
        return list(conn.execute(
            "SELECT * FROM sources WHERE channel=? ORDER BY captured_at DESC",
            (channel,),
        ))
    return list(conn.execute("SELECT * FROM sources ORDER BY captured_at DESC"))


def get_artifact(conn: sqlite3.Connection, artifact_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()


def list_artifacts(conn: sqlite3.Connection, *, client_id: str,
                   cycle: Optional[str] = None, limit: int = 50) -> List[sqlite3.Row]:
    if cycle:
        return list(conn.execute(
            """SELECT id, client_id, cycle, title, created_at FROM artifacts
                WHERE client_id=? AND cycle=? ORDER BY created_at DESC LIMIT ?""",
            (client_id, cycle, limit),
        ))
    return list(conn.execute(
        """SELECT id, client_id, cycle, title, created_at FROM artifacts
            WHERE client_id=? ORDER BY created_at DESC LIMIT ?""",
        (client_id, limit),
    ))


# ---------- matrix views ----------

def cell_summary(conn: sqlite3.Connection, client_id: str) -> List[Dict[str, Any]]:
    """Return one row per subsection with green/red/grey counts and last update."""
    rows = conn.execute("""
        SELECT s.id AS subsection_id, s.layer_id, s.name AS subsection_name,
               L.name AS layer_name, L.intimacy,
               SUM(CASE WHEN f.flag='green' THEN 1 ELSE 0 END) AS n_green,
               SUM(CASE WHEN f.flag='red'   THEN 1 ELSE 0 END) AS n_red,
               SUM(CASE WHEN f.flag='grey'  THEN 1 ELSE 0 END) AS n_grey,
               MAX(f.captured_at) AS last_update
        FROM subsections s
        JOIN layers L ON L.id = s.layer_id
        LEFT JOIN cells c ON c.subsection_id = s.id AND c.client_id = ?
        LEFT JOIN facts f ON f.cell_id = c.id
        GROUP BY s.id
        ORDER BY L.intimacy, s.sort_order
    """, (client_id,)).fetchall()
    return [dict(r) for r in rows]


def empty_cells(conn: sqlite3.Connection, client_id: str) -> List[Dict[str, Any]]:
    """Subsections with NO facts at all (no green, no red, no grey).
    These are 'untouched' cells — the channel hasn't been run yet."""
    return [r for r in cell_summary(conn, client_id)
            if (r["n_green"] or 0) == 0
            and (r["n_red"] or 0) == 0
            and (r["n_grey"] or 0) == 0]


def cells_with_known_gaps(conn: sqlite3.Connection, client_id: str) -> List[Dict[str, Any]]:
    """Subsections that have explicit grey-flagged facts (= 'we know we don't know').
    These are the methodologically interesting punch-list items."""
    return [r for r in cell_summary(conn, client_id) if (r["n_grey"] or 0) > 0]


def thinly_covered_cells(conn: sqlite3.Connection, client_id: str,
                         min_green: int = 2) -> List[Dict[str, Any]]:
    """Subsections with fewer than `min_green` green-flagged facts.
    Useful for prioritising what to deepen before quarterly."""
    return [r for r in cell_summary(conn, client_id)
            if (r["n_green"] or 0) < min_green]


def grey_facts_for_cell(conn: sqlite3.Connection, client_id: str,
                        subsection_id: str) -> List[sqlite3.Row]:
    return [f for f in facts_for_cell(conn, client_id, subsection_id)
            if f["flag"] == "grey"]


def cell_dominant_flag(conn: sqlite3.Connection, client_id: str, subsection_id: str) -> str:
    """Roll up a cell's facts into a single flag for scorecard purposes."""
    facts = facts_for_cell(conn, client_id, subsection_id)
    has_red = any(f["flag"] == FLAG_RED for f in facts)
    has_green = any(f["flag"] == FLAG_GREEN for f in facts)
    if has_red and has_green:
        return "mixed"
    if has_red:
        return FLAG_RED
    if has_green:
        return FLAG_GREEN
    return FLAG_GREY


# ---------- plans + tracks ----------

def upsert_plan(conn: sqlite3.Connection, client_id: str, quarter: str,
                notes: str = "") -> int:
    row = conn.execute(
        "SELECT id FROM plans WHERE client_id=? AND quarter=?",
        (client_id, quarter),
    ).fetchone()
    if row:
        conn.execute("UPDATE plans SET notes=? WHERE id=?", (notes, row["id"]))
        conn.commit()
        return row["id"]
    cur = conn.execute(
        "INSERT INTO plans (client_id, quarter, notes) VALUES (?, ?, ?)",
        (client_id, quarter, notes),
    )
    conn.commit()
    return cur.lastrowid


def add_track(conn: sqlite3.Connection, *, plan_id: int, name: str, angle: str,
              target_layer_ids: List[int], target_subsection_ids: List[str],
              priority: int = 1) -> int:
    cur = conn.execute(
        """INSERT INTO narrative_tracks
            (plan_id, name, angle, target_layer_ids, target_subsection_ids, priority)
            VALUES (?, ?, ?, ?, ?, ?)""",
        (plan_id, name, angle,
         json.dumps(target_layer_ids), json.dumps(target_subsection_ids), priority),
    )
    conn.commit()
    return cur.lastrowid


def tracks_for_quarter(conn: sqlite3.Connection, client_id: str,
                       quarter: str) -> List[Dict[str, Any]]:
    rows = conn.execute("""
        SELECT t.* FROM narrative_tracks t
        JOIN plans p ON p.id = t.plan_id
        WHERE p.client_id=? AND p.quarter=?
        ORDER BY t.priority DESC, t.id
    """, (client_id, quarter)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["target_layer_ids"] = json.loads(d.get("target_layer_ids") or "[]")
        d["target_subsection_ids"] = json.loads(d.get("target_subsection_ids") or "[]")
        out.append(d)
    return out


# ---------- artifacts ----------

def save_artifact(conn: sqlite3.Connection, *, client_id: str, cycle: str,
                  title: str, body: str, meta: Optional[Dict[str, Any]] = None) -> int:
    cur = conn.execute(
        """INSERT INTO artifacts (client_id, cycle, title, body, meta)
            VALUES (?, ?, ?, ?, ?)""",
        (client_id, cycle, title, body, json.dumps(meta or {})),
    )
    conn.commit()
    return cur.lastrowid
