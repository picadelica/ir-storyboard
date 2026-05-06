"""Output generators that read the matrix and produce artifacts for the analyst.

  - notebooklm_package : a curated markdown bundle for direct upload to NotebookLM
  - punch_list         : grey cells + recommended channel to fill them
  - interview_questions: grey cells in interview-only layers, framed as questions
  - scorecard          : green/red/grey counts per layer for the IR client report
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from . import matrix
from .models import (
    LAYERS, layer_by_id, subsection_by_id,
    CHANNEL_OFFLINE_INTERVIEW, CHANNEL_ONLINE_INTERVIEW,
    CHANNEL_ONLINE_RESEARCH, CHANNEL_ARCHIVAL,
    FLAG_GREEN, FLAG_RED, FLAG_GREY,
)


# ---------- NotebookLM package ----------

def notebooklm_package(conn: sqlite3.Connection, *, client_id: str,
                       artifact_ids: List[int]) -> str:
    """Bundle one or more cycle artifacts into a single markdown file
    suitable for upload to NotebookLM as the source set."""
    client = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    out: List[str] = []
    out.append(f"# NotebookLM source bundle — {client['name']}")
    out.append(f"_Generated:_ {date.today().isoformat()}")
    out.append("")
    out.append("> Curated package: focused inputs for one production run.")
    out.append("> Do not feed the entire matrix — NotebookLM works best with "
               "5–8 well-chosen sources.")
    out.append("")

    for aid in artifact_ids:
        a = conn.execute("SELECT * FROM artifacts WHERE id=?", (aid,)).fetchone()
        if not a:
            continue
        out.append(f"---")
        out.append(f"## {a['title']}")
        out.append(f"_cycle:_ {a['cycle']}")
        out.append("")
        out.append(a["body"])
        out.append("")
    return "\n".join(out)


# ---------- punch list ----------

def punch_list(conn: sqlite3.Connection, *, client_id: str,
               thin_threshold: int = 2) -> str:
    """Three categories:
       1. Untouched cells — no facts at all.
       2. Cells with explicit gaps — grey-flagged 'we know we don't know'.
       3. Thinly covered cells — fewer than `thin_threshold` green facts.
    """
    empty = matrix.empty_cells(conn, client_id)
    gaps = matrix.cells_with_known_gaps(conn, client_id)
    thin = [r for r in matrix.thinly_covered_cells(conn, client_id, min_green=thin_threshold)
            if (r["n_green"] or 0) >= 1 and (r["n_grey"] or 0) == 0]
    client = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()

    out: List[str] = []
    out.append(f"# Punch-list — {client['name']}")
    out.append(f"_Generated:_ {date.today().isoformat()}")
    out.append("")

    if not (empty or gaps or thin):
        out.append("✅ Matrix is fully populated and well-covered.")
        return "\n".join(out)

    if empty:
        out.append("## 1. Untouched cells (no facts of any kind)")
        out.append("| Cell | Layer → Subsection | Suggested channel |")
        out.append("|---|---|---|")
        for r in empty:
            L = layer_by_id(r["layer_id"])
            primary = ", ".join(L.primary_channels)
            out.append(f"| L{r['subsection_id']} | {L.name} → {r['subsection_name']} | {primary} |")
        out.append("")

    if gaps:
        out.append("## 2. Explicit gaps (we know we don't know)")
        out.append("| Cell | Subsection | Gap | Suggested channel |")
        out.append("|---|---|---|---|")
        for r in gaps:
            L = layer_by_id(r["layer_id"])
            primary = ", ".join(L.primary_channels)
            for g in matrix.grey_facts_for_cell(conn, client_id, r["subsection_id"]):
                out.append(f"| L{r['subsection_id']} | {r['subsection_name']} | {g['text']} | {primary} |")
        out.append("")

    if thin:
        out.append(f"## 3. Thin coverage (< {thin_threshold} green facts)")
        out.append("| Cell | Layer → Subsection | green count |")
        out.append("|---|---|---:|")
        for r in thin:
            L = layer_by_id(r["layer_id"])
            out.append(f"| L{r['subsection_id']} | {L.name} → {r['subsection_name']} | {r['n_green'] or 0} |")
        out.append("")

    return "\n".join(out)


# ---------- interview questions ----------

INTERVIEWABLE_LAYER_IDS = {1, 2, 3}   # layers fillable only via interview


QUESTION_TEMPLATES = {
    "1.1": "Расскажи про детство — где рос, что было важно в семье, какой эпизод запомнился больше всего?",
    "1.2": "Что для тебя — несгибаемые ценности? Когда последний раз пришлось выбирать между ценностью и выгодой?",
    "1.3": "Какой момент в жизни напугал больше всего? Что ты тогда понял про себя?",
    "1.4": "Если бы получилось всё, что ты задумал — как выглядит мир через 10 лет? Что в этом мире — твоё?",
    "2.1": "Расскажи путь к нынешней экспертизе — какие повороты были неожиданными, у кого учился больше всего?",
    "2.2": "Какую роль ты сейчас играешь в компании по-настоящему — не по титулу? Что тебя в ней держит?",
    "2.3": "Как вы с сооснователями принимаете решения, когда не согласны? Был ли конфликт, который вас укрепил?",
    "3.1": "Как вы выбираете людей в команду / клуб? Какой признак ты заметишь за 10 минут разговора?",
    "3.2": "Опиши день, когда сообщество ощущалось настоящим. Что происходило, кто был, что говорили?",
    "3.3": "Кто из инвесторов / партнёров за последний год сделал что-то, чего по контракту делать не должен был?",
}


def interview_questions(conn: sqlite3.Connection, *, client_id: str) -> str:
    """Inner layers (1–3) need interview channels. Pull empty + grey-marked
    cells in those layers and turn each into a question."""
    empty = matrix.empty_cells(conn, client_id)
    gaps = matrix.cells_with_known_gaps(conn, client_id)
    inner = [r for r in (empty + gaps) if r["layer_id"] in INTERVIEWABLE_LAYER_IDS]
    # de-dupe by subsection id, prefer gap rows
    seen = {}
    for r in inner:
        seen[r["subsection_id"]] = r
    inner = list(seen.values())

    client = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()

    out: List[str] = []
    out.append(f"# Interview questions — {client['name']}")
    out.append(f"_Generated:_ {date.today().isoformat()}")
    out.append("")
    out.append("These cells cannot be reliably filled by web search. "
               "Bring this list to the next interview with the founder / community.")
    out.append("")

    if not inner:
        out.append("✅ Inner layers (1–3) are populated. No interview prompts needed right now.")
        return "\n".join(out)

    by_layer: Dict[int, List[Dict[str, Any]]] = {}
    for r in inner:
        by_layer.setdefault(r["layer_id"], []).append(r)

    for lid in sorted(by_layer):
        L = layer_by_id(lid)
        out.append(f"## L{L.id} — {L.name}")
        for r in sorted(by_layer[lid], key=lambda x: x["subsection_id"]):
            sid = r["subsection_id"]
            q = QUESTION_TEMPLATES.get(sid, f"Расскажи подробнее про **{r['subsection_name']}**.")
            # If there are explicit gap facts, surface them as bullet hints
            grey = matrix.grey_facts_for_cell(conn, client_id, sid)
            out.append(f"- **{sid} {r['subsection_name']}** — {q}")
            for g in grey:
                out.append(f"  _gap noted:_ {g['text']}")
        out.append("")
    return "\n".join(out)


# ---------- scorecard ----------

def scorecard(conn: sqlite3.Connection, *, client_id: str) -> str:
    summary = matrix.cell_summary(conn, client_id)
    client = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()

    # Group by layer
    by_layer: Dict[int, List[Dict[str, Any]]] = {}
    for r in summary:
        by_layer.setdefault(r["layer_id"], []).append(r)

    out: List[str] = []
    out.append(f"# Green-flag scorecard — {client['name']}")
    out.append(f"_Generated:_ {date.today().isoformat()}")
    out.append("")
    out.append("| Layer | Subsection | 🟢 | 🔴 | ⚪ implicit-grey | last update |")
    out.append("|---|---|---:|---:|---:|---|")

    total_g = total_r = total_grey_cells = 0
    for L in LAYERS:
        rows = by_layer.get(L.id, [])
        for r in rows:
            ng = r["n_green"] or 0
            nr = r["n_red"] or 0
            implicit = "•" if ng == 0 and nr == 0 else ""
            if implicit:
                total_grey_cells += 1
            total_g += ng
            total_r += nr
            last = (r["last_update"] or "")[:10]
            out.append(f"| L{L.id} {L.name} | {r['subsection_name']} | {ng} | {nr} | {implicit} | {last} |")
    out.append("")
    out.append(f"**Totals:** 🟢 {total_g} green facts · 🔴 {total_r} red facts · "
               f"⚪ {total_grey_cells} cells with no signal yet.")
    return "\n".join(out)


# ---------- write all to disk ----------

def write_all(conn: sqlite3.Connection, *, client_id: str, out_dir: Path,
              weekly_artifact_id: int, event_artifact_id: int,
              quarterly_artifact_id: int) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files: Dict[str, Path] = {}

    p = out_dir / "notebooklm_bundle.md"
    p.write_text(notebooklm_package(
        conn, client_id=client_id,
        artifact_ids=[weekly_artifact_id, event_artifact_id, quarterly_artifact_id],
    ), encoding="utf-8")
    files["notebooklm_bundle"] = p

    p = out_dir / "punch_list.md"
    p.write_text(punch_list(conn, client_id=client_id), encoding="utf-8")
    files["punch_list"] = p

    p = out_dir / "interview_questions.md"
    p.write_text(interview_questions(conn, client_id=client_id), encoding="utf-8")
    files["interview_questions"] = p

    p = out_dir / "scorecard.md"
    p.write_text(scorecard(conn, client_id=client_id), encoding="utf-8")
    files["scorecard"] = p

    # Each cycle artifact also written as its own file for direct opening
    for aid, fname in [
        (weekly_artifact_id, "weekly_brief.md"),
        (event_artifact_id, "event_brief.md"),
        (quarterly_artifact_id, "quarterly_dossier.md"),
    ]:
        a = conn.execute("SELECT * FROM artifacts WHERE id=?", (aid,)).fetchone()
        if a:
            (out_dir / fname).write_text(a["body"], encoding="utf-8")
            files[fname.replace(".md", "")] = out_dir / fname

    return files
