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
{"groups": [{"subsection_id": "X.Y", "keep": <id с самой полной/точной формулировкой>, "ids": [<все id группы, включая keep>], "reason": "<коротко что общего>", "merged_text": "<одна точная формулировка, вбирающая все детали группы>"}]}

merged_text — твой ПРЕДЛАГАЕМЫЙ единый текст факта, который объединяет всё важное из группы (особенно если фактов больше двух): без потери деталей, без воды, тем же языком, что и факты. Аналитик потом отредактирует.

Группа — минимум 2 id из ОДНОЙ подсекции. Факты с разными деталями/числами НЕ объединяй. Дублей нет → "groups": []."""


# Max facts per dedup LLM call — keeps the prompt/response from truncating when one
# subsection holds many facts. ~30 atomic facts fit comfortably in a 2000-token reply.
_DEDUP_BATCH = 30


def _chunked(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _fact_card_fields(conn, fid: int) -> Optional[dict]:
    """Source-line fields for a fact so the UI can render it exactly like a matrix
    card (flag + text + source link/timecode) inside the merge preview."""
    from . import matrix
    r = matrix.get_fact(conn, fid)
    if r is None:
        return None
    keys = r.keys()
    g = lambda k: (r[k] if k in keys else None)  # noqa: E731
    return {
        "id": r["id"], "text": r["text"] or "", "flag": r["flag"],
        "source_url": g("source_url") or "", "source_title": g("source_title") or "",
        "source_channel": g("source_channel") or "", "source_publisher": g("source_publisher") or "",
        "source_archive_url": g("source_archive_url") or "",
        "snippet_start_sec": g("snippet_start_sec"),
        "ingest_audit_id": g("ingest_audit_id") or "",
        "ingest_kind": g("ingest_kind") or "",
        "captured_at": g("captured_at") or "",
    }


_DEDUP_SUB_SYSTEM = """Ты — дедупликатор фактов одной подсекции IR-матрицы. Дан список фактов `[id] текст` (все из ОДНОЙ подсекции). Найди группы, где факты утверждают ОДНО И ТО ЖЕ (околодубли — та же мысль, возможно иными словами).

Верни СТРОГО валидный JSON (без markdown):
{"groups": [{"keep": <id с самой полной/точной формулировкой>, "ids": [<все id группы, включая keep>], "reason": "<коротко что общего>", "merged_text": "<одна точная формулировка, вбирающая все детали группы>"}]}

merged_text — предлагаемый единый текст факта, вбирающий всё важное из группы (особенно при >2 фактах): без потери деталей, тем же языком. Аналитик потом отредактирует.

Группа — минимум 2 id. Факты с разными деталями/числами НЕ объединяй. Дублей нет → "groups": []."""


def _active_facts(conn, client_id: str) -> List[dict]:
    rows = conn.execute(
        """SELECT f.id AS id, c.subsection_id AS sid, f.text AS text
            FROM facts f JOIN cells c ON c.id = f.cell_id
            WHERE c.client_id=? AND f.state='active' ORDER BY c.subsection_id, f.id""",
        (client_id,)).fetchall()
    return [dict(r) for r in rows]


def find_duplicate_groups(conn, client_id: str, *, model: Optional[str] = None) -> Dict[str, Any]:
    """LLM-cluster same-meaning active facts for merge proposals. Runs PER SUBSECTION
    (dupes can only live within one) — many small prompts instead of one huge one, so
    it scales to clients with hundreds of facts (a single all-facts call truncated /
    failed to parse → looked like "verifier unavailable").

    Returns {available, groups:[{subsection_id, keep, ids:[...], reason, merged_text,
    facts:[{id,text}]}]}. available=False only if there were subsections to check and
    EVERY LLM call failed. Stub-safe."""
    from collections import defaultdict
    facts = _active_facts(conn, client_id)
    by_id = {f["id"]: f for f in facts}
    bysub: Dict[str, list] = defaultdict(list)
    for f in facts:
        bysub[f["sid"]].append(f)

    groups: List[dict] = []
    calls = 0
    ok = 0
    mdl = model or _audit_model()
    for sid, sfacts in bysub.items():
        if len(sfacts) < 2:
            continue   # no possible dupes in a 0/1-fact subsection
        # Guard against a fat subsection (hundreds of facts) blowing the prompt /
        # truncating the response: chunk into bounded batches. Trade-off — a dup pair
        # split across batches is missed this run; a re-run after merges catches it.
        # TODO(scale): replace blind chunking with cheap pre-clustering (Jaccard/embeddings)
        # so likely-similar facts land in the same batch. See NEXT.md.
        for batch in _chunked(sfacts, _DEDUP_BATCH):
            if len(batch) < 2:
                continue
            calls += 1
            lines = [f"[{f['id']}] {(f['text'] or '')[:200]}" for f in batch]
            data = _generate_json(_DEDUP_SUB_SYSTEM, f"Подсекция {sid}. Факты:\n" + "\n".join(lines),
                                  max_tokens=2000, model=mdl)
            if data is None:
                continue
            ok += 1
            for g in data.get("groups", []) or []:
                ids = [int(i) for i in (g.get("ids") or []) if str(i).isdigit() and int(i) in by_id]
                ids = [i for i in ids if by_id[i]["sid"] == sid]
                if len(ids) < 2:
                    continue
                keep = g.get("keep")
                keep = int(keep) if str(keep).isdigit() and int(keep) in ids else ids[0]
                merged = (g.get("merged_text") or "").strip()[:400] or (by_id[keep]["text"] or "")
                groups.append({
                    "subsection_id": sid,
                    "keep": keep,
                    "ids": ids,
                    "reason": (g.get("reason") or "").strip()[:300],
                    "merged_text": merged,
                    "facts": [c for i in ids if (c := _fact_card_fields(conn, i))],
                })
    # available unless we tried subsections and every call failed (LLM down)
    return {"available": calls == 0 or ok > 0, "groups": groups}


_ATTRIB_SYSTEM = """Ты — редактор IR-матрицы. Дан список фактов `[id|подсекция|текст]`. Найди факты, где субъект высказывания/действия назван ОБЕЗЛИЧЕННО: «фаундер», «основатель», «сооснователь», «founder», «co-founder», «он/она» в роли говорящего — вместо конкретного имени. Это плохо: в матрице и материалах должно быть конкретное лицо.

