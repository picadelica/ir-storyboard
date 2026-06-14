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
                  aliases: Optional[List[str]] = None, notes: str = "",
                  tone_preset: Optional[str] = None) -> None:
    conn.execute(
        """INSERT INTO clients (id, name, sector, one_liner, founder_name, founder_handle,
                                aliases, notes, tone_preset)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, 'business'))
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, sector=excluded.sector, one_liner=excluded.one_liner,
                founder_name=excluded.founder_name, founder_handle=excluded.founder_handle,
                aliases=excluded.aliases, notes=excluded.notes,
                tone_preset=COALESCE(excluded.tone_preset, clients.tone_preset)""",
        (client_id, name, sector, one_liner,
         founder_name, founder_handle, json.dumps(aliases or []), notes, tone_preset),
    )
    conn.commit()


# ---------- methodology (per-subsection description + per-client tone) ----------

def get_subsection_descriptions(conn: sqlite3.Connection) -> Dict[str, str]:
    """Return {subsection_id: description} for all 24 cells."""
    rows = conn.execute(
        "SELECT id, COALESCE(description, '') AS description FROM subsections"
    ).fetchall()
    return {r["id"]: r["description"] for r in rows}


def update_subsection_description(conn: sqlite3.Connection,
                                  subsection_id: str,
                                  description: str) -> None:
    """Overwrite the description for one subsection."""
    cur = conn.execute(
        "UPDATE subsections SET description = ? WHERE id = ?",
        (description, subsection_id),
    )
    if cur.rowcount == 0:
        raise ValueError(f"Unknown subsection_id: {subsection_id}")
    conn.commit()


def get_client_tone_preset(conn: sqlite3.Connection, client_id: str) -> str:
    """Return the client's tone preset id, defaulting to 'business' if missing."""
    row = conn.execute(
        "SELECT tone_preset FROM clients WHERE id = ?", (client_id,)
    ).fetchone()
    if not row:
        return "business"
    return (row["tone_preset"] or "business").strip() or "business"


def set_client_tone_preset(conn: sqlite3.Connection,
                            client_id: str, preset_id: str) -> None:
    cur = conn.execute(
        "UPDATE clients SET tone_preset = ? WHERE id = ?",
        (preset_id, client_id),
    )
    if cur.rowcount == 0:
        raise ValueError(f"Unknown client_id: {client_id}")
    conn.commit()


def get_client_subsection_notes(conn: sqlite3.Connection,
                                  client_id: str) -> Dict[str, str]:
    """Return {sid: per-client note} for this client (only non-empty rows)."""
    rows = conn.execute(
        "SELECT subsection_id, note FROM client_subsection_notes WHERE client_id = ?",
        (client_id,),
    ).fetchall()
    return {r["subsection_id"]: r["note"] for r in rows if (r["note"] or "").strip()}


