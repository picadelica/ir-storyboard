"""LLM / search abstraction.

Stubs work without API keys (prototype mode).
Set ANTHROPIC_API_KEY and TAVILY_API_KEY to activate real providers.

Key public API:
    classify_fact(text)            -> FactCandidate   (single, for ad-hoc use)
    classify_facts_batch(texts)    -> List[FactCandidate]  (batch, 10-20x cheaper)
    web_search(query, max_hits)    -> List[SearchHit]
    summarize(text, max_chars)     -> str
    generate(system, user, max_tokens) -> str  (cycle content generation)
    extract_facts_from_llm_report(...)  -> List[ExtractedFact]  (LLM Report Ingest)
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, List, Optional

from .models import LAYERS, SubsectionSpec

if TYPE_CHECKING:
    from .channels.llm_report.citations import ResolvedCitation


# ─────────────────────────── data types ────────────────────────────────────

@dataclass
class FactCandidate:
    text: str
    suggested_subsection_id: Optional[str]   # "1.1" … "8.3", or None
    suggested_flag: str                       # green / red / grey
    confidence: float = 0.5


@dataclass
class ExtractedFact:
    """Fact produced by extract_facts_from_llm_report."""
    text: str                          # one-sentence atomic fact, ≤240 chars
    subsection_id: str                 # proposed subsection, e.g. "6.1"
    flag: str                          # green / red / grey
    cite_ids: List[int] = field(default_factory=list)   # references to ResolvedCitation
    confidence: float = 0.5
    raw_paraphrase: str = ""           # source sentence from the LLM report (for audit + snippet MVP)
    rationale: str = ""


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


# ─────────────────────────── keyword stub ──────────────────────────────────

KEYWORDS_BY_SUBSECTION = {
    "1.1": ["родил", "детств", "школ", "семья", "отец", "мать", "born", "childhood"],
    "1.2": ["верит", "ценност", "убежд", "believe", "values"],
    "1.3": ["страх", "потер", "уязвим", "мечт", "идентичн", "fear", "loss", "vulnerab", "dream", "identity"],
    "2.1": ["опыт", "построил", "запустил", "founded", "built", "experience", "expertise"],
    "2.2": ["роль", "мотив", "role", "motivation", "ceo", "founder"],
    "2.3": ["сооснователь", "партнёр", "co-founder", "cofounder", "partner"],
    "3.1": ["отбор", "приглаш", "invite", "selection", "exclusive"],
    "3.2": ["сообществ", "событ", "встреч", "community", "event", "forum"],
    "3.3": ["инвестор", "партнёр", "investor", "partner"],
    "4.1": ["экспертиз", "разнообраз", "diversity", "expertise"],
    "4.2": ["рост", "масштаб", "growth", "scale", "transformation"],
    "4.3": ["провал", "ошибк", "потер", "failure", "lost", "mistake"],
    "5.1": ["клиент", "проблема", "контекст", "challenge", "customer", "pain"],
    "5.2": ["выбор", "довер", "choice", "trust", "decision"],
    "5.3": ["конфликт", "честн", "признан", "conflict", "honest"],
    "6.1": ["архитектур", "продукт", "решение", "architecture", "product", "solution"],
    "6.2": ["философ", "принцип", "philosophy", "principle"],
    "6.3": ["эволюц", "развит", "evolution", "iteration"],
    "7.1": ["изменен", "трансформ", "change", "vision"],
    "7.2": ["противоречи", "цена", "contradiction", "cost", "trade-off"],
    "7.3": ["наследи", "будущ", "legacy", "future"],
    "8.1": ["исторический", "момент", "historical", "moment"],
    "8.2": ["рынок", "технолог", "market", "technology"],
    "8.3": ["регулир", "политик", "регуляц", "regulation", "policy", "law"],
}

POSITIVE_HINTS = ["зелёный", "green", "сильн", "strong", "уже", "достиг", "успех"]
NEGATIVE_HINTS = ["красный", "red", "риск", "risk", "проблем", "concern", "weakness"]
GREY_HINTS = ["неизвестн", "нет данных", "не упомин", "unknown", "no info", "missing", "серый"]


def stub_classify(text: str) -> FactCandidate:
    """Deterministic keyword classifier. Decent baseline; replaced by LLM when key is set."""
    norm = text.lower()
    best_sid, best_score = None, 0
    for sid, kws in KEYWORDS_BY_SUBSECTION.items():
        score = sum(1 for kw in kws if kw in norm)
        if score > best_score:
            best_sid, best_score = sid, score

    if any(h in norm for h in GREY_HINTS):
        flag = "grey"
    elif any(h in norm for h in NEGATIVE_HINTS):
        flag = "red"
    elif any(h in norm for h in POSITIVE_HINTS):
        flag = "green"
    else:
        flag = "green"

    return FactCandidate(
        text=text,
        suggested_subsection_id=best_sid,
        suggested_flag=flag,
        confidence=min(1.0, 0.3 + 0.15 * best_score),
        rationale=f"matched {best_score} keyword(s) for subsection {best_sid}",
    )


def stub_web_search(query: str, max_hits: int = 5) -> List[SearchHit]:
    return []


def stub_summarize(text: str, max_chars: int = 280) -> str:
    s = text.strip().replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    m = re.search(r"^(.{40,}?[\.!?])\s", s)
    if m:
        s = m.group(1)
    if len(s) > max_chars:
        s = s[:max_chars - 1] + "…"
    return s


def stub_generate(system: str, user: str, max_tokens: int = 1024) -> str:
    """Stub — returns empty string; callers fall back to template rendering."""
    return ""


# ─────────────────── public callables (start as stubs) ─────────────────────

classify_fact: Callable[[str], FactCandidate] = stub_classify
web_search: Callable[[str, int], List[SearchHit]] = stub_web_search
summarize: Callable[[str, int], str] = stub_summarize
generate: Callable[[str, str, int], str] = stub_generate


def classify_facts_batch(texts: List[str]) -> List[FactCandidate]:
    """Classify a list of facts. Falls back to per-fact stub if no LLM configured."""
    if not texts:
        return []
    return [classify_fact(t) for t in texts]


# ─────────────────── Claude prompt (built once at import) ──────────────────

_MATRIX_LINES = "\n".join(
    f"{sub.id}  {sub.name}  ({layer.name})"
    for layer in LAYERS
    for sub in layer.subsections
)

_CLASSIFY_SYSTEM = f"""\
You are an IR narrative analyst. Classify each fact into the IR Storyboard matrix.