Для КАЖДОГО такого факта верни перепись, где обезличенный субъект заменён плейсхолдером `[ИМЯ]` (именно так, в квадратных скобках), а остальной текст сохранён дословно. Падеж/грамматику подгони под подстановку имени в именительном падеже («[ИМЯ] считает…», «[ИМЯ] предложил…»).

Верни СТРОГО валидный JSON (без markdown):
{"items": [{"id": <id>, "generic": "<обезличенная фраза как в тексте>", "rewrite": "<текст с [ИМЯ]>"}]}

Факты с уже конкретным именем НЕ трогай. Нет таких фактов → "items": []."""


# Generic speaker words for the offline fallback (LLM gives a smarter scan).
_GENERIC_SPEAKER_RE = re.compile(
    r"\b(со-?основател\w+|сооснователь\w*|основател\w+|фаундер\w*|co-?founders?|founders?)\b",
    re.IGNORECASE)


_TITLE_SYSTEM = """Ты — редактор IR-карточек. Для каждого факта придумай ЗАГОЛОВОК из 2–3 слов на русском — короткую суть факта (как заголовок карточки). Без точки в конце, с заглавной буквы.

Верни СТРОГО валидный JSON (без markdown): {"titles": [{"id": <id>, "title": "<2-3 слова>"}]}"""


def generate_fact_titles(conn, client_id: str, *, model: Optional[str] = None,
                         overwrite: bool = False) -> Dict[str, Any]:
    """LLM-generate a short 2-3 word title for each active fact (analyst-editable
    afterwards). By default only fills empty titles (manual edits are preserved).
    Batched like dedup so it scales. Stub-safe. Returns {available, titled}."""
    where = "" if overwrite else " AND (f.title IS NULL OR f.title='')"
    rows = conn.execute(
        f"""SELECT f.id AS id, f.text AS text FROM facts f
             JOIN cells c ON c.id = f.cell_id
             WHERE c.client_id=? AND f.state='active'{where}
             ORDER BY f.id""", (client_id,)).fetchall()
    facts = [dict(r) for r in rows]
    if not facts:
        return {"available": True, "titled": 0}
    by_id = {f["id"] for f in facts}
    mdl = model or _audit_model()
    titled = 0
    ok = 0
    calls = 0
    for batch in _chunked(facts, _DEDUP_BATCH):
        calls += 1
        lines = [f"[{f['id']}] {(f['text'] or '')[:160]}" for f in batch]
        data = _generate_json(_TITLE_SYSTEM, "Факты:\n" + "\n".join(lines),
                              max_tokens=2000, model=mdl)
        if data is None:
            continue
        ok += 1
        from . import matrix
        for it in data.get("titles", []) or []:
            try:
                fid = int(it.get("id"))
            except (TypeError, ValueError):
                continue
            t = (it.get("title") or "").strip()
            if fid in by_id and t:
                matrix.set_fact_title(conn, fid, t)
                titled += 1
    return {"available": calls == 0 or ok > 0, "titled": titled}


def _founder_candidates(conn, client_id: str) -> List[dict]:
    """Founder names for attribution, from BOTH dedicated kind='founder' entities AND
    the company card's "founder" profile fact (e.g. 'Dave Waiser (ex-Gett CEO)').
    Entity-backed names carry their id; profile-derived names have id=None (selecting
    one creates the founder card on apply). Deduped, order-preserving."""
    from . import matrix
    out: List[dict] = []
    seen = set()

    def _add(name: str, eid):
        nm = (name or "").split("(")[0].strip().strip(",.;—-").strip()
        if nm and nm.lower() not in seen:
            seen.add(nm.lower())
            out.append({"id": eid, "name": nm})

    for e in matrix.entities_for_client(conn, client_id):
        if e["kind"] == "founder":
            _add(e["name"], e["id"])
    for e in matrix.entities_for_client(conn, client_id):
        if e["kind"] == "company":
            for ef in e.get("facts", []):
                if "founder" in (ef.get("key", "") or "").lower():
                    _add(ef.get("value", ""), None)
    return out


def find_unattributed_facts(conn, client_id: str, *, model: Optional[str] = None) -> Dict[str, Any]:
    """Scan active facts for generic speaker references ("фаундер считает …") and
    propose a rewrite that names a concrete founder. Mirrors find_duplicate_groups.

    - 1 founder on the company card → proposed_text auto-fills that name.
    - >1 founder → needs_choice; analyst picks who, then the name fills [ИМЯ].
    - L1–L2 facts must name a concrete person → flagged must_be_concrete=True.
    Returns {available, founders:[{id,name}], items:[...]}. Stub-safe."""
    from . import matrix
    founders = _founder_candidates(conn, client_id)
    facts = _active_facts(conn, client_id)
    by_id = {f["id"]: f for f in facts}
    if not facts:
        return {"available": True, "founders": founders, "items": []}
    lines = [f"[{f['id']}|{f['sid']}] {(f['text'] or '')[:200]}" for f in facts]
    fn = "Фаундеры на карточке: " + (", ".join(x["name"] for x in founders) or "нет") + "\n\n"
    data = _generate_json(_ATTRIB_SYSTEM, fn + "Факты:\n" + "\n".join(lines),
                          max_tokens=6000, model=model or _audit_model())

    single = founders[0]["name"] if len(founders) == 1 else None

    # LLM unavailable (no key / no balance) → deterministic keyword fallback so the
    # tool still works offline: flag facts naming a generic speaker, swap the word
    # for [ИМЯ]. Grammar is rough but the analyst edits the text before applying.
    if data is None:
        raw_items = []
        for f in facts:
            m = _GENERIC_SPEAKER_RE.search(f["text"] or "")
            if not m:
                continue
            rewrite = (f["text"][:m.start()] + "[ИМЯ]" + f["text"][m.end():]).strip()[:400]
            raw_items.append({"id": f["id"], "generic": m.group(0), "rewrite": rewrite})
    else:
        raw_items = data.get("items", []) or []

    items: List[dict] = []
    for it in raw_items:
        try:
            fid = int(it.get("id"))
        except (TypeError, ValueError):
            continue
        if fid not in by_id:
            continue
        rewrite = (it.get("rewrite") or "").strip()[:400]
        if not rewrite or "[ИМЯ]" not in rewrite:
            continue
        sid = by_id[fid]["sid"]
        layer_id = int(sid.split(".")[0])
        items.append({
            "id": fid,
            "subsection_id": sid,
            "layer_id": layer_id,
            "text": by_id[fid]["text"],
            "generic": (it.get("generic") or "").strip()[:120],
            "rewrite_template": rewrite,
            "proposed_text": rewrite.replace("[ИМЯ]", single) if single else rewrite,
            "needs_choice": single is None,
            "must_be_concrete": layer_id in (1, 2),
        })
    return {"available": True, "founders": founders, "items": items}


def _generate_json(system: str, user: str, *, max_tokens: int,
                   model: Optional[str], attempts: int = 2) -> Optional[dict]:
    """Thin object-only wrapper over the universal llm.generate_json primitive
    (generate + tolerant parse + retry). Kept as a local name so the existing
    callers and tests import it from here."""
    data = llm.generate_json(system, user, max_tokens=max_tokens, model=model, attempts=attempts)
    return data if isinstance(data, dict) else None


def _parse_json(raw: str) -> Optional[dict]:
    """Object-only wrapper over llm.extract_json (tolerant of chatty models)."""
    data = llm.extract_json(raw)
    return data if isinstance(data, dict) else None
