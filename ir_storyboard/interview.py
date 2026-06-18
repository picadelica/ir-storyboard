"""Grounded interview guide — a per-founder prep doc built from the VERIFIED
matrix (active, non-suspect facts) + the identity anchor. Replaces the static
question templates: every question is grounded in what's already known, ordered
by the concentric-intimacy arc, and targets the real gaps.

One strong-model pass → structured JSON {dossier, diagnosis, arcs[]}. Stub-safe.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from . import llm
from .models import LAYERS


def _guide_model() -> str:
    return os.environ.get("LLM_GUIDE_MODEL", "claude-sonnet-4-6")


def _clean_facts_by_cell(conn, client_id: str) -> Dict[str, List[dict]]:
    """Active, non-flagged facts grouped by subsection (the grounding material)."""
    rows = conn.execute(
        """SELECT c.subsection_id AS sid, f.text AS text, f.flag AS flag
            FROM facts f JOIN cells c ON c.id = f.cell_id
            WHERE c.client_id = ? AND f.state = 'active'
              AND f.verification NOT IN ('suspect', 'refuted')
            ORDER BY c.subsection_id, f.id""",
        (client_id,)).fetchall()
    out: Dict[str, List[dict]] = {}
    for r in rows:
        out.setdefault(r["sid"], []).append({"text": r["text"], "flag": r["flag"]})
    return out


_SYSTEM = """Ты — старший IR-интервьюер и нарративный аналитик. На основе матрицы знаний (только ПРОВЕРЕННЫЕ факты) подготовь интервьюера к разговору с фаундером.

Методология — 8 концентрических слоёв близости × 3 подсекции (1 = самое личное, 8 = внешний контекст). Внутренние слои 1–3 заполняются ТОЛЬКО живым интервью; внешние (продукт 6, видение 7, контекст 8, инвесторы 3.3) можно подтверждать/обогащать у фаундера. Флаги: g — подтверждённый позитив, r — риск/противоречие/концерн, y — явный гэп. ВАЖНО: r на личных слоях (1.x) и в 7.2 (противоречия/цена) — часто эмоциональное ядро истории, его надо бережно раскрывать, а не избегать.

Принципы:
- Каждый вопрос ГРУНТОВАН на конкретных известных фактах — ссылайся («ты говорил, что…»). Никаких generic-шаблонов.
- Дуга по близости: человек/разогрев → профессиональное → команда/сообщество → трудное (противоречия, провалы, страхи) → видение/legacy.
- На каждый вопрос 1–2 follow-up, чтобы добывать СЦЕНЫ и анекдоты (show, don't tell).
- Приоритет: пустые/тонкие внутренние ячейки; красные кластеры под авторскую рамку фаундера; противоречия между фактами.

Верни СТРОГО валидный JSON (без markdown), на русском:
{
  "dossier": "<1-2 плотных абзаца: кто фаундер/компания, какая история проступает, центральное напряжение>",
  "diagnosis": {"covered": "<что сильно покрыто>", "gaps": "<что зияет/тонко>", "priorities": ["<топ-приоритет на это интервью>", "..."]},
  "arcs": [
    {"title": "<название дуги>", "questions": [
      {"question": "<грунтованный вопрос>", "targets": ["X.Y", "..."], "know": "<что уже знаем>", "close": "<что закрываем>", "followups": ["<уточняющий>", "..."]}
    ]}
  ]
}
Опирайся ТОЛЬКО на факты матрицы и якорь — не выдумывай. Будь конкретным и человечным."""


def build_guide(conn, client_id: str, *, model: Optional[str] = None) -> Dict[str, Any]:
    """Returns {available, dossier, diagnosis:{covered,gaps,priorities[]}, arcs:[...], n_facts}."""
    by_cell = _clean_facts_by_cell(conn, client_id)
    n_facts = sum(len(v) for v in by_cell.values())
    if n_facts == 0:
        return {"available": True, "dossier": "", "diagnosis": {}, "arcs": [], "n_facts": 0}

    from . import matrix
    anchor = matrix.entity_anchor(conn, client_id)

    lines: List[str] = []
    for L in LAYERS:
        for s in L.subsections:
            fs = by_cell.get(s.id, [])
            tag = "ПУСТО" if not fs else f"{len(fs)} факт(ов)"
            lines.append(f"\n[{s.id}] {s.name} ({L.name}) — {tag}")
            for f in fs:
                lines.append(f"  ({(f['flag'] or '?')[0]}) {(f['text'] or '')[:220]}")
    anchor_txt = ""
    if anchor.get("company") or anchor.get("founders"):
        anchor_txt = (f"ЯКОРЬ — компания: {anchor.get('company') or '?'}; "
                      f"фаундеры: {', '.join(anchor.get('founders') or []) or '?'}; "
                      f"НЕ путать с: {', '.join(anchor.get('decoys') or []) or '—'}\n\n")
    user = anchor_txt + "МАТРИЦА ЗНАНИЙ (проверенные факты):\n" + "\n".join(lines)

    raw = llm.generate(_SYSTEM, user, max_tokens=8000, model=model or _guide_model())
    if not raw:
        return {"available": False, "dossier": "", "diagnosis": {}, "arcs": [], "n_facts": n_facts}
    data = _parse(raw)
    if data is None:
        return {"available": False, "dossier": "", "diagnosis": {}, "arcs": [], "n_facts": n_facts}

    diag = data.get("diagnosis") if isinstance(data.get("diagnosis"), dict) else {}
    arcs_out: List[dict] = []
    for a in data.get("arcs", []) or []:
        if not isinstance(a, dict):
            continue
        qs: List[dict] = []
        for q in a.get("questions", []) or []:
            if not isinstance(q, dict) or not q.get("question"):
                continue
            qs.append({
                "question": str(q.get("question"))[:1000],
                "targets": [str(t) for t in (q.get("targets") or []) if t][:6],
                "know": str(q.get("know") or "")[:600],
                "close": str(q.get("close") or "")[:600],
                "followups": [str(f) for f in (q.get("followups") or []) if f][:4],
            })
        if qs:
            arcs_out.append({"title": str(a.get("title") or "")[:120], "questions": qs})
    return {
        "available": True,
        "dossier": str(data.get("dossier") or "")[:3000],
        "diagnosis": {
            "covered": str(diag.get("covered") or "")[:800],
            "gaps": str(diag.get("gaps") or "")[:800],
            "priorities": [str(p) for p in (diag.get("priorities") or []) if p][:8],
        },
        "arcs": arcs_out,
        "n_facts": n_facts,
    }


def _parse(raw: str) -> Optional[dict]:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else None
    except (json.JSONDecodeError, AttributeError):
        return None