Subsections (id — name — parent layer):
{_MATRIX_LINES}

Flag rules:
- green  confirmed positive signal, strength, achievement
- red    risk, controversy, concern, weakness, regulatory issue
- grey   unverified, ambiguous, information gap, unknown

Return ONLY valid JSON — no markdown fences, no explanation:
{{"results":[{{"sid":"X.Y","flag":"green|red|grey","conf":0.0,"rationale":"one short phrase"}}]}}

One object per input fact, same order. Set sid to null if no subsection fits.\
"""


# ─────────────────── real Claude implementation ─────────────────────────────

def _try_init_anthropic() -> None:
    global classify_fact, summarize, classify_facts_batch, generate

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return

    try:
        import anthropic
        from pydantic import BaseModel
    except ImportError:
        return

    _client = anthropic.Anthropic(api_key=api_key)
    # Haiku is the right choice here: high-volume classification, cost matters
    _MODEL = os.environ.get("LLM_CLASSIFY_MODEL", "claude-haiku-4-5")
    _SUMMARIZE_MODEL = os.environ.get("LLM_SUMMARIZE_MODEL", "claude-haiku-4-5")

    class _Item(BaseModel):
        sid: Optional[str] = None
        flag: str = "grey"
        conf: float = 0.5
        rationale: str = ""

    class _Batch(BaseModel):
        results: List[_Item]

    def _classify_batch_real(texts: List[str]) -> List[FactCandidate]:
        if not texts:
            return []
        numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
        try:
            resp = _client.messages.parse(
                model=_MODEL,
                max_tokens=min(4096, 80 * len(texts) + 256),
                system=[{
                    "type": "text",
                    "text": _CLASSIFY_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": numbered}],
                output_format=_Batch,
            )
            items = resp.parsed_output.results
        except Exception:
            return [stub_classify(t) for t in texts]

        out: List[FactCandidate] = []
        for i, item in enumerate(items):
            # LLM may return more items than input texts (multiple facts per paragraph)
            text = texts[i] if i < len(texts) else texts[-1] if texts else ""
            flag = item.flag if item.flag in ("green", "red", "grey") else "grey"
            out.append(FactCandidate(
                text=text,
                suggested_subsection_id=item.sid,
                suggested_flag=flag,
                confidence=max(0.0, min(1.0, item.conf)),
                rationale=item.rationale,
            ))
        # pad if model returned fewer items than expected
        for i in range(len(out), len(texts)):
            out.append(stub_classify(texts[i]))
        return out

    def _classify_single_real(text: str) -> FactCandidate:
        return _classify_batch_real([text])[0]

    def _summarize_real(text: str, max_chars: int = 280) -> str:
        try:
            resp = _client.messages.create(
                model=_SUMMARIZE_MODEL,
                max_tokens=128,
                system="Summarize in one concise sentence. Return only the sentence, no preamble.",
                messages=[{"role": "user", "content": text[:3000]}],
            )
            s = next((b.text for b in resp.content if b.type == "text"), "").strip()
            if len(s) > max_chars:
                s = s[:max_chars - 1] + "…"
            return s or stub_summarize(text, max_chars)
        except Exception:
            return stub_summarize(text, max_chars)

    _GENERATE_MODEL = os.environ.get("LLM_GENERATE_MODEL", "claude-haiku-4-5")

    def _generate_real(system: str, user: str, max_tokens: int = 1024) -> str:
        try:
            resp = _client.messages.create(
                model=_GENERATE_MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return next((b.text for b in resp.content if b.type == "text"), "").strip()
        except Exception:
            return ""

    classify_fact = _classify_single_real
    summarize = _summarize_real
    classify_facts_batch = _classify_batch_real
    generate = _generate_real


# ─────────────────── real Tavily implementation ─────────────────────────────

def _try_init_tavily() -> None:
    global web_search

    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return

    try:
        from tavily import TavilyClient
    except ImportError:
        return

    _tavily = TavilyClient(api_key=api_key)

    def _search_real(query: str, max_hits: int = 5) -> List[SearchHit]:
        try:
            result = _tavily.search(query=query, max_results=max_hits, search_depth="basic")
            return [
                SearchHit(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=(item.get("content") or "")[:400],
                )
                for item in result.get("results", [])
            ]
        except Exception:
            return []

    web_search = _search_real


# ─────────────────── auto-init on import ────────────────────────────────────

_try_init_anthropic()
_try_init_tavily()


# ─────────────────── LLM Report Ingest: fact extractor ──────────────────────

_EXTRACT_SYSTEM_TMPL = """\
You are a fact extractor for a narrative IR matrix (ir-storyboard).

