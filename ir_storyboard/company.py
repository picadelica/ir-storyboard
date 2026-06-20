"""Auto-fill the company "About" card — a structured business profile.

Two evidence sources, fused into one LLM pass:
  1. what's already collected — the client's verified matrix facts + their source URLs
  2. web search — Tavily hits for the company name (funding / founding / site …)

Discipline ("голые факты, 100% уверенность"): the model may only emit facts whose
source_url appears VERBATIM in the supplied evidence — enforced mechanically, not
just by prompt, by dropping any proposal whose URL isn't in the allowed set. The
result is a list of PROPOSALS; nothing is written until the analyst commits.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import llm
from . import matrix

SECTIONS = ("profile", "sites", "funding", "history", "product", "metrics")

_MAX_FACTS = 120
_MAX_HITS = 24


def _norm_url(u: str) -> str:
    u = (u or "").strip().lower().rstrip("/")
    for p in ("https://", "http://", "www."):
        if u.startswith(p):
            u = u[len(p):]
    return u


def _norm_val(v: str) -> str:
    return " ".join((v or "").lower().split())


def _client_name(conn, client_id: str) -> str:
    row = conn.execute("SELECT name FROM clients WHERE id=?", (client_id,)).fetchone()
    return (row["name"] if row else "") or client_id


def _matrix_evidence(conn, client_id: str) -> List[dict]:
    """Active facts that carry a source URL — what we already know, with provenance."""
    rows = conn.execute(
        """
        SELECT f.text AS text,
               COALESCE(NULLIF(f.source_url, ''), s.url, '') AS url,
               COALESCE(s.title, '') AS title
        FROM facts f
        JOIN cells c ON c.id = f.cell_id
        LEFT JOIN sources s ON s.id = f.source_id
        WHERE c.client_id = ?
          AND f.state = 'active'
          AND f.flag != 'grey'
          AND COALESCE(NULLIF(f.source_url, ''), s.url, '') LIKE 'http%'
        ORDER BY f.id
        """,
        (client_id,),
    ).fetchall()
    return [dict(r) for r in rows][:_MAX_FACTS]


def _web_evidence(name: str) -> List[dict]:
    if not name:
        return []
    queries = [name, f"{name} funding round investors", f"{name} founded headquarters website",
               f"{name} product customers"]
    hits: List[dict] = []
    seen = set()
    for q in queries:
        for h in (llm.web_search(q, 6) or []):
            k = _norm_url(h.url)
            if not k or k in seen:
                continue
            seen.add(k)
            hits.append({"title": h.title, "url": h.url, "snippet": h.snippet})
            if len(hits) >= _MAX_HITS:
                return hits
    return hits


_SYSTEM = """Ты строишь СТРУКТУРНЫЙ БИЗНЕС-ПРОФИЛЬ компании — голые факты, без психологии, нарратива и оценок. Даны два набора данных с источниками: (A) уже собранные факты про компанию и (B) результаты веб-поиска. Извлеки бизнес-факты и разложи по секциям:
- profile — юр. название, основана (дата/место), стадия, размер команды, чем занимается одной строкой
- sites — сайт, домены, соцсети (X/LinkedIn/GitHub)
- funding — раунды: стадия, сумма, дата, лид/инвесторы, оценка
- history — датированные бизнес-события: запуски, релизы, ключевые сделки/наймы
- product — продукт, категория/рынок, конкуренты
- metrics — ключевые числа: ARR, пользователи, рост (с датой)

ЖЁСТКИЕ ПРАВИЛА (бизнес требует 100% достоверности):
- Каждый факт ОБЯЗАН иметь source_url, который ДОСЛОВНО присутствует в предоставленных данных. НЕ придумывай ни факты, ни ссылки. Нет источника в данных — не включай факт.
- Только бизнес. Никакой психологии, мотивации, нарратива.
- as_of — дата факта, если известна (иначе пусто).
- Не дублируй факты, уже перечисленные как «УЖЕ В КАРТОЧКЕ».

