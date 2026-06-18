"""Fact verification: a skeptical second opinion over research/document facts.

Two mechanisms (both validated on real data):
  - audit_client  : one strong-model pass over a client's non-transcript facts,
                    detecting entity conflation, mis-attribution and fabrication,
                    returning a per-fact verdict + a proposed identity anchor.
  - verify_claims : Tavily web search + a grounded adjudicator verdict per claim.

Trusted-by-provenance facts (YouTube / audio — literal quotes + timecodes) are
NOT verified here. Stub-safe: with no API key, audit/verify return `available=False`
and no findings, so callers degrade gracefully (CI runs offline).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from . import llm
from .models import LAYERS

# Channels whose facts come from documents / deep-research and can hallucinate.
# (online_interview is included only when NOT transcript-grounded — see SQL below.)
VERDICTS = ("ok", "suspect", "refuted")


def _audit_model() -> str:
    return os.environ.get("LLM_AUDIT_MODEL", "claude-sonnet-4-6")


def verifiable_facts(conn, client_id: str) -> List[dict]:
    """Active, non-transcript facts for a client (research/document provenance).

    Skips YouTube/audio facts (grounded by literal quote + timecode)."""
    rows = conn.execute(
        """
        SELECT f.id AS id, c.subsection_id AS sid, f.text AS text, f.flag AS flag,
               COALESCE(s.channel, '') AS channel, COALESCE(s.title, '') AS stitle,
               COALESCE(ia.ingest_kind, '') AS kind
        FROM facts f
        JOIN cells c ON c.id = f.cell_id
        LEFT JOIN sources s ON s.id = f.source_id
        LEFT JOIN ingest_audit ia ON ia.id = f.ingest_audit_id
        WHERE c.client_id = ?
          AND f.state = 'active'
          AND f.snippet_start_sec IS NULL
          AND COALESCE(ia.ingest_kind, '') NOT IN ('youtube', 'audio_file')
        ORDER BY c.subsection_id
        """,
        (client_id,),
    ).fetchall()
    return [dict(r) for r in rows]


_AUDIT_SYSTEM = """Ты — придирчивый fact-checker IR-аналитики. Перед тобой факты, авто-извлечённые из веб-документов и deep-research отчётов про одну компанию. Типичная болезнь таких фактов: КОНФЛЯЦИЯ СУЩНОСТЕЙ — факт про ДРУГОГО человека/компанию подмешан, потому что имена со-встречаются в публичном поле. Бывают также выдумка и внутренние противоречия по атрибуции.

Каждый факт дан как `[id|подсекция|флаг] текст`. Проверь их на согласованность сущностей и верни СТРОГО валидный JSON (без markdown-ограждений) такой формы:

{
  "canonical": {"company": "<реальная компания>", "founders": ["<реальные фаундеры>"], "decoys": ["<двойники: люди/компании с пересекающимися именами, которые НЕ относятся к этой компании>"]},
  "summary": "<1-2 фразы: суть склейки, если есть>",
  "facts": [
    {"id": <id>, "verdict": "suspect|refuted", "entity": "<кому факт принадлежит на самом деле, если не компании: напр. 'Khachuyan — иное лицо' / 'Product Science' / 'выдумка'>", "reason": "<коротко, почему>"}
  ]
}

В "facts" включай ТОЛЬКО подозрительные (suspect) и опровергнутые (refuted) — чистые факты не перечисляй. Если ничего подозрительного — верни "facts": []. verdict=refuted — когда факт почти точно про другую сущность или выдуман; suspect — когда сомнительно и нужна внешняя проверка. Опирайся только на данные фактов."""


def audit_client(conn, client_id: str, *, model: Optional[str] = None) -> Dict[str, Any]:
    """Skeptical entity-conflation audit over a client's verifiable facts.

    Returns {available, canonical, summary, facts:[{id,verdict,entity,reason}],
             n_facts, error}. available=False when no LLM/usable output.
    """
    facts = verifiable_facts(conn, client_id)
    if not facts:
        return {"available": True, "canonical": {}, "summary": "", "facts": [], "n_facts": 0}

    lines = [f"[{f['id']}|{f['sid']}|{(f['flag'] or '?')[0]}] {(f['text'] or '')[:240]}" for f in facts]
    user = "Факты компании (id|подсекция|флаг):\n" + "\n".join(lines)

    raw = llm.generate(_AUDIT_SYSTEM, user, max_tokens=8000, model=model or _audit_model())
    if not raw:
        return {"available": False, "canonical": {}, "summary": "", "facts": [], "n_facts": len(facts)}

    data = _parse_json(raw)
    if data is None:
        return {"available": False, "canonical": {}, "summary": "", "facts": [],
                "n_facts": len(facts), "error": "unparseable"}

    valid_ids = {f["id"] for f in facts}
    out_facts: List[dict] = []
    for it in data.get("facts", []) or []:
        try:
            fid = int(it.get("id"))
        except (TypeError, ValueError):
            continue
        if fid not in valid_ids:
            continue
        verdict = it.get("verdict") if it.get("verdict") in ("suspect", "refuted") else "suspect"
        out_facts.append({
            "id": fid,
            "verdict": verdict,
            "entity": (it.get("entity") or "").strip()[:200],
            "reason": (it.get("reason") or "").strip()[:600],
        })
    canonical = data.get("canonical") if isinstance(data.get("canonical"), dict) else {}
    return {
        "available": True,
        "canonical": canonical,
        "summary": (data.get("summary") or "").strip()[:600],
        "facts": out_facts,
        "n_facts": len(facts),
    }


_VERIFY_SYSTEM = """Ты — придирчивый верификатор фактов IR-аналитики. По каждому утверждению даны реальные результаты веб-поиска. Вынеси вердикт СТРОГО на основе этих результатов (не на общих знаниях), особенно внимательно к КОНФЛЯЦИИ СУЩНОСТЕЙ. Верни валидный JSON (без markdown):

