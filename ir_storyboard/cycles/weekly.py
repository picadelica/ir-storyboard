"""Weekly cycle.

Input:  client_id, quarter, optional week label.
Logic:  pick the active (highest-priority) narrative track for the quarter,
        focus on its target subsections, pull recent green/red facts,
        produce a video brief — hook + facts + suggested angle.
Output: markdown artifact stored in DB and returned.

The brief is meant to feed NotebookLM (or a human scriptwriter), not to be
a publishable script.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from .. import matrix
from ..models import FLAG_GREEN, FLAG_RED, layer_by_id, subsection_by_id


def run_weekly(
    conn: sqlite3.Connection,
    *,
    client_id: str,
    quarter: str,
    week_label: Optional[str] = None,
    max_facts: int = 3,
) -> Dict[str, Any]:
    week_label = week_label or date.today().isoformat()

    tracks = matrix.tracks_for_quarter(conn, client_id, quarter)
    if not tracks:
        raise RuntimeError(
            f"No narrative tracks for {client_id} in {quarter}. Define a plan first."
        )
    track = tracks[0]  # highest priority

    target_sids = track["target_subsection_ids"]
    if not target_sids:
        target_sids = []
        for lid in track["target_layer_ids"]:
            target_sids.extend(s.id for s in layer_by_id(lid).subsections)

    # Collect (subsection_id, fact_row) pairs so we can label by cell
    pairs: List[Tuple[str, sqlite3.Row]] = []
    for sid in target_sids:
        for f in matrix.facts_for_cell(conn, client_id, sid):
            if f["flag"] in (FLAG_GREEN, FLAG_RED):
                pairs.append((sid, f))
    pairs.sort(key=lambda p: p[1]["captured_at"] or "", reverse=True)
    pairs = pairs[:max_facts]

    client = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    body = _render_weekly_brief(client, track, pairs, week_label)
    title = f"Weekly brief — {client['name']} — {week_label}"

    artifact_id = matrix.save_artifact(
        conn, client_id=client_id, cycle="weekly",
        title=title, body=body,
        meta={
            "track_id": track["id"],
            "track_name": track["name"],
            "fact_ids": [p[1]["id"] for p in pairs],
            "week_label": week_label,
        },
    )

    return {"artifact_id": artifact_id, "title": title, "body": body}


def _render_weekly_brief(client, track, pairs, week_label) -> str:
    lines: List[str] = []
    lines.append(f"# Weekly brief — {client['name']}")
    lines.append(f"_Week:_ {week_label}  ")
    lines.append(f"_Sector:_ {client['sector'] or '—'}  ")
    lines.append(f"_Track:_ **{track['name']}**  ")
    if track.get("angle"):
        lines.append(f"_Angle:_ {track['angle']}")
    lines.append("")

    if not pairs:
        lines.append("> ⚠ No fresh green/red facts in target cells this week.")
        lines.append("> Run an ingestion cycle, or work the punch-list of grey cells.")
        return "\n".join(lines)

    lines.append("## Hook")
    lines.append(f"_Suggested angle:_ {track.get('angle') or track['name']}")
    lines.append("")
    lines.append("## Facts (newest first)")
    for sid, f in pairs:
        sub_name = subsection_by_id(sid).name
        layer_name = layer_by_id(int(sid.split('.')[0])).name
        lines.append(f"- **[{f['flag'].upper()}] L{sid} {layer_name} → {sub_name}**")
        lines.append(f"  {f['text']}")
        if f["source_url"]:
            lines.append(f"  _source:_ [{f['source_title'] or f['source_url']}]({f['source_url']})")
    lines.append("")
    lines.append("## Notes for NotebookLM")
    lines.append(f"- Anchor the piece in narrative track **{track['name']}**.")
    lines.append("- Lead with the hook; each fact should advance a green flag.")
    lines.append("- Keep length 60–90 seconds; pick the strongest fact for the close.")
    return "\n".join(lines)
