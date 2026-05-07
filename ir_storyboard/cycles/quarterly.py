"""Quarterly cycle.

Renders the full matrix for a client as a narrative arc that traverses
all 8 concentric layers. Two traversal modes:
  - 'inside_out' : start at founder personal (1) and zoom out to PEST (8)
  - 'outside_in' : start at historical moment (8) and zoom into the founder (1)
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional

from .. import matrix
from ..llm import generate
from ..models import (
    LAYERS, FLAG_GREEN, FLAG_RED, FLAG_GREY,
    layer_by_id, subsection_by_id,
)

_QUARTERLY_SYSTEM = """\
You are an IR narrative analyst writing a quarterly narrative dossier for a PR/IR agency.
This is NOT a bullet-point report — it is a flowing narrative arc.
Write in the same language as the majority of the facts (Russian or English).

Rules:
- Write prose with clear transitions between layers
- Each layer gets 1-2 paragraphs — move the story forward, don't just list
- Honesty section: address red flags directly, as part of the narrative
- Open research gaps: mention concisely as what the team still needs to uncover
- The dossier feeds NotebookLM — every fact should connect to the next

Structure:
# [Client name] — Quarterly dossier — [Quarter]

## [Layer name]
(prose, 1-2 paragraphs)

## [Next layer name]
...

## Honesty
(red flags as honest narrative, not as appendix)

## Open questions
(gaps, in 3-5 bullet points)
"""


def run_quarterly(
    conn: sqlite3.Connection,
    *,
    client_id: str,
    quarter: str,
    traversal: str = "inside_out",
    facts_per_subsection: int = 2,
) -> Dict[str, Any]:
    if traversal not in ("inside_out", "outside_in"):
        raise ValueError(f"traversal must be inside_out or outside_in, got {traversal}")

    client = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    layers_ordered = sorted(LAYERS, key=lambda L: L.intimacy,
                            reverse=(traversal == "outside_in"))
    tracks = matrix.tracks_for_quarter(conn, client_id, quarter)

    body = _generate_quarterly(client, quarter, traversal, layers_ordered,
                                tracks, conn, client_id, facts_per_subsection)
    title = f"Quarterly dossier — {client['name']} — {quarter}"

    artifact_id = matrix.save_artifact(
        conn, client_id=client_id, cycle="quarterly",
        title=title, body=body,
        meta={"traversal": traversal, "quarter": quarter},
    )
    return {"artifact_id": artifact_id, "title": title, "body": body}


def _generate_quarterly(client, quarter, traversal, layers_ordered,
                        tracks, conn, client_id, fps) -> str:
    summary = matrix.cell_summary(conn, client_id)

    # Build structured content for the prompt (capped to avoid huge contexts)
    layer_sections: List[str] = []
    red_lines: List[str] = []
    gap_lines: List[str] = []

    for L in layers_ordered:
        subsection_lines: List[str] = []
        for s in L.subsections:
            facts = matrix.facts_for_cell(conn, client_id, s.id)
            green = [f["text"] for f in facts if f["flag"] == FLAG_GREEN][:fps]
            reds = [f["text"] for f in facts if f["flag"] == FLAG_RED][:1]
            if green:
                subsection_lines.append(
                    f"  [{s.name}]: " + " | ".join(f'"{t}"' for t in green)
                )
            for r in reds:
                red_lines.append(f"L{s.id} {s.name}: \"{r}\"")
        if subsection_lines:
            layer_sections.append(f"L{L.id} {L.name}:\n" + "\n".join(subsection_lines))

    empty = matrix.empty_cells(conn, client_id)
    gaps = matrix.cells_with_known_gaps(conn, client_id)
    for r in (empty or [])[:5]:
        gap_lines.append(f"L{r['subsection_id']} {r['subsection_name']} — no facts yet")
    for r in (gaps or [])[:5]:
        grey = matrix.grey_facts_for_cell(conn, client_id, r["subsection_id"])
        for g in (grey or [])[:1]:
            gap_lines.append(f"L{r['subsection_id']} {r['subsection_name']} — \"{g['text']}\"")

    tracks_block = "\n".join(
        f"- {t['name']}: {t.get('angle') or '—'}" for t in (tracks or [])
    ) or "None defined"

    user_prompt = (
        f"Client: {client['name']}, sector: {client['sector'] or 'not specified'}\n"
        f"Quarter: {quarter}\n"
        f"Traversal: {traversal.replace('_', '-')}\n"
        f"Active narrative tracks:\n{tracks_block}\n\n"
        "Matrix content (layer by layer):\n"
        + "\n\n".join(layer_sections or ["(no facts in matrix yet)"])
        + "\n\nRed flags:\n"
        + ("\n".join(red_lines) or "None")
        + "\n\nOpen gaps:\n"
        + ("\n".join(gap_lines) or "None")
        + "\n\nWrite the quarterly dossier now."
    )

    llm_body = generate(_QUARTERLY_SYSTEM, user_prompt, max_tokens=2000)
    if llm_body:
        return llm_body

    return _render_template(client, quarter, traversal, layers_ordered,
                             tracks, conn, client_id, fps)


def _render_template(client, quarter, traversal, layers_ordered,
                     tracks, conn, client_id, fps) -> str:
    lines: List[str] = []
    lines.append(f"# Quarterly dossier — {client['name']} — {quarter}")
    lines.append(f"_Date:_ {date.today().isoformat()}  ")
    lines.append(f"_Sector:_ {client['sector'] or '—'}  ")
    lines.append(f"_Traversal:_ {traversal.replace('_', ' ')}")
    lines.append("")

    if tracks:
        lines.append("## Active narrative tracks")
        for t in tracks:
            lines.append(f"- **{t['name']}** — {t.get('angle') or ''}")
        lines.append("")

    lines.append("## Narrative arc")
    for L in layers_ordered:
        lines.append(f"### L{L.id}. {L.name}")
        had = False
        for s in L.subsections:
            facts = matrix.facts_for_cell(conn, client_id, s.id)
            green = [f for f in facts if f["flag"] == FLAG_GREEN][:fps]
            if not green:
                continue
            had = True
            lines.append(f"#### {s.name}")
            for f in green:
                lines.append(f"- {f['text']}")
        if not had:
            lines.append("_No green-flag content yet._")
        lines.append("")

    lines.append("## Honesty section")
    summary = matrix.cell_summary(conn, client_id)
    reds = [r for r in summary if (r["n_red"] or 0) > 0]
    if reds:
        lines.append("### Red flags (acknowledged)")
        for r in reds:
            facts = matrix.facts_for_cell(conn, client_id, r["subsection_id"])
            for f in facts:
                if f["flag"] == FLAG_RED:
                    lines.append(f"- **L{r['subsection_id']}** — {f['text']}")
        lines.append("")
    empty = matrix.empty_cells(conn, client_id)
    gaps = matrix.cells_with_known_gaps(conn, client_id)
    if empty or gaps:
        lines.append("### Open research targets")
        for r in (empty or []):
            lines.append(f"- L{r['subsection_id']} **{r['subsection_name']}** — untouched")
        for r in (gaps or []):
            grey = matrix.grey_facts_for_cell(conn, client_id, r["subsection_id"])
            for g in (grey or [])[:1]:
                lines.append(f"- L{r['subsection_id']} **{r['subsection_name']}** — {g['text']}")
    return "\n".join(lines)