{"results": [{"id": "<id утверждения>", "verdict": "confirmed|refuted|unresolved", "attribution": "<кому факт принадлежит на самом деле, если перепутано>", "reason": "<1-2 фразы со ссылкой на источник>"}]}

confirmed — поиск подтверждает; refuted — поиск противоречит или относит к другой сущности; unresolved — поиск не дал ясного ответа (не додумывай)."""


def verify_claims(claims: List[Dict[str, str]], *, model: Optional[str] = None,
                  max_hits: int = 6) -> Dict[str, Any]:
    """Web-verify claims. Each claim: {id, claim, query}.

    Returns {available, results:[{id, verdict, attribution, reason, sources}]}.
    Stub-safe: no Tavily/LLM → available=False.
    """
    if not claims:
        return {"available": True, "results": []}

    evidence_blocks: List[str] = []
    sources_by_id: Dict[str, List[dict]] = {}
    any_hits = False
    for cl in claims:
        cid = str(cl.get("id"))
        query = cl.get("query") or cl.get("claim") or ""
        hits = llm.web_search(query, max_hits) or []
        if hits:
            any_hits = True
        sources_by_id[cid] = [{"title": h.title, "url": h.url} for h in hits]
        block = f"\n### {cid}. Утверждение: {cl.get('claim','')}\nЗапрос: {query}\nНайдено:\n"
        if not hits:
            block += "  (поиск ничего не вернул)\n"
        for h in hits:
            block += f"  - {h.title[:90]} | {h.url}\n    {h.snippet[:300]}\n"
        evidence_blocks.append(block)

    if not any_hits:
        return {"available": False, "results": []}

    raw = llm.generate(_VERIFY_SYSTEM, "\n".join(evidence_blocks), max_tokens=4000,
                       model=model or _audit_model())
    if not raw:
        return {"available": False, "results": []}
    data = _parse_json(raw)
    if data is None:
        return {"available": False, "results": []}

    results: List[dict] = []
    for it in data.get("results", []) or []:
        cid = str(it.get("id"))
        verdict = it.get("verdict") if it.get("verdict") in ("confirmed", "refuted", "unresolved") else "unresolved"
        results.append({
            "id": cid,
            "verdict": verdict,
            "attribution": (it.get("attribution") or "").strip()[:200],
            "reason": (it.get("reason") or "").strip()[:600],
            "sources": sources_by_id.get(cid, []),
        })
    return {"available": True, "results": results}


_GATE_SYSTEM = """Ты — фильтр на входе IR-матрицы. Дан ЯКОРЬ идентичности (кто реальная компания/фаундеры и кто ДВОЙНИКИ — другие люди/компании с пересекающимися именами) и список новых фактов-кандидатов, извлечённых из веб-документа. Пропусти в матрицу только то, что согласуется с якорем; флагни кандидатов, которые относятся к ДВОЙНИКУ, противоречат якорю или выглядят выдумкой.

Верни СТРОГО валидный JSON (без markdown):
{"facts": [{"i": <индекс кандидата>, "verdict": "suspect|refuted", "entity": "<кому относится, если не компании>", "reason": "<коротко>"}]}

Включай в "facts" ТОЛЬКО проблемные (suspect/refuted). Чистые — не перечисляй. Если якорь пустой/слабый — флагни только явную выдумку. Опирайся на якорь и тексты, не на общие знания."""


def verify_candidates(candidates: List[Dict[str, str]], anchor: Dict[str, Any],
                      *, model: Optional[str] = None) -> List[Dict[str, str]]:
    """Gate new extracted facts against a client's identity anchor BEFORE commit.

    candidates: [{text, subsection_id}]. anchor: {company, founders[], decoys[]}.
    Returns a list aligned by index: [{verdict: ok|suspect|refuted, entity, reason}].
    Stub-safe / no-anchor: returns all 'ok' (nothing held — the matrix re-audit
    still catches the first, anchor-less batch)."""
    out = [{"verdict": "ok", "entity": "", "reason": ""} for _ in candidates]
    if not candidates:
        return out
    has_anchor = bool(anchor and (anchor.get("company") or anchor.get("founders") or anchor.get("decoys")))
    if not has_anchor:
        return out

    anchor_txt = (
        f"Компания: {anchor.get('company') or '?'}\n"
        f"Фаундеры: {', '.join(anchor.get('founders') or []) or '?'}\n"
        f"Двойники (НЕ относятся к компании): {', '.join(anchor.get('decoys') or []) or '—'}"
    )
    lines = [f"[{i}|{c.get('subsection_id','')}] {(c.get('text') or '')[:240]}" for i, c in enumerate(candidates)]
    user = f"ЯКОРЬ:\n{anchor_txt}\n\nКАНДИДАТЫ:\n" + "\n".join(lines)
    raw = llm.generate(_GATE_SYSTEM, user, max_tokens=4000, model=model or _audit_model())
    data = _parse_json(raw) if raw else None
    if data is None:
        return out  # LLM unavailable → don't block ingest (degrade open)
    for it in data.get("facts", []) or []:
        try:
            i = int(it.get("i"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(out):
            verdict = it.get("verdict") if it.get("verdict") in ("suspect", "refuted") else "suspect"
            out[i] = {"verdict": verdict, "entity": (it.get("entity") or "").strip()[:200],
                      "reason": (it.get("reason") or "").strip()[:600]}
    return out


def _parse_json(raw: str) -> Optional[dict]:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, AttributeError):
        return None
