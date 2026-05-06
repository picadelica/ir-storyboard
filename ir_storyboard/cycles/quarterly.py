"""Quarterly cycle.

Renders the full matrix for a client as a narrative arc that traverses
all 8 concentric layers. Two traversal modes:
  - 'inside_out' : start at founder personal (1) and zoom out to PEST (8)
  - 'outside_in' : start at historical moment (8) and zoom into the founder (1)
Each layer contributes its strongest green facts; red and grey are surfaced
in a separate honesty section.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional

from .. import matrix
from ..models import (
    LAYERS, layer_by_id, subsection_by_id,
    FLAG_GREEN, FLAG_RED, FLAG_GREY,
)


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
    layers_iter = sorted(LAYERS, key=lambda L: L.intimacy,
                         reverse=(traversal == "outside_in"))

    # Active tracks for context
    tracks = matrix.tracks_for_quarter(conn, client_id, quarter)

    body = _render_quarterly(client, quarter, traversal, layers_iter, tracks,
                              conn, client_id, facts_per_subsection)

    title = f"Quarterly dossier — {client['name']} — {quarter}"
    artifact_id = matrix.save_artifact(
        conn, client_id=client_id, cycle="quarterly",
        title=title, body=body,
        meta={"traversal": traversal, "quarter": quarter},
    )
    return {"artifact_id": artifact_id, "title": title, "body": body}


def _render_quarterly(client, quarter, traversal, layers_iter, tracks, conn,
                      client_id, fps) -> str:
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

    # Main narrative arc
    lines.append("## Narrative arc")
    for L in layers_iter:
        lines.append(f"### L{L.id}. {L.name}")
        layer_had_content = False
        for s in L.subsections:
            facts = matrix.facts_for_cell(conn, client_id, s.id)
            green = [f for f in facts if f["flag"] == FLAG_GREEN][:fps]
            if not green:
                continue
            layer_had_content = True
            lines.append(f"#### {s.name}")
            for f in green:
                lines.append(f"- {f['text']}")
        if not layer_had_content:
            lines.append("_No green-flag content yet — see honesty section._")
        lines.append("")

    # Honesty section: reds + grey-cell punch list
    lines.append("## Honesty section")
    summary = matrix.cell_summary(conn, client_id)
    reds = [r for r in summary if (r["n_red"] or 0) > 0]
    if reds:
        lines.append("### Red flags (acknowledged)")
        for r in reds:
            facts = matrix.facts_for_cell(conn, client_id, r["subsection_id"])
            for f in facts:
                if f["flag"] == FLAG_RED:
                    lines.append(f"- **L{r['subsection_id']} {r['subsection_name']}** — {f['text']}")
        lines.append("")

    empty = matrix.empty_cells(conn, client_id)
    gaps = matrix.cells_with_known_gaps(conn, client_id)
    if empty or gaps:
        lines.append("### Open research targets")
        for r in empty:
            lines.append(f"- L{r['subsection_id']} **{r['layer_name']} → {r['subsection_name']}** "
                         "_— untouched, no facts yet_")
        for r in gaps:
            grey = matrix.grey_facts_for_cell(conn, client_id, r["subsection_id"])
            for g in grey:
                lines.append(f"- L{r['subsection_id']} **{r['layer_name']} → {r['subsection_name']}** "
                             f"_— gap noted:_ {g['text']}")
        lines.append("")

    lines.append("## Notes for NotebookLM")
    article = "an" if traversal.startswith("inside") else "an"
    lines.append(f"- Render this dossier as {article} {traversal.replace('_','-')} arc, "
                  "one layer = one section.")
    lines.append("- Honesty section is part of the narrative, not an appendix.")
    lines.append("- For the 1-quarter recap end on the strongest green flag in L5–L7.")
    return "\n".join(lines)