Matrix subsections available (id — name):
SUBSECTION_LIST_PLACEHOLDER

Your task: given one section of a deep-research LLM report, extract ATOMIC facts.

Rules:
- One fact = one sentence, <=240 characters.
- Do NOT invent facts not present in the text.
- Do NOT merge multiple claims into one fact.
- Assign one subsection_id from the provided list. Choose the best fit.
- Assign flag: green (positive/neutral confirmed claim), red (risk/concern/controversy), grey (gap / unknown / not covered).
- Assign cite_ids: list of integer citation numbers referenced in the sentence (from [N] markers).
- Assign confidence 0.0-1.0.
- raw_paraphrase: copy the original sentence from the report that supports this fact (verbatim or near-verbatim, <=400 chars).

Return ONLY valid JSON, no markdown fences:
{"facts": [{"text": "...", "subsection_id": "X.Y", "flag": "green|red|grey", "cite_ids": [1,2], "confidence": 0.8, "raw_paraphrase": "..."}]}

If no usable facts in the section, return: {"facts": []}
"""


def extract_facts_from_llm_report(
    section_heading: str,
    section_paragraphs: List[str],
    available_subsections: List[str],
    citation_index: "dict[int, ResolvedCitation]",
) -> List["ExtractedFact"]:
    """Extract atomic facts from one report section using LLM.

    Falls back to empty list if no API key configured (prototype mode).
    """
    from .channels.llm_report.classifiers.flag_heuristics import apply_heuristics

    if not section_paragraphs:
        return []

    subsection_list = "\n".join(
        f"{sub.id} — {sub.name} ({layer.name})"
        for layer in LAYERS
        for sub in layer.subsections
        if sub.id in available_subsections
    )

    cite_ref = "\n".join(
        f"[{cid}] {c.title or c.canonical_url}"
        for cid, c in sorted(citation_index.items())
    ) or "(no citations)"

    user_content = (
        f"Section: {section_heading}\n\n"
        + "\n".join(section_paragraphs)
        + f"\n\nAvailable citations:\n{cite_ref}"
    )

    system_prompt = _EXTRACT_SYSTEM_TMPL.replace("SUBSECTION_LIST_PLACEHOLDER", subsection_list)

    raw = generate(system_prompt, user_content, max_tokens=2048)

    if not raw:
        return _stub_extract(section_heading, section_paragraphs, available_subsections)

    try:
        data = json.loads(raw)
        facts_data = data.get("facts", [])
    except (json.JSONDecodeError, AttributeError):
        return _stub_extract(section_heading, section_paragraphs, available_subsections)

    results: List[ExtractedFact] = []
    for item in facts_data:
        text = (item.get("text") or "").strip()
        sid = item.get("subsection_id") or ""
        if not text or sid not in available_subsections:
            continue
        llm_flag = item.get("flag", "green")
        if llm_flag not in ("green", "red", "grey"):
            llm_flag = "green"
        # Apply safety-net heuristics (grey/red override)
        final_flag = apply_heuristics(text, llm_flag)
        results.append(ExtractedFact(
            text=text[:240],
            subsection_id=sid,
            flag=final_flag,
            cite_ids=[int(c) for c in (item.get("cite_ids") or []) if str(c).isdigit()],
            confidence=max(0.0, min(1.0, float(item.get("confidence", 0.5)))),
            raw_paraphrase=(item.get("raw_paraphrase") or text)[:400],
        ))

    return results


def _stub_extract(
    heading: str,
    paragraphs: List[str],
    available_subsections: List[str],
) -> List["ExtractedFact"]:
    """Deterministic stub when no LLM key is configured."""
    from .channels.llm_report.classifiers.section_to_layer import suggest_subsection
    from .channels.llm_report.classifiers.flag_heuristics import apply_heuristics

    sid = suggest_subsection(heading)
    if sid is None or sid not in available_subsections:
        return []

    results = []
    for para in paragraphs[:5]:  # limit stub output
        text = para.strip()
        if len(text) < 20:
            continue
        flag = apply_heuristics(text, "green")
        results.append(ExtractedFact(
            text=text[:240],
            subsection_id=sid,
            flag=flag,
            cite_ids=[],
            confidence=0.3,
            raw_paraphrase=text[:400],
        ))
    return results
