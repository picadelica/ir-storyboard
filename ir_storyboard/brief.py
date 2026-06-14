"""Brief composer — turn client factology + an analyst prompt into an MD/JSON
bundle that gets pasted into a large external LLM (ChatGPT / Claude / Gemini).

The inverse of ingest: instead of LLM report -> facts, this is facts -> prompt.
The system's edge is provenance — the bundle teaches the external model to
respect the green/red/grey reliability tags and cite sources, which is what
keeps it from hallucinating over a flat "wall of facts".
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from . import matrix
from .models import LAYERS

BRIEF_RULES = (
    "Работай ТОЛЬКО с фактологией ниже — не добавляй внешних фактов и не выдумывай.\n"
    "- [green] = подтверждённый факт, можно утверждать прямо.\n"
    "- [grey] = известный пробел: обозначь как открытый вопрос или опусти, не достраивай.\n"
    "- [red] = факт-риск или противоречие: используй осторожно, с оговоркой.\n"
    "Где у факта есть источник — ссылайся на него."
)

_DEFAULT_TEMPLATES = [
    {
        "name": "Инвест-нарратив",
        "material_type": "investor_narrative",
        "body": (
            "Ты — IR-стратег. На основе фактологии ниже собери связный "
            "инвест-нарратив компании для питча инвесторам.\n\n"
            "Структура:\n"
            "1. Кто это и почему сейчас (1 абзац).\n"
            "2. Команда и трек-рекорд (фаундеры, экспертиза).\n"
            "3. Продукт и его дифференциация.\n"
            "4. Рынок и момент.\n"
            "5. Тяга и проверяемые сигналы.\n"
            "6. Риски и как с ними работают (используй red-факты честно).\n\n"
            "Тон: уверенный, без хайпа. Каждое сильное утверждение — на "
            "проверяемом факте; где источник есть, дай сноску."
        ),
    },
]


# ── templates table ───────────────────────────────────────────────────────────

def ensure_seeded(conn: sqlite3.Connection) -> None:
    """Seed the starter templates once, if the table is empty (idempotent)."""
    n = conn.execute("SELECT COUNT(*) FROM brief_templates").fetchone()[0]
    if n:
        return
    for t in _DEFAULT_TEMPLATES:
        conn.execute(
            "INSERT INTO brief_templates(name, material_type, body) VALUES(?, ?, ?)",
            (t["name"], t["material_type"], t["body"]),
        )
    conn.commit()


def list_templates(conn: sqlite3.Connection) -> list[dict]:
    ensure_seeded(conn)
    return [dict(r) for r in conn.execute(
        "SELECT id, name, material_type, body, created_by, updated_at "
        "FROM brief_templates ORDER BY name")]


def get_template(conn: sqlite3.Connection, tid: int) -> Optional[dict]:
    r = conn.execute(
        "SELECT id, name, material_type, body, created_by, updated_at "
        "FROM brief_templates WHERE id=?", (tid,)).fetchone()
    return dict(r) if r else None


def create_template(conn, name: str, material_type: str, body: str,
                    created_by: Optional[str] = None) -> dict:
    cur = conn.execute(
        "INSERT INTO brief_templates(name, material_type, body, created_by) VALUES(?, ?, ?, ?)",
        (name, material_type, body, created_by))
    conn.commit()
    return get_template(conn, cur.lastrowid)


def update_template(conn, tid: int, *, name=None, material_type=None, body=None) -> Optional[dict]:
    cur = get_template(conn, tid)
    if not cur:
        return None
    conn.execute(
        "UPDATE brief_templates SET name=?, material_type=?, body=?, "
        "updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (name if name is not None else cur["name"],
         material_type if material_type is not None else cur["material_type"],
         body if body is not None else cur["body"], tid))
    conn.commit()
    return get_template(conn, tid)


def delete_template(conn, tid: int) -> None:
    conn.execute("DELETE FROM brief_templates WHERE id=?", (tid,))
    conn.commit()


# ── factology collection + rendering ───────────────────────────────────────────

def collect_factology(conn, client_id: str, flags: Optional[list] = None,
                      layer_ids: Optional[list] = None) -> list[dict]:
    flagset = set(flags) if flags else None
    lids = set(layer_ids) if layer_ids else None
    out = []
    for layer in LAYERS:
        if lids is not None and layer.id not in lids:
            continue
        subs = []
        for sub in layer.subsections:
            facts = []
            for r in matrix.facts_for_cell(conn, client_id, sub.id):
                if flagset is not None and r["flag"] not in flagset:
                    continue
                facts.append({
                    "text": r["text"],
                    "flag": r["flag"],
                    "rationale": r["rationale"] or "",
                    "source": {
                        "url": r["source_url"] or "",
                        "title": r["source_title"] or "",
                        "channel": r["source_channel"] or "",
                        "publisher": r["source_publisher"] or "",
                    },
                })
            if facts:
                subs.append({"subsection_id": sub.id, "subsection_name": sub.name, "facts": facts})
        if subs:
            out.append({"layer_id": layer.id, "layer_name": layer.name, "subsections": subs})
    return out


def _cite(src: dict) -> str:
    label = src.get("publisher") or src.get("title") or src.get("url")
    if not label:
        return ""
    if src.get("url") and label != src["url"]:
        return f" (src: {label} — {src['url']})"
    return f" (src: {label})"


def render_md(client: dict, template: dict, analyst_prompt: str, factology: list) -> str:
    lines = [f"# Brief: {template['name']} — {client['name']}", ""]
    if (analyst_prompt or "").strip():
        lines += ["## Постановка аналитика", analyst_prompt.strip(), ""]
    if (template.get("body") or "").strip():
        lines += ["## Задача", template["body"].strip(), ""]
    lines += ["## Фактология (verified)", ""]
    if not factology:
        lines += ["_(нет фактов под выбранный фильтр)_", ""]
    for layer in factology:
        lines.append(f"### Слой {layer['layer_id']} — {layer['layer_name']}")
        for sub in layer["subsections"]:
            lines.append(f"**{sub['subsection_id']} {sub['subsection_name']}**")
            for f in sub["facts"]:
                lines.append(f"- [{f['flag']}] {f['text']}{_cite(f['source'])}")
                if f["flag"] in ("red", "grey") and f["rationale"]:
                    lines.append(f"  - примечание: {f['rationale']}")
            lines.append("")
    lines += ["## Правила работы с фактологией", BRIEF_RULES, ""]
    return "\n".join(lines)


def render_json(client: dict, template: dict, analyst_prompt: str, factology: list) -> dict:
    facts = []
    for layer in factology:
        for sub in layer["subsections"]:
            for f in sub["facts"]:
                facts.append({
                    "text": f["text"],
                    "flag": f["flag"],
                    "layer_id": layer["layer_id"],
                    "layer_name": layer["layer_name"],
                    "subsection_id": sub["subsection_id"],
                    "subsection_name": sub["subsection_name"],
                    "source": f["source"],
                    "rationale": f["rationale"],
                })
    return {
        "material_type": template.get("material_type", ""),
        "template": template["name"],
        "client": {"id": client["id"], "name": client["name"], "sector": client.get("sector")},
        "instructions": analyst_prompt,
        "task": template.get("body", ""),
        "facts": facts,
        "rules": BRIEF_RULES,
    }