Верни СТРОГО валидный JSON, без преамбулы:
{"proposals": [{"section": "<одна из секций>", "key": "<короткий ярлык>", "value": "<факт>", "source_url": "<URL из данных>", "source_title": "<название источника>", "as_of": "<дата или пусто>"}]}"""


def build_about_proposals(conn, client_id: str, *, model: Optional[str] = None,
                          pasted: str = "", pasted_url: str = "", pasted_title: str = "",
                          use_web: bool = True) -> Dict[str, Any]:
    """Propose source-grounded business facts for the company About card.

    Evidence: (A) the client's collected facts, (B) web search (if use_web), and
    optionally (C) a pasted document/URL the analyst supplies. A fact survives only
    if its source_url is in the supplied evidence. Returns {available, proposals,
    stats}; writes nothing."""
    name = _client_name(conn, client_id)
    ents = matrix.entities_for_client(conn, client_id)
    company = next((e for e in ents if e["kind"] == "company"), None)
    existing = {_norm_val(f["value"]) for f in (company["facts"] if company else [])}

    facts = _matrix_evidence(conn, client_id)
    hits = _web_evidence(name) if use_web else []
    pasted = (pasted or "").strip()[:12000]
    stats = {"from_matrix": len(facts), "from_web": len(hits),
             "dropped_ungrounded": 0, "duplicates": 0}
    if not facts and not hits and not pasted:
        return {"available": True, "proposals": [], "stats": stats}

    # allowed URLs (normalized) + origin lookup — the grounding whitelist
    allowed: Dict[str, str] = {}
    for f in facts:
        allowed.setdefault(_norm_url(f["url"]), "matrix")
    for h in hits:
        allowed.setdefault(_norm_url(h["url"]), "web")
    if pasted and pasted_url.strip():
        allowed.setdefault(_norm_url(pasted_url), "doc")

    card_block = ""
    if existing:
        card_block = "УЖЕ В КАРТОЧКЕ (не повторять):\n" + "\n".join(f"- {f['value']}" for f in company["facts"]) + "\n\n"
    a_block = "\n".join(f"- {f['text']}  [src: {f['url']}]" for f in facts) or "(нет)"
    b_block = "\n".join(f"- {h['title']}: {h['snippet'][:200]}  [src: {h['url']}]" for h in hits) or "(нет)"
    user = (f"Компания: {name}\n\n{card_block}"
            f"(A) УЖЕ СОБРАННЫЕ ФАКТЫ:\n{a_block}\n\n"
            f"(B) ВЕБ-ПОИСК:\n{b_block}")
    if pasted:
        doc_src = pasted_url.strip() or "(без URL)"
        user += (f"\n\n(C) ВСТАВЛЕННЫЙ ДОКУМЕНТ [src: {doc_src}] "
                 f"{('«'+pasted_title.strip()+'»') if pasted_title.strip() else ''}:\n{pasted}")

    data = llm.generate_json(_SYSTEM, user, max_tokens=6000, model=model)
    if data is None:
        return {"available": False, "proposals": [], "stats": stats}

    proposals: List[dict] = []
    dropped = dups = 0
    seen_vals = set(existing)
    for it in (data.get("proposals") or []):
        if not isinstance(it, dict):
            continue
        value = (it.get("value") or "").strip()
        section = it.get("section") if it.get("section") in SECTIONS else ""
        url = (it.get("source_url") or "").strip()
        origin = allowed.get(_norm_url(url))
        if not value or not section:
            continue
        if origin is None:          # URL not in supplied evidence → ungrounded → drop
            dropped += 1
            continue
        nv = _norm_val(value)
        if nv in seen_vals:         # duplicate of existing or another proposal
            dups += 1
            continue
        seen_vals.add(nv)
        proposals.append({
            "section": section,
            "key": (it.get("key") or "").strip()[:80],
            "value": value[:400],
            "source_url": url,
            "source_title": (it.get("source_title") or "").strip()[:160],
            "as_of": (it.get("as_of") or "").strip()[:40] or None,
            "origin": origin,        # matrix | web
        })

    stats["dropped_ungrounded"] = dropped
    stats["duplicates"] = dups
    return {"available": True, "proposals": proposals, "stats": stats}