def set_client_subsection_note(conn: sqlite3.Connection,
                                client_id: str, subsection_id: str,
                                note: str) -> None:
    """Upsert per-client note. Empty string deletes the row."""
    if not (note or "").strip():
        conn.execute(
            "DELETE FROM client_subsection_notes WHERE client_id = ? AND subsection_id = ?",
            (client_id, subsection_id),
        )
    else:
        conn.execute(
            """INSERT INTO client_subsection_notes (client_id, subsection_id, note)
                VALUES (?, ?, ?)
                ON CONFLICT(client_id, subsection_id) DO UPDATE
                    SET note = excluded.note,
                        updated_at = CURRENT_TIMESTAMP""",
            (client_id, subsection_id, note.strip()),
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

ONLINE_CHANNELS = {"online_research", "online_interview", "archival"}


def validate_rationale(flag: str, rationale: Optional[str]) -> str:
    """Return normalized rationale or raise ValueError on missing red rationale.

    Rules:
      * red   → non-empty rationale required (1-2 sentences explaining the concern).
      * grey  → rationale optional (returned as-is, stripped).
      * green → rationale silently dropped (green facts don't carry rationale).
    """
    text = (rationale or "").strip()
    if flag == FLAG_RED:
        if not text:
            raise ValueError(
                "red fact requires rationale explaining the concern"
            )
        return text
    if flag == FLAG_GREEN:
        return ""
    return text


def validate_provenance(channel: str, source_url: str, evidence_snippet: str,
                        source_title: str = "", flag: str = "green") -> None:
    """Raise ValueError if provenance rules are violated.

    Rule 3: grey flag → evidence_snippet is optional (gap marker doesn't need a quote),
    but source and URL rules still apply.
    """
    snippet_required = flag != "grey"
    if channel in ONLINE_CHANNELS:
        if not source_url.startswith(("http://", "https://")):
            raise ValueError(
                f"{channel} fact requires source_url starting with http(s)://"
            )
        if snippet_required and len(evidence_snippet.strip()) < 20:
            raise ValueError(
                f"{channel} fact requires evidence_snippet ≥20 chars (literal quote from source)"
            )
    elif channel == "offline_interview":
        if not source_title.strip():
            raise ValueError(
                "offline_interview fact requires source_title "
                "(e.g. 'Interview with X 2026-05-12')"
            )


def add_source(conn: sqlite3.Connection, channel: str, title: str = "",
               url: str = "", notes: str = "",
               archive_url: str = "", publisher: str = "", author: str = "") -> int:
    if channel not in ALL_CHANNELS:
        raise ValueError(f"unknown channel {channel}")
    cur = conn.execute(
        """INSERT INTO sources (channel, title, url, notes, archive_url, publisher, author)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (channel, title, url, notes, archive_url or None, publisher, author),
    )
    conn.commit()
    return cur.lastrowid


# ---------- facts ----------

def add_fact(conn: sqlite3.Connection, *, client_id: str, subsection_id: str,
             text: str, flag: str, source_id: Optional[int] = None,
             confidence: float = 1.0, valid_until: Optional[str] = None,
             evidence_snippet: str = "", rationale: Optional[str] = None) -> int:
    if flag not in (FLAG_GREEN, FLAG_RED, FLAG_GREY):
        raise ValueError(f"bad flag {flag}")
    rationale = validate_rationale(flag, rationale)
    # methodological guard: warn if source channel can't really fill this layer
    layer_id = int(subsection_id.split(".")[0])
    if source_id is not None:
        ch = conn.execute("SELECT channel FROM sources WHERE id=?", (source_id,)).fetchone()
        if ch and not channel_can_fill(ch["channel"], layer_id):
            conn.execute(
                "UPDATE sources SET notes = COALESCE(notes,'') || ? WHERE id=?",
                (f"\n[warn] channel {ch['channel']} not primary for layer {layer_id}", source_id),
            )

    cell_id = get_or_create_cell(conn, client_id, subsection_id)
    cur = conn.execute(
        """INSERT INTO facts (cell_id, text, flag, source_id, confidence, valid_until,
                              evidence_snippet, rationale)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (cell_id, text, flag, source_id, confidence, valid_until,
         evidence_snippet, rationale),
    )
    conn.commit()
    fact_id = cur.lastrowid

    if flag == FLAG_GREEN:
        from .workitems import auto_close_on_green_fact
        auto_close_on_green_fact(conn, client_id, subsection_id, fact_id)

    return fact_id


def facts_for_cell(conn: sqlite3.Connection, client_id: str,
                   subsection_id: str) -> List[sqlite3.Row]:
    return list(conn.execute(
        """SELECT f.id, f.cell_id, f.text, f.flag, f.source_id, f.confidence,
                  f.captured_at, f.valid_until, f.evidence_snippet,
                  f.ingest_audit_id, f.rationale, f.created_by,
                  f.snippet_start_sec,
                  s.channel AS source_channel, s.title AS source_title,
                  COALESCE(NULLIF(f.source_url, ''), s.url) AS source_url,
                  s.archive_url AS source_archive_url,
                  s.publisher AS source_publisher,
                  ia.ingest_kind AS ingest_kind,
                  ia.source_artifact AS ingest_artifact
            FROM facts f
            JOIN cells c ON c.id = f.cell_id
            LEFT JOIN sources s ON s.id = f.source_id
            LEFT JOIN ingest_audit ia ON ia.id = f.ingest_audit_id
            WHERE c.client_id=? AND c.subsection_id=?
            ORDER BY f.captured_at DESC""",
        (client_id, subsection_id),
    ))


def get_fact(conn: sqlite3.Connection, fact_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        """SELECT f.id, f.cell_id, f.text, f.flag, f.source_id, f.confidence,
                  f.captured_at, f.valid_until, f.evidence_snippet,
                  f.ingest_audit_id, f.rationale, f.created_by,
                  f.snippet_start_sec,
                  s.channel AS source_channel, s.title AS source_title,
                  COALESCE(NULLIF(f.source_url, ''), s.url) AS source_url,
                  s.archive_url AS source_archive_url,
                  s.publisher AS source_publisher,
                  ia.ingest_kind AS ingest_kind,
                  ia.source_artifact AS ingest_artifact,
                  c.client_id, c.subsection_id
            FROM facts f
            JOIN cells c ON c.id = f.cell_id
            LEFT JOIN sources s ON s.id = f.source_id
            LEFT JOIN ingest_audit ia ON ia.id = f.ingest_audit_id
            WHERE f.id=?""",
        (fact_id,),
    ).fetchone()


def update_fact(conn: sqlite3.Connection, fact_id: int, *,
                text: Optional[str] = None, flag: Optional[str] = None,
                confidence: Optional[float] = None,
                rationale: Optional[str] = None) -> None:
    sets, params = [], []
    if text is not None:
        sets.append("text=?"); params.append(text)
    if flag is not None:
        if flag not in (FLAG_GREEN, FLAG_RED, FLAG_GREY):
            raise ValueError(f"bad flag {flag}")
        sets.append("flag=?"); params.append(flag)
    if confidence is not None:
        sets.append("confidence=?"); params.append(confidence)

    # Re-validate (flag, rationale) only when either is being changed.
    if flag is not None or rationale is not None:
        row = conn.execute(
            "SELECT flag, rationale FROM facts WHERE id=?", (fact_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"fact {fact_id} not found")
        effective_flag = flag if flag is not None else row["flag"]
        effective_rationale = rationale if rationale is not None else (row["rationale"] or "")
        normalized = validate_rationale(effective_flag, effective_rationale)
        if rationale is not None or normalized != (row["rationale"] or ""):
            sets.append("rationale=?"); params.append(normalized)

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
    """Return one row per subsection with green/red/grey counts, last update,
    and the distinct source channels feeding the cell (for matrix infographics)."""
    rows = conn.execute("""
        SELECT s.id AS subsection_id, s.layer_id, s.name AS subsection_name,
               L.name AS layer_name, L.intimacy,
               SUM(CASE WHEN f.flag='green' THEN 1 ELSE 0 END) AS n_green,
               SUM(CASE WHEN f.flag='red'   THEN 1 ELSE 0 END) AS n_red,
               SUM(CASE WHEN f.flag='grey'  THEN 1 ELSE 0 END) AS n_grey,
               MAX(f.captured_at) AS last_update,
               GROUP_CONCAT(DISTINCT src.channel) AS channels
        FROM subsections s
        JOIN layers L ON L.id = s.layer_id
        LEFT JOIN cells c ON c.subsection_id = s.id AND c.client_id = ?
        LEFT JOIN facts f ON f.cell_id = c.id
        LEFT JOIN sources src ON src.id = f.source_id
        GROUP BY s.id
        ORDER BY L.intimacy, s.sort_order
    """, (client_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        raw = d.pop("channels", None)
        d["channels"] = sorted({c for c in (raw.split(",") if raw else []) if c})
        out.append(d)
    return out


def portfolio_summary(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """One row per client with covered/total subsection counts — for the
    sidebar portfolio health bars. `covered` = subsections with >=1 green fact."""
    total = conn.execute("SELECT COUNT(*) FROM subsections").fetchone()[0]
    rows = conn.execute("""
        SELECT cl.id, cl.name, cl.sector,
               COUNT(DISTINCT CASE WHEN f.flag='green' THEN c.subsection_id END) AS covered
        FROM clients cl
        LEFT JOIN cells c ON c.client_id = cl.id
        LEFT JOIN facts f ON f.cell_id = c.id
        GROUP BY cl.id
        ORDER BY cl.name
    """).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["total"] = total
        d["covered"] = d.get("covered") or 0
        out.append(d)
    return out


def my_client_ids(conn: sqlite3.Connection, telegram_id: int) -> set:
    """Client ids the given user has marked as 'mine'."""
    return {r[0] for r in conn.execute(
        "SELECT client_id FROM client_members WHERE telegram_id=?", (telegram_id,))}


def set_client_member(conn: sqlite3.Connection, client_id: str, telegram_id: int, on: bool) -> None:
    if on:
        conn.execute(
            "INSERT OR IGNORE INTO client_members(client_id, telegram_id) VALUES(?, ?)",
            (client_id, telegram_id))
    else:
        conn.execute(
            "DELETE FROM client_members WHERE client_id=? AND telegram_id=?",
            (client_id, telegram_id))
    conn.commit()


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
