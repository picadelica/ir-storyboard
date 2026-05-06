"""Event-driven cycle.

Input:  client_id, event description, the layer the event lands in.
Logic:  treat the event as a fresh fact, pull adjacent matrix cells
        (same layer + ±1 layer) for context, suggest 2-3 angles tied to
        active narrative tracks, output a 48-hour reaction brief.
Output: markdown artifact.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional

from .. import matrix
from ..models import FLAG_GREEN, FLAG_RED, layer_by_id, subsection_by_id


def run_event(
    conn: sqlite3.Connection,
    *,
    client_id: str,
    event_text: str,
    landed_subsection_id: str,
    quarter: Optional[str] = None,
) -> Dict[str, Any]:
    landed_layer_id = int(landed_subsection_id.split(".")[0])

    # Pull adjacent context: same layer + immediately concentric neighbours
    context_layer_ids = sorted({
        max(1, landed_layer_id - 1),
        landed_layer_id,
        min(8, landed_layer_id + 1),
    })

    context: List[Dict[str, Any]] = []
    for lid in context_layer_ids:
        for s in layer_by_id(lid).subsections:
            facts = matrix.facts_for_cell(conn, client_id, s.id)
            green = [f for f in facts if f["flag"] == FLAG_GREEN]
            if green:
                context.append({
                    "subsection_id": s.id,
                    "subsection_name": s.name,
                    "layer_id": lid,
                    "layer_name": layer_by_id(lid).name,
                    "best_fact": green[0]["text"],
                })

    # Active tracks (if any) suggest angles
    angles: List[str] = []
    if quarter:
        tracks = matrix.tracks_for_quarter(conn, client_id, quarter)
        for t in tracks:
            if landed_layer_id in t["target_layer_ids"] or landed_subsection_id in t["target_subsection_ids"]:
                angles.append(f"{t['name']}: {t.get('angle') or '—'}")

    client = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    title = f"Event brief — {client['name']} — {date.today().isoformat()}"
    body = _render_event_brief(client, event_text, landed_subsection_id, context, angles)

    artifact_id = matrix.save_artifact(
        conn, client_id=client_id, cycle="event",
        title=title, body=body,
        meta={
            "landed_subsection_id": landed_subsection_id,
            "context_layer_ids": context_layer_ids,
            "angles": angles,
        },
    )
    return {"artifact_id": artifact_id, "title": title, "body": body}


def _render_event_brief(client, event_text, landed_sid, context, angles) -> str:
    sub = subsection_by_id(landed_sid)
    layer = layer_by_id(sub.layer_id if hasattr(sub, "layer_id") else int(landed_sid.split('.')[0]))
    L = layer
    lines: List[str] = []
    lines.append(f"# Event brief — {client['name']}")
    lines.append(f"_Date:_ {date.today().isoformat()}  ")
    lines.append(f"_Window:_ react within 48 hours")
    lines.append("")
    lines.append("## Event")
    lines.append(f"> {event_text}")
    lines.append("")
    lines.append(f"_Lands in:_ **L{landed_sid} — {L.name} → {sub.name}**")
    lines.append("")
    lines.append("## Adjacent context")
    if not context:
        lines.append("_No green-flag context in adjacent cells. Pull from quarterly dossier._")
    else:
        for c in context:
            lines.append(f"- **L{c['subsection_id']} {c['layer_name']} → {c['subsection_name']}**")
            lines.append(f"  {c['best_fact']}")
    lines.append("")
    lines.append("## Suggested angles")
    if angles:
        for a in angles:
            lines.append(f"- {a}")
    else:
        lines.append("_No matching active narrative tracks. Free-form reaction._")
    lines.append("")
    lines.append("## Notes for NotebookLM")
    lines.append("- Open with the event in 1 sentence.")
    lines.append("- Use 1–2 adjacent-context items to widen the frame.")
    lines.append("- Close on the angle, not on the event itself.")
    return "\n".join(lines)
