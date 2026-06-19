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
import re
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

В "facts" включай ТОЛЬКО подозрительные (suspect) и опровергнутые (refuted) — чистые факты не перечисляй. Если ничего подозрительного — верни "facts": []. verdict=refuted — когда факт почти точно про другую сущность или выдуман; suspect — когда сомнительно и нужна внешняя проверка. Опирайся только на данные фактов.

ВАЖНО: ответ — только JSON-объект, без преамбулы, рассуждений и текста до или после него."""


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

    data = _generate_json(_AUDIT_SYSTEM, user, max_tokens=8000, model=model or _audit_model())
    if data is None:
        return {"available": False, "canonical": {}, "summary": "", "facts": [], "n_facts": len(facts)}

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

    data = _generate_json(_VERIFY_SYSTEM, "\n".join(evidence_blocks), max_tokens=4000,
                          model=model or _audit_model())
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
    data = _generate_json(_GATE_SYSTEM, user, max_tokens=4000, model=model or _audit_model())
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


_DEDUP_SYSTEM = """Ты — дедупликатор фактов IR-матрицы. Дан список фактов `[id|подсекция|текст]`. Найди группы, где факты утверждают ОДНО И ТО ЖЕ (околодубли — та же мысль, возможно иными словами), ТОЛЬКО в пределах одной подсекции.

Верни СТРОГО валидный JSON (без markdown):
{"groups": [{"subsection_id": "X.Y", "keep": <id с самой полной/точной формулировкой>, "ids": [<все id группы, включая keep>], "reason": "<коротко что общего>"}]}

Группа — минимум 2 id из ОДНОЙ подсекции. Факты с разными деталями/числами НЕ объединяй. Дублей нет → "groups": []."""


def _active_facts(conn, client_id: str) -> List[dict]:
    rows = conn.execute(
        """SELECT f.id AS id, c.subsection_id AS sid, f.text AS text
            FROM facts f JOIN cells c ON c.id = f.cell_id
            WHERE c.client_id=? AND f.state='active' ORDER BY c.subsection_id, f.id""",
        (client_id,)).fetchall()
    return [dict(r) for r in rows]


def find_duplicate_groups(conn, client_id: str, *, model: Optional[str] = None) -> Dict[str, Any]:
    """LLM-cluster same-meaning active facts (per subsection) for merge proposals.

    Returns {available, groups:[{subsection_id, keep, ids:[...], reason, facts:[{id,text}]}]}.
    Stub-safe."""
    facts = _active_facts(conn, client_id)
    by_id = {f["id"]: f for f in facts}
    if len(facts) < 2:
        return {"available": True, "groups": []}
    lines = [f"[{f['id']}|{f['sid']}] {(f['text'] or '')[:200]}" for f in facts]
    data = _generate_json(_DEDUP_SYSTEM, "Факты:\n" + "\n".join(lines), max_tokens=6000,
                          model=model or _audit_model())
    if data is None:
        return {"available": False, "groups": []}

    groups: List[dict] = []
    for g in data.get("groups", []) or []:
        ids = [int(i) for i in (g.get("ids") or []) if isinstance(i, (int, str)) and str(i).isdigit()]
        ids = [i for i in ids if i in by_id]
        if len(ids) < 2:
            continue
        # all in one subsection
        sids = {by_id[i]["sid"] for i in ids}
        if len(sids) != 1:
            continue
        keep = g.get("keep")
        keep = int(keep) if str(keep).isdigit() and int(keep) in ids else ids[0]
        groups.append({
            "subsection_id": next(iter(sids)),
            "keep": keep,
            "ids": ids,
            "reason": (g.get("reason") or "").strip()[:300],
            "facts": [{"id": i, "text": by_id[i]["text"]} for i in ids],
        })
    return {"available": True, "groups": groups}


def _generate_json(system: str, user: str, *, max_tokens: int,
                   model: Optional[str], attempts: int = 2) -> Optional[dict]:
    """llm.generate + tolerant JSON parse, retried on an empty/unparseable reply.

    A strong model occasionally returns an empty or malformed body (overload,
    truncation) — without a retry that surfaced as a misleading "verifier
    unavailable". One extra attempt heals the common transient. Returns the
    parsed dict, or None if every attempt failed (no key / persistent error)."""
    for _ in range(max(1, attempts)):
        raw = llm.generate(system, user, max_tokens=max_tokens, model=model)
        if raw:
            data = _parse_json(raw)
            if data is not None:
                return data
    return None


def _parse_json(raw: str) -> Optional[dict]:
    """Extract a JSON object from an LLM reply, tolerant of chatty models.

    Models (esp. sonnet) often wrap the JSON in a ```fence``` and/or precede it
    with a prose preamble ("I need to analyze..."). Try, in order: the whole
    string, the contents of a fenced block anywhere, and the widest {...} span.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    candidates: List[str] = [raw]
    m = re.search(r"```(?:json)?\s*(.+?)```", raw, re.DOTALL)
    if m:
        candidates.append(m.group(1).strip())
    i, j = raw.find("{"), raw.rfind("}")
    if 0 <= i < j:
        candidates.append(raw[i : j + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(data, dict):
            return data
    return None
