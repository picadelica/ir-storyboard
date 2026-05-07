"""Weekly cycle.

Input:  client_id, quarter, optional week label.
Logic:  pick the active (highest-priority) narrative track for the quarter,
        focus on its target subsections, pull recent green/red facts,
        produce a video brief — hook + facts + suggested angle.
Output: markdown artifact stored in DB and returned.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from .. import matrix
from ..llm import generate
from ..models import FLAG_GREEN, FLAG_RED, layer_by_id, subsection_by_id

_WEEKLY_SYSTEM = """\
You are an IR narrative analyst writing weekly video briefs for a PR/IR agency.
The brief feeds a scriptwriter or NotebookLM — it must be ready to use, not a list of pointers.
Write in the same language as the facts provided (Russian or English).

Output exactly this structure (markdown):

## Hook
(1-2 punchy sentences that open the piece — concrete, not generic)

## Narrative thread
(2-3 sentences weaving the facts into the track angle — cause → effect → so what)

## Talking points
- (specific, quote-ready)
- (specific, quote-ready)
- (specific, quote-ready)

## Close
(One memorable line to end the 60-90 sec piece)
"""


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
    track = tracks[0]

    target_sids = track["target_subsection_ids"]
    if not target_sids:
        target_sids = []
        for lid in track["target_layer_ids"]:
            target_sids.extend(s.id for s in layer_by_id(lid).subsections)

    pairs: List[Tuple[str, sqlite3.Row]] = []
    for sid in target_sids:
        for f in matrix.facts_for_cell(conn, client_id, sid):
            if f["flag"] in (FLAG_GREEN, FLAG_RED):
                pairs.append((sid, f))
    pairs.sort(key=lambda p: p[1]["captured_at"] or "", reverse=True)
    pairs = pairs[:max_facts]

    client = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()

    body = _generate_weekly(client, track, pairs, week_label)
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


def _generate_weekly(client, track, pairs, week_label) -> str:
    header = (
        f"# Weekly brief — {client['name']}\n"
        f"_Week:_ {week_label}  \n"
        f"_Sector:_ {client['sector'] or '—'}  \n"
        f"_Track:_ **{track['name']}**\n"
    )

    if not pairs:
        return (
            header + "\n"
            "> ⚠ No fresh green/red facts in target cells this week.\n"
            "> Run an ingestion cycle, or work the punch-list of grey cells.\n"
        )

    facts_block = "\n".join(
        f"{i+1}. [{f['flag'].upper()}] L{sid} "
        f"{layer_by_id(int(sid.split('.')[0])).name} → "
        f"{subsection_by_id(sid).name}: \"{f['text']}\""
        for i, (sid, f) in enumerate(pairs)
    )

    user_prompt = (
        f"Client: {client['name']}, sector: {client['sector'] or 'not specified'}\n"
        f"Narrative track: {track['name']}\n"
        f"Track angle: {track.get('angle') or 'not specified'}\n"
        f"Week: {week_label}\n\n"
        f"Facts (newest first):\n{facts_block}\n\n"
        "Write the brief now."
    )

    llm_body = generate(_WEEKLY_SYSTEM, user_prompt, max_tokens=800)
    if llm_body:
        return header + "\n" + llm_body

    # fallback: template render
    return _render_template(client, track, pairs, week_label)


def _render_template(client, track, pairs, week_label) -> str:
    lines: List[str] = []
    lines.append(f"# Weekly brief — {client['name']}")
    lines.append(f"_Week:_ {week_label}  ")
    lines.append(f"_Sector:_ {client['sector'] or '—'}  ")
    lines.append(f"_Track:_ **{track['name']}**  ")
    if track.get("angle"):
        lines.append(f"_Angle:_ {track['angle']}")
    lines.append("")
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
