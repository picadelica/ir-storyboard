"""Work-item layer: generates and manages process tasks for IR analysts."""
from __future__ import annotations

import json
import sqlite3
from typing import List, Optional

from .models import LAYERS
from .outputs import QUESTION_TEMPLATES

ACTIVE_STATUSES = ("queued", "in_progress", "needs_review")
INNER_LAYER_IDS = {1, 2, 3}


def _has_active(conn: sqlite3.Connection, client_id: str, type_: str,
                subsection_id: Optional[str]) -> bool:
    """Return True if an active work item of this type already exists for this cell."""
    if subsection_id:
        row = conn.execute(
            """SELECT 1 FROM work_items
                WHERE client_id=? AND type=? AND subsection_id=?
                  AND status IN ('queued','in_progress','needs_review')
                LIMIT 1""",
            (client_id, type_, subsection_id),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT 1 FROM work_items
                WHERE client_id=? AND type=?
                  AND subsection_id IS NULL
                  AND status IN ('queued','in_progress','needs_review')
                LIMIT 1""",
            (client_id, type_),
        ).fetchone()
    return row is not None


def _insert(conn: sqlite3.Connection, *, client_id: str, type_: str,
            subsection_id: Optional[str], source_signal: str, title: str,
            priority: int = 3, rationale: str = "", suggested_channel: str = "",
            related_track_id: Optional[int] = None) -> Optional[int]:
    """Insert a work item if no active duplicate exists. Returns new id or None."""
    if _has_active(conn, client_id, type_, subsection_id):
        return None
    cur = conn.execute(
        """INSERT INTO work_items
            (client_id, type, subsection_id, source_signal, title, priority,
             rationale, suggested_channel, related_track_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (client_id, type_, subsection_id, source_signal, title, priority,
         rationale, suggested_channel or None, related_track_id),
    )
    return cur.lastrowid


def synthesize_work_items(conn: sqlite3.Connection, client_id: str,
                          quarter: Optional[str] = None) -> List[int]:
    """Compare current matrix state with active plan and create new work items.

    Returns list of newly created work item ids (skips duplicates).
    """
    from . import matrix

    # load active track target subsections for priority boost
    track_sids: set[str] = set()
    if quarter:
        for t in matrix.tracks_for_quarter(conn, client_id, quarter):
            track_sids.update(t.get("target_subsection_ids") or [])
    else:
        # load all quarters' tracks
        for row in conn.execute(
            """SELECT target_subsection_ids FROM narrative_tracks t
                JOIN plans p ON p.id = t.plan_id WHERE p.client_id=?""",
            (client_id,),
        ):
            try:
                track_sids.update(json.loads(row[0] or "[]"))
            except Exception:
                pass

    created: List[int] = []

    # ── Rule 1: fill_gap for every empty cell ─────────────────────────────
    for cell in matrix.empty_cells(conn, client_id):
        sid = cell["subsection_id"]
        layer_id = cell["layer_id"]
        layer = next((L for L in LAYERS if L.id == layer_id), None)
        channel = layer.primary_channels[0] if layer else ""
        prio = 2 if sid in track_sids else 3
        title = f"Fill gap: {cell['layer_name']} → {cell['subsection_name']}"
        wid = _insert(conn, client_id=client_id, type_="fill_gap",
                      subsection_id=sid, source_signal="empty_cells",
                      title=title, priority=prio,
                      suggested_channel=channel)
        if wid:
            created.append(wid)

    # ── Rule 2: interview for inner-layer empty or gap cells ──────────────
    inner_sids = {
        r["subsection_id"]
        for r in (matrix.empty_cells(conn, client_id) +
                  matrix.cells_with_known_gaps(conn, client_id))
        if r["layer_id"] in INNER_LAYER_IDS
    }
    for sid in inner_sids:
        sub = next(
            (s for L in LAYERS if L.id in INNER_LAYER_IDS for s in L.subsections if s.id == sid),
            None,
        )
        if not sub:
            continue
        question = QUESTION_TEMPLATES.get(sid, f"Расскажи подробнее про {sub.name}.")
        title = f"Interview: {sub.name} ({sid})"
        wid = _insert(conn, client_id=client_id, type_="interview",
                      subsection_id=sid, source_signal="empty_cells",
                      title=title, priority=2,
                      rationale=question,
                      suggested_channel="offline_interview")
        if wid:
            created.append(wid)

    # ── Rule 3: deepen for thinly covered cells (n_green≥1, n_grey==0) ───
    for cell in matrix.thinly_covered_cells(conn, client_id, min_green=2):
        if (cell["n_green"] or 0) < 1 or (cell["n_grey"] or 0) > 0:
            continue
        sid = cell["subsection_id"]
        prio = 3 if sid in track_sids else 4
        title = f"Deepen: {cell['layer_name']} → {cell['subsection_name']} ({cell['n_green']} green)"
        wid = _insert(conn, client_id=client_id, type_="deepen",
                      subsection_id=sid, source_signal="thin_coverage",
                      title=title, priority=prio)
        if wid:
            created.append(wid)

    # ── Rule 4: verify for low-confidence facts ────────────────────────────
    low_conf = conn.execute(
        """SELECT f.id, f.confidence, c.subsection_id, s.name AS sub_name
            FROM facts f
            JOIN cells c ON c.id = f.cell_id
            JOIN subsections s ON s.id = c.subsection_id
            WHERE c.client_id=? AND f.confidence < 0.7""",
        (client_id,),
    ).fetchall()
    for row in low_conf:
        sid = row["subsection_id"]
        title = f"Verify: low-confidence fact in {row['sub_name']} ({row['id']})"
        if _has_active(conn, client_id, "verify", sid):
            continue
        cur = conn.execute(
            """INSERT INTO work_items
                (client_id, type, subsection_id, source_signal, title, priority,
                 rationale, related_fact_id)
                VALUES (?, 'verify', ?, 'low_confidence', ?, 3, ?, ?)""",
            (client_id, sid, title,
             f"confidence={row['confidence']:.2f} — cross-check needed",
             row["id"]),
        )
        created.append(cur.lastrowid)

    conn.commit()
    return created


def auto_close_on_green_fact(conn: sqlite3.Connection, client_id: str,
                             subsection_id: str, fact_id: int) -> None:
    """When a green fact is added, move active fill_gap/deepen/interview items
    for that cell to needs_review status."""
    try:
        conn.execute(
            """UPDATE work_items
                SET status='needs_review', related_fact_id=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE client_id=? AND subsection_id=?
                  AND type IN ('fill_gap','deepen','interview')
                  AND status IN ('queued','in_progress')""",
            (fact_id, client_id, subsection_id),
        )
        conn.commit()
    except Exception:
        pass  # table may not exist on old DBs
