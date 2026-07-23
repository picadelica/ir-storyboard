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
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Inline [N] citation marker (used by the keyword stub to attribute provenance).
_RE_CITE_MARKER = re.compile(r"\[(\d+)\]")

from .models import LAYERS, SubsectionSpec

if TYPE_CHECKING:
    from .ingest.citations import ResolvedCitation


# ─────────────────────────── data types ────────────────────────────────────

@dataclass
class FactCandidate:
    text: str
    suggested_subsection_id: Optional[str]   # "1.1" … "8.3", or None
    suggested_flag: str                       # green / red / grey
    confidence: float = 0.5
    rationale: str = ""                       # short LLM-supplied reason for the classification


class PdfRejectedError(Exception):
    """The vision API rejected the uploaded PDF itself (corrupt / encrypted / not a
    real PDF). Surfaced to the analyst as a clear error rather than silent 0 facts."""


@dataclass
class ExtractedFact:
    """Fact produced by extract_facts_from_llm_report."""
    text: str                          # one-sentence atomic fact, ≤400 chars (primary storage)
    subsection_id: str                 # proposed subsection, e.g. "6.1"
    flag: str                          # green / red / grey
    cite_ids: List[int] = field(default_factory=list)   # references to ResolvedCitation
    confidence: float = 0.5
    raw_paraphrase: str = ""           # source sentence from the LLM report (for audit + snippet MVP)
    rationale: str = ""
    # Transcript-mode fields (populated only for YouTube ingest)
    segment_idx_start: Optional[int] = None   # index into transcript.segments
    segment_idx_end: Optional[int] = None
    layer_warning: bool = False               # True if LLM flagged this as a restricted layer
    # Bilingual fields (YouTube transcript mode only)
    text_ru: str = ""                  # Russian brief
    text_en: str = ""                  # English brief
    quote: str = ""                    # literal transcript quote


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

    # авто-красный флаг убран как слишком грубый: риск/проблема/пробел → grey,
    # иначе green. Красный остаётся как РУЧНОЙ флаг (выставляется аналитиком).
    if any(h in norm for h in GREY_HINTS) or any(h in norm for h in NEGATIVE_HINTS):
        flag = "grey"
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


def stub_generate(system: str, user: str, max_tokens: int = 1024,
                  model: Optional[str] = None) -> str:
    """Stub — returns empty string; callers fall back to template rendering."""
    return ""


def get_fallback_model() -> Optional[str]:
    """Return the configured fallback model name, or None if same as primary."""
    primary = os.environ.get("LLM_GENERATE_MODEL", "claude-haiku-4-5")
    fallback = os.environ.get("LLM_GENERATE_MODEL_FALLBACK", "claude-sonnet-4-6")
    return fallback if fallback and fallback != primary else None


# ─────────────────── public callables (start as stubs) ─────────────────────

classify_fact: Callable[[str], FactCandidate] = stub_classify
web_search: Callable[[str, int], List[SearchHit]] = stub_web_search
summarize: Callable[[str, int], str] = stub_summarize
generate: Callable[..., str] = stub_generate
_client = None  # real anthropic.Anthropic set by _try_init_anthropic; read by PDF vision


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

Flag rules (only two — do NOT use red, it is a manual analyst flag):
- green  a substantive signal we have on file (strength, achievement, fact, even a risk we know about)
- grey   unverified, ambiguous, information gap, unknown, or an explicit "we don't know yet"

Return ONLY valid JSON — no markdown fences, no explanation:
{{"results":[{{"sid":"X.Y","flag":"green|grey","conf":0.0,"rationale":"one short phrase"}}]}}

One object per input fact, same order. Set sid to null if no subsection fits.\
"""


# ─────────────────── real Claude implementation ─────────────────────────────

def _try_init_anthropic() -> None:
    # _client must be a MODULE global, not a closure local: module-level extractors
    # (extract_facts_from_pdf) read it via globals().get("_client"). Without this it
    # stays None there → PDF vision silently returns [] even with a valid API key.
    global classify_fact, summarize, classify_facts_batch, generate, _client

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
            # авто-красный убран: модель не должна выдавать red; любой не-green → grey
            flag = "green" if item.flag == "green" else "grey"
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

    def _generate_real(system: str, user: str, max_tokens: int = 1024,
                       model: Optional[str] = None) -> str:
        use_model = model or _GENERATE_MODEL
        backoffs = [2.0, 5.0, 10.0]
        last_exc: Optional[BaseException] = None
        for attempt, delay in enumerate(backoffs, start=1):
            try:
                resp = _client.messages.create(
                    model=use_model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return next((b.text for b in resp.content if b.type == "text"), "").strip()
            except anthropic.APIError as e:
                last_exc = e
                logger.warning(
                    "generate(model=%s): Anthropic APIError on attempt %d/%d (%s): %s — retrying in %.1fs",
                    use_model, attempt, len(backoffs), type(e).__name__, e, delay,
                )
                if attempt < len(backoffs):
                    time.sleep(delay)
            except Exception as e:
                logger.error(
                    "generate(model=%s): non-retryable error (%s): %s",
                    use_model, type(e).__name__, e,
                )
                return ""
        logger.error(
            "generate(model=%s): exhausted %d retries, giving up. Last error: %s",
            use_model, len(backoffs), last_exc,
        )
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


# ─────────────────── RATIONALE prompt fragment (shared by all extractors) ────

_RATIONALE_RULES = """\
RATIONALE field rules:
- If flag is "red": you MUST provide a `rationale` (1-2 sentences) explaining
  what specifically is the concern. Be concrete, not generic.
  GOOD: "Founder has not disclosed Series B valuation while peers X and Y
        did. Raises transparency concern for institutional investors."
  BAD:  "This is bad." / "Risky." / "Concerning."
- If flag is "grey": `rationale` is RECOMMENDED (1-2 sentences explaining
  what specifically we don't know and why it matters). Optional but useful.
- If flag is "green": leave `rationale` empty (omit the field or use "").
"""


# ─────────────────── LLM Report Ingest: full-document batch extractor ────────

_BATCH_EXTRACT_SYSTEM_TMPL = """\
You are a fact extractor for a narrative IR matrix (ir-storyboard).

Matrix subsections (id — name — parent layer):
SUBSECTION_LIST_PLACEHOLDER

Extract ATOMIC facts from the ENTIRE document below. Rules:
- One fact = one sentence, <=400 characters.
- Do NOT invent facts not in the text.
- Do NOT merge multiple claims into one fact.
- Assign one subsection_id from the list above. Choose the best fit.
- flag: green=confirmed positive/neutral, red=risk/concern, grey=gap/unknown/not covered.
- cite_ids: list of [N] citation numbers from the sentence.
- confidence: 0.0-1.0.
- raw_paraphrase: the original sentence this fact is based on (<=400 chars).
- Skip L1 subsections (1.1, 1.2, 1.3) — those require live interviews only.
- Skip "Conclusions" / "Выводы" sections entirely.

If input is a TRANSCRIPT (single section with timestamped segments,
indicated by transcript_segments in metadata):
- For each fact, return segment_idx_start and segment_idx_end pointing
  to segment indices that contain the literal phrasing supporting the fact.
- Range should be tight: prefer 1-3 segments. Wider only if a single
  segment is shorter than 20 characters.
- Skip filler segments ("um, you know, like, basically...").
- DO NOT invent segments — if the transcript doesn't say it, don't emit the fact.
- L1 subsections (1.1, 1.2, 1.3) ARE allowed for transcripts when the founder
  directly speaks about personal history, values, or fears.
- LayerGuard will reject facts mapped to L5/L6/L8 (online_interview cannot feed
  those layers). If you must emit such a fact, set layer_warning=true.

__RATIONALE_RULES__

Return ONLY valid JSON, no markdown fences:
{"facts": [{"text": "...", "subsection_id": "X.Y", "flag": "green|red|grey", "cite_ids": [1], "confidence": 0.85, "raw_paraphrase": "...", "rationale": "", "segment_idx_start": 0, "segment_idx_end": 2, "layer_warning": false}]}

For non-transcript mode, omit segment_idx_* and layer_warning fields.
If no usable facts, return: {"facts": []}
"""


# ─────────────────── LLM Report Ingest: fact extractor ──────────────────────

_EXTRACT_SYSTEM_TMPL = """\
You are a fact extractor for a narrative IR matrix (ir-storyboard).

Matrix subsections available (id — name):
SUBSECTION_LIST_PLACEHOLDER

Your task: given one section of a deep-research LLM report, extract ATOMIC facts.

Rules:
- One fact = one sentence, <=400 characters.
- Do NOT invent facts not present in the text.
- Do NOT merge multiple claims into one fact.
- Assign one subsection_id from the provided list. Choose the best fit.
- Assign flag: green (positive/neutral confirmed claim), red (risk/concern/controversy), grey (gap / unknown / not covered).
- Assign cite_ids: list of integer citation numbers referenced in the sentence (from [N] markers).
- Assign confidence 0.0-1.0.
- raw_paraphrase: copy the original sentence from the report that supports this fact (verbatim or near-verbatim, <=400 chars).

__RATIONALE_RULES__

Return ONLY valid JSON, no markdown fences:
{"facts": [{"text": "...", "subsection_id": "X.Y", "flag": "green|red|grey", "cite_ids": [1,2], "confidence": 0.8, "raw_paraphrase": "...", "rationale": ""}]}

If no usable facts in the section, return: {"facts": []}
"""


def _build_subsection_list(available_subsections: List[str],
                            descriptions: Optional[dict] = None,
                            client_notes: Optional[dict] = None,
                            separator: str = "  ") -> str:
    """Build the SUBSECTION_LIST text injected into extractor prompts.

    descriptions: global "Methodology note:" — what each cell is about (constant
    across clients).
    client_notes: optional per-client additive "For this client:" appendix —
    things specific to the current company.
    """
    descriptions = descriptions or {}
    client_notes = client_notes or {}
    lines: List[str] = []
    for layer in LAYERS:
        for sub in layer.subsections:
            if sub.id not in available_subsections:
                continue
            lines.append(f"{sub.id}{separator}{sub.name}{separator}({layer.name})")
            note = (descriptions.get(sub.id) or "").strip()
            if note:
                first = True
                for line in note.splitlines():
                    prefix = "    Methodology note: " if first else "      "
                    lines.append(prefix + line)
                    first = False
            client_note = (client_notes.get(sub.id) or "").strip()
            if client_note:
                first = True
                for line in client_note.splitlines():
                    prefix = "    For this client: " if first else "      "
                    lines.append(prefix + line)
                    first = False
    return "\n".join(lines)


def extract_facts_from_llm_report(
    section_heading: str,
    section_paragraphs: List[str],
    available_subsections: List[str],
    citation_index: "dict[int, ResolvedCitation]",
    subsection_descriptions: Optional[dict] = None,
    client_subsection_notes: Optional[dict] = None,
    tone_instruction: str = "",
) -> List["ExtractedFact"]:
    """Extract atomic facts from one report section using LLM.

    Falls back to empty list if no API key configured (prototype mode).
    """
    from .ingest.classifiers.flag_heuristics import classify_with_reason

    if not section_paragraphs:
        return []

    subsection_list = _build_subsection_list(
        available_subsections, subsection_descriptions,
        client_subsection_notes, separator=" — ",
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

    system_prompt = (
        _EXTRACT_SYSTEM_TMPL
        .replace("SUBSECTION_LIST_PLACEHOLDER", subsection_list)
        .replace("__RATIONALE_RULES__", _RATIONALE_RULES.strip())
    )
    if tone_instruction:
        system_prompt = (
            "TONE INSTRUCTION (applies to every fact you emit):\n"
            + tone_instruction.strip()
            + "\n\n"
            + system_prompt
        )

    data = extract_json(generate(system_prompt, user_content, max_tokens=4096))
    if not isinstance(data, dict):
        return _stub_extract(section_heading, section_paragraphs, available_subsections)
    facts_data = data.get("facts", []) or []

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
        final_flag, heur_reason = classify_with_reason(text, llm_flag)
        rationale = (item.get("rationale") or "").strip() or heur_reason
        results.append(ExtractedFact(
            text=text[:400],
            subsection_id=sid,
            flag=final_flag,
            cite_ids=[int(c) for c in (item.get("cite_ids") or []) if str(c).isdigit()],
            confidence=max(0.0, min(1.0, float(item.get("confidence", 0.5)))),
            raw_paraphrase=(item.get("raw_paraphrase") or text)[:400],
            rationale=_normalize_rationale(final_flag, rationale),
        ))

    return results


def _normalize_rationale(flag: str, raw: Any) -> str:
    """Clip + sanity-check rationale. Green silently drops; red/grey keep.

    Belt-and-suspenders: a red/grey fact must never surface without a concern
    string. If both the LLM rationale and the heuristic reason are empty, fall
    back to a placeholder so the UI always shows *something* to the analyst.
    The real reason (LLM or heuristic) always takes priority over the placeholder.
    """
    text = (raw or "").strip() if isinstance(raw, str) else ""
    if flag == "green":
        return ""
    if not text:
        return "(требует уточнения экспертом)"
    return text[:600]


def _stub_extract(
    heading: str,
    paragraphs: List[str],
    available_subsections: List[str],
) -> List["ExtractedFact"]:
    """Deterministic stub when no LLM key is configured."""
    from .ingest.classifiers.section_to_layer import suggest_subsection
    from .ingest.classifiers.flag_heuristics import classify_with_reason

    sid = suggest_subsection(heading)
    # If heading not in synonym map, use first available subsection as fallback
    if sid is None or sid not in available_subsections:
        sid = available_subsections[0] if available_subsections else None
    if sid is None:
        return []

    results = []
    for para in paragraphs[:20]:  # process up to 20 paragraphs in stub mode
        text = para.strip()
        if len(text) < 20:
            continue
        flag, heur_reason = classify_with_reason(text, "green")
        # Harvest inline [N] citation markers so stub-extracted facts still
        # carry provenance (matches the inline-hyperlink docx format).
        cite_ids = [int(n) for n in _RE_CITE_MARKER.findall(text)]
        results.append(ExtractedFact(
            text=text[:400],
            subsection_id=sid,
            flag=flag,
            cite_ids=sorted(set(cite_ids)),
            confidence=0.3,
            raw_paraphrase=text[:400],
            rationale=_normalize_rationale(flag, heur_reason),
        ))
    return results


def extract_facts_from_full_document(
    sections: "list[tuple[str, list[str]]]",   # [(heading, paragraphs), ...]
    available_subsections: List[str],
    citation_index: "dict[int, ResolvedCitation]",
    subsection_descriptions: Optional[dict] = None,
    client_subsection_notes: Optional[dict] = None,
    tone_instruction: str = "",
) -> List["ExtractedFact"]:
    """Single LLM call for the ENTIRE document — much faster than per-section calls.

    sections: list of (heading, paragraphs) tuples (meta/conclusions already filtered out).
    Falls back to per-section stub if no LLM key.
    """
    from .ingest.classifiers.flag_heuristics import classify_with_reason

    if not sections:
        return []

    subsection_list = _build_subsection_list(
        available_subsections, subsection_descriptions, client_subsection_notes,
    )

    cite_ref = "\n".join(
        f"[{cid}] {c.title or c.canonical_url}"
        for cid, c in sorted(citation_index.items())
    ) or "(no citations)"

    # Build full document text with section headers
    doc_text = ""
    for heading, paragraphs in sections:
        doc_text += f"\n\n## {heading}\n\n"
        doc_text += "\n".join(paragraphs)

    user_content = (
        f"Available citations:\n{cite_ref}\n\n"
        f"Document:\n{doc_text[:12000]}"  # cap at ~12K chars to stay within context
    )

    system_prompt = (
        _BATCH_EXTRACT_SYSTEM_TMPL
        .replace("SUBSECTION_LIST_PLACEHOLDER", subsection_list)
        .replace("__RATIONALE_RULES__", _RATIONALE_RULES.strip())
    )
    if tone_instruction:
        system_prompt = (
            "TONE INSTRUCTION (applies to every fact you emit):\n"
            + tone_instruction.strip()
            + "\n\n"
            + system_prompt
        )

    data = extract_json(generate(system_prompt, user_content, max_tokens=8192))
    if not isinstance(data, dict):
        # Stub fallback: process each section individually
        results = []
        for heading, paragraphs in sections:
            results.extend(_stub_extract(heading, paragraphs, available_subsections))
        return results
    facts_data = data.get("facts", []) or []

    results: List[ExtractedFact] = []
    for item in facts_data:
        text = (item.get("text") or "").strip()
        sid = item.get("subsection_id") or ""
        if not text or sid not in available_subsections:
            continue
        llm_flag = item.get("flag", "green")
        if llm_flag not in ("green", "red", "grey"):
            llm_flag = "green"
        final_flag, heur_reason = classify_with_reason(text, llm_flag)
        rationale = (item.get("rationale") or "").strip() or heur_reason

        seg_start = item.get("segment_idx_start")
        seg_end = item.get("segment_idx_end")

        results.append(ExtractedFact(
            text=text[:400],
            subsection_id=sid,
            flag=final_flag,
            cite_ids=[int(c) for c in (item.get("cite_ids") or []) if str(c).isdigit()],
            confidence=max(0.0, min(1.0, float(item.get("confidence", 0.5)))),
            raw_paraphrase=(item.get("raw_paraphrase") or text)[:400],
            rationale=_normalize_rationale(final_flag, rationale),
            segment_idx_start=int(seg_start) if seg_start is not None else None,
            segment_idx_end=int(seg_end) if seg_end is not None else None,
            layer_warning=bool(item.get("layer_warning", False)),
        ))

    return results


_PDF_VISION_MODEL = os.environ.get("PDF_VISION_MODEL", "claude-sonnet-4-6")


def extract_facts_from_pdf(pdf_bytes: bytes, available_subsections: List[str], *,
                           subsection_descriptions: Optional[dict] = None,
                           client_subsection_notes: Optional[dict] = None,
                           tone_instruction: str = "", model: Optional[str] = None) -> List[ExtractedFact]:
    """Vision extraction from an ARBITRARY PDF (text OR image/scanned). Claude reads
    the document directly (no separate OCR) and maps atomic facts to matrix
    subsections. No citations — facts are sourced to the uploaded file by the caller.
    Stub-safe: no API key → []."""
    from .ingest.classifiers.flag_heuristics import classify_with_reason
    import base64
    client = globals().get("_client")
    if client is None or not pdf_bytes:
        return []

    subsection_list = _build_subsection_list(available_subsections, subsection_descriptions, client_subsection_notes)
    system_prompt = (
        _BATCH_EXTRACT_SYSTEM_TMPL
        .replace("SUBSECTION_LIST_PLACEHOLDER", subsection_list)
        .replace("__RATIONALE_RULES__", _RATIONALE_RULES.strip())
    )
    if tone_instruction:
        system_prompt = ("TONE INSTRUCTION (applies to every fact you emit):\n"
                         + tone_instruction.strip() + "\n\n" + system_prompt)

    b64 = base64.standard_b64encode(pdf_bytes).decode()
    user_text = ("Перед тобой произвольный документ (возможно картиночный/скан). Распознай его "
                 "содержимое и извлеки атомарные факты по правилам системного промпта, разложив их "
                 "по подсекциям матрицы. Источников-цитат нет — оставь cite_ids пустым. "
                 "Верни СТРОГО JSON {\"facts\":[...]}, без преамбулы.")
    try:
        resp = client.messages.create(
            model=model or _PDF_VISION_MODEL, max_tokens=8000, system=system_prompt,
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                {"type": "text", "text": user_text},
            ]}])
        raw = next((b.text for b in resp.content if b.type == "text"), "")
    except Exception as e:  # noqa: BLE001
        logger.error("extract_facts_from_pdf failed (%s): %s", type(e).__name__, e)
        # Distinguish "the file itself is rejected" (corrupt / encrypted / not a real
        # PDF) from transient errors: the former must surface to the analyst, not hide
        # as "0 facts found". Anthropic returns 400 "The PDF specified was not valid."
        msg = str(e).lower()
        if "pdf" in msg and ("not valid" in msg or "invalid" in msg or "could not" in msg):
            raise PdfRejectedError(
                "Не удалось прочитать PDF: файл повреждён, зашифрован или это скан без "
                "текстового/картиночного слоя, который мы можем разобрать. Попробуйте "
                "пересохранить файл (печать в PDF) или впишите факты вручную."
            ) from e
        return []

    data = extract_json(raw)
    if not isinstance(data, dict):
        return []
    results: List[ExtractedFact] = []
    for item in (data.get("facts") or []):
        text = (item.get("text") or "").strip()
        sid = item.get("subsection_id") or ""
        if not text or sid not in available_subsections:
            continue
        llm_flag = item.get("flag", "green")
        if llm_flag not in ("green", "red", "grey"):
            llm_flag = "green"
        final_flag, heur_reason = classify_with_reason(text, llm_flag)
        rationale = (item.get("rationale") or "").strip() or heur_reason
        results.append(ExtractedFact(
            text=text[:400], subsection_id=sid, flag=final_flag,
            confidence=max(0.0, min(1.0, float(item.get("confidence", 0.5)))),
            raw_paraphrase=(item.get("raw_paraphrase") or text)[:400],
            rationale=_normalize_rationale(final_flag, rationale)))
    return results


# ─────────────────── Transcript extractor (YouTube ingest) ──────────────────

_TRANSCRIPT_CHUNK_SYSTEM = """\
You are an IR analyst extracting facts from a podcast/interview transcript.

Your task: identify ALL meaningful statements made BY THE GUEST (interviewee) about
the founder, their company, team, product, vision, background, values, or mission.
Be generous — extract 10-25 facts per 15-minute chunk. Better to include borderline facts
than to miss important ones.

Matrix subsections (use ONLY these ids):
SUBSECTION_LIST_PLACEHOLDER

Rules:
- SKIP questions asked by the interviewer/host. SKIP pure filler ("um", "uh", "you know").
- Each fact must have TWO versions:
  * text_ru: concise factual statement in RUSSIAN (≤200 chars)
  * text_en: same fact in ENGLISH (≤200 chars)
  * quote: 1-3 sentences of LITERAL transcript text supporting this fact (verbatim)
- flag: green=positive/confirmed, red=risk/concern/failure, grey=vague/uncertain.
- segment_idx_start / segment_idx_end: [N] indices of the 1-3 segments with the quote.
- confidence: 0.0-1.0.
- Subsection guidance:
  1.1=childhood/family/origin  1.2=values/beliefs  1.3=fears/dreams/identity
  2.1=career path/expertise    2.2=founder role/motivation  2.3=co-founder dynamics
  3.1=team recruitment         3.3=investors/partners
  4.1=team expertise           4.2=team growth/scaling
  7.1=mission/vision           7.2=tensions/trade-offs

__RATIONALE_RULES__

Return ONLY valid JSON, no markdown:
{"facts": [{"text_ru": "...", "text_en": "...", "quote": "...", "subsection_id": "X.Y",
            "flag": "green|red|grey", "segment_idx_start": N, "segment_idx_end": N,
            "confidence": 0.8, "rationale": ""}]}

If truly no guest content in this chunk, return: {"facts": []}
"""


def _repair_truncated_facts_json(raw: str) -> Optional[dict]:
    """Salvage a JSON of shape {"facts":[{...},{...,]} truncated by max_tokens.

    Strategy: trim everything after the last "}," (or "}]" if intact) inside
    the array, then close. Returns parsed dict or None if unsalvageable.
    """
    last_close = max(raw.rfind("},"), raw.rfind("}]"))
    if last_close < 0:
        return None
    repaired = raw[:last_close + 1].rstrip(",") + "]}"
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        return None


# ── Universal structured-output primitives ───────────────────────────────────
# Every place that asks the model for JSON used to strip ``` only when the reply
# STARTED with a fence and then json.loads the rest — which breaks the moment a
# chatty model adds a prose preamble ("I need to analyze..."). Route all JSON
# extraction through one tolerant parser so we stop re-fighting that bug.

def extract_json(raw: Optional[str], *, repair: bool = False) -> Optional[Any]:
    """Pull a JSON value out of an LLM reply, tolerant of chatty models.

    Handles, in order: the whole string; the contents of a ```fence``` anywhere
    in the reply; the widest {...}/[...] span (prose preamble before/after). With
    ``repair=True`` also salvages a body truncated by max_tokens. Returns the
    parsed value (dict or list), or None if nothing parses.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    candidates: List[str] = [raw]
    m = re.search(r"```(?:json)?\s*(.+?)```", raw, re.DOTALL)
    if m:
        candidates.append(m.group(1).strip())
    starts = [p for p in (raw.find("{"), raw.find("[")) if p >= 0]
    ends = [p for p in (raw.rfind("}"), raw.rfind("]")) if p >= 0]
    if starts and ends and min(starts) < max(ends):
        candidates.append(raw[min(starts):max(ends) + 1])
    for cand in candidates:
        try:
            return json.loads(cand)
        except (json.JSONDecodeError, AttributeError):
            continue
    if repair:
        for cand in candidates:
            rep = _repair_truncated_facts_json(cand)
            if rep is not None:
                return rep
    return None


def generate_json(system: str, user: str, *, max_tokens: int = 4096,
                  model: Optional[str] = None, attempts: int = 2,
                  repair: bool = False) -> Optional[Any]:
    """generate() + extract_json(), retried on an empty/unparseable reply.

    A strong model occasionally returns an empty or malformed body (overload,
    truncation); one extra attempt heals the common transient. Returns the
    parsed value, or None when every attempt failed (no key / persistent error).
    """
    for _ in range(max(1, attempts)):
        raw = generate(system, user, max_tokens=max_tokens, model=model)
        if raw:
            data = extract_json(raw, repair=repair)
            if data is not None:
                return data
    return None


_RECLASSIFY_SYSTEM_TMPL = """\
You are a senior IR narrative analyst re-classifying facts into the IR Storyboard matrix
under the CURRENT methodology. Reason by MEANING, not keyword overlap.

BASE COMPANY (the client this matrix is about): «BASE_COMPANY_PLACEHOLDER».

CRITICAL — whose company is the fact about? This is the #1 source of mistakes:
- The founder-history layers L2.x describe the founder's PAST / OTHER ventures and projects
  (companies BEFORE / OTHER THAN the base company): 2.1 = professional path & decisions in
  previous products; 2.2 = relations with co-founders/teams in PREVIOUS companies; 2.3 =
  investor relations in PREVIOUS companies.
- The layers L3–L8 (community, clients, product, vision, PEST) are about the BASE company
  «BASE_COMPANY_PLACEHOLDER» ONLY.
- So: if a fact is about a DIFFERENT company/project (e.g. the founder's earlier startup),
  it almost always belongs in L2.x — NOT in L3–L8, even if the wording looks product/team/
  investor-ish. First decide WHICH company the fact is about, THEN pick the subsection.
- Some facts carry an explicit tag «про компанию: X» (X ≠ base). Treat that as a STRONG
  signal the fact is about another company → founder-history layers (L2.x).

Subsections (id — name — parent layer), with methodology notes:
SUBSECTION_LIST_PLACEHOLDER

Rules:
- Assign exactly one subsection id from the list that best fits under these notes and the
  whose-company reasoning above.
- You only decide PLACEMENT — do not rewrite the fact, do not change its meaning.
- rationale: one short phrase that MUST state which company the fact is about (base vs other).
- Set sid to null only if truly nothing fits.

Return ONLY valid JSON — no markdown fences, no explanation:
{"results":[{"sid":"X.Y","conf":0.0,"rationale":"one short phrase"}]}

One object per input fact, same order."""


def reclassify_facts(texts: List[str], descriptions: Optional[dict] = None,
                     client_notes: Optional[dict] = None,
                     about_companies: Optional[List[str]] = None,
                     base_company: str = "",
                     model: Optional[str] = None) -> List[FactCandidate]:
    """Re-classify existing fact texts against the CURRENT methodology (global descriptions
    + per-client notes injected into the prompt). Реальный Claude при наличии ключа, иначе
    keyword-стаб. Решает только раскладку по подсекциям (subsection_id), не трогает текст.

    Усилено: базовая компания как контекст + тег «про компанию» на факте как сильный сигнал
    (факт про ДРУГУЮ компанию → слои истории фаундера L2.x). Модель по умолчанию — сильнее
    (LLM_RECLASSIFY_MODEL, дефолт sonnet), т.к. это семантическое решение, не по словам."""
    if not texts:
        return []
    all_sids = [sub.id for layer in LAYERS for sub in layer.subsections]
    subsection_list = _build_subsection_list(all_sids, descriptions, client_notes)
    system = (_RECLASSIFY_SYSTEM_TMPL
              .replace("SUBSECTION_LIST_PLACEHOLDER", subsection_list)
              .replace("BASE_COMPANY_PLACEHOLDER", base_company or "the client company"))
    ab = about_companies or []
    lines = []
    for i, t in enumerate(texts):
        tag = (ab[i] if i < len(ab) else "") or ""
        hint = f"  [про компанию: {tag} — НЕ базовую]" if tag.strip() else ""
        lines.append(f"{i + 1}. {t}{hint}")
    numbered = "\n".join(lines)
    use_model = model or os.environ.get("LLM_RECLASSIFY_MODEL", "claude-sonnet-4-6")
    data = generate_json(system, numbered, max_tokens=min(8192, 90 * len(texts) + 512), model=use_model)
    results = data.get("results") if isinstance(data, dict) else None
    if not results:  # нет ключа / провал парса → keyword-фолбэк (раскладка по стабу)
        return [stub_classify(t) for t in texts]
    out: List[FactCandidate] = []
    for i, item in enumerate(results):
        text = texts[i] if i < len(texts) else (texts[-1] if texts else "")
        sid = item.get("sid") if isinstance(item, dict) else None
        conf = item.get("conf", 0.0) if isinstance(item, dict) else 0.0
        rationale = item.get("rationale", "") if isinstance(item, dict) else ""
        out.append(FactCandidate(
            text=text, suggested_subsection_id=sid, suggested_flag="green",
            confidence=max(0.0, min(1.0, float(conf or 0.0))), rationale=rationale or "",
        ))
    for i in range(len(out), len(texts)):  # модель вернула меньше — добить стабом
        out.append(stub_classify(texts[i]))
    return out


def extract_facts_from_transcript(
    segments: List[dict],
    available_subsections: List[str],
    chunk_duration_sec: float = 600.0,  # 10-min chunks (smaller output → less truncation)
    subsection_descriptions: Optional[dict] = None,
    client_subsection_notes: Optional[dict] = None,
    tone_instruction: str = "",
) -> Tuple[List["ExtractedFact"], List[dict]]:
    """Extract facts from a full transcript processed in time-windowed chunks.

    segments: list of {text, start, end} in global video time.
    subsection_descriptions: optional {sid: methodology note} to enrich the prompt.
    tone_instruction: optional one-paragraph instruction shaping how facts are phrased.
    Returns (facts, chunk_errors). chunk_errors entries:
        {"chunk_start_min": int, "chunk_end_min": int, "reason": str, "detail": str}
    Reasons: "empty_llm_response" (LLM returned ""), "invalid_json" (parse failed).
    """
    from .ingest.classifiers.flag_heuristics import classify_with_reason

    if not segments:
        return [], []

    subsection_list = _build_subsection_list(
        available_subsections, subsection_descriptions, client_subsection_notes,
    )
    system_prompt = (
        _TRANSCRIPT_CHUNK_SYSTEM
        .replace("SUBSECTION_LIST_PLACEHOLDER", subsection_list)
        .replace("__RATIONALE_RULES__", _RATIONALE_RULES.strip())
    )
    if tone_instruction:
        system_prompt = (
            "TONE INSTRUCTION (applies to every fact you emit):\n"
            + tone_instruction.strip()
            + "\n\n"
            + system_prompt
        )

    all_facts: List["ExtractedFact"] = []
    chunk_errors: List[dict] = []
    chunk_start_sec = 0.0
    i = 0

    while i < len(segments):
        chunk_end_sec = chunk_start_sec + chunk_duration_sec
        chunk_segs: list = []
        chunk_indices: list = []
        j = i
        while j < len(segments) and segments[j]["start"] < chunk_end_sec:
            chunk_segs.append(segments[j])
            chunk_indices.append(j)
            j += 1

        if not chunk_segs:
            i = max(j + 1, i + 1)
            chunk_start_sec = chunk_end_sec
            continue

        lines = []
        for local_idx, seg in enumerate(chunk_segs):
            t = int(seg["start"])
            mm, ss = divmod(t, 60)
            hh, mm = divmod(mm, 60)
            ts = f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm}:{ss:02d}"
            lines.append(f"[{local_idx}]({ts}) {seg['text'].strip()}")

        user_content = (
            f"Chunk: {int(chunk_start_sec//60)}-{int(chunk_end_sec//60)} min\n\n"
            + "\n".join(lines)
        )

        chunk_start_min = int(chunk_start_sec // 60)
        chunk_end_min = int(chunk_end_sec // 60)
        fallback_model = get_fallback_model()

        def _attempt(model: Optional[str]):
            """Returns (data, raw, parse_error, repaired_count). data is None on failure."""
            r = generate(system_prompt, user_content, max_tokens=16000, model=model)
            if not r:
                return None, "", None, None
            data = extract_json(r)
            if isinstance(data, dict):
                return data, r, None, None
            rep = _repair_truncated_facts_json(r)
            if rep is not None:
                return rep, r, None, len(rep.get("facts", []))
            return None, r, ValueError("unparseable JSON after extract+repair"), None

        data, raw, parse_error, repaired_count = _attempt(None)
        used_fallback = False
        if data is None and fallback_model:
            logger.warning(
                "extract_facts_from_transcript: chunk %d-%d min failed on primary, retrying with fallback model %s",
                chunk_start_min, chunk_end_min, fallback_model,
            )
            data2, raw2, parse_error2, repaired_count2 = _attempt(fallback_model)
            if data2 is not None:
                data, raw, parse_error, repaired_count = data2, raw2, parse_error2, repaired_count2
                used_fallback = True

        if not raw and data is None:
            chunk_errors.append({
                "chunk_start_min": chunk_start_min,
                "chunk_end_min": chunk_end_min,
                "reason": "empty_llm_response",
                "detail": "LLM returned empty string (rate-limit, overloaded, or network error)"
                          + (f"; fallback {fallback_model} also empty" if fallback_model else ""),
            })
            logger.warning(
                "extract_facts_from_transcript: chunk %d-%d min produced no LLM output",
                chunk_start_min, chunk_end_min,
            )
        else:
            if data is None:
                chunk_errors.append({
                    "chunk_start_min": chunk_start_min,
                    "chunk_end_min": chunk_end_min,
                    "reason": "invalid_json",
                    "detail": f"{type(parse_error).__name__}: {str(parse_error)[:160]} | raw[:200]={raw[:200]!r}"
                              + (f"; fallback {fallback_model} also failed" if fallback_model else ""),
                })
                logger.warning(
                    "extract_facts_from_transcript: chunk %d-%d min returned unparseable JSON (%s) — repair failed",
                    chunk_start_min, chunk_end_min, type(parse_error).__name__,
                )
            else:
                if used_fallback:
                    chunk_errors.append({
                        "chunk_start_min": chunk_start_min,
                        "chunk_end_min": chunk_end_min,
                        "reason": "fallback_used",
                        "detail": f"primary model failed; recovered via fallback model {fallback_model}",
                    })
                if repaired_count is not None:
                    chunk_errors.append({
                        "chunk_start_min": chunk_start_min,
                        "chunk_end_min": chunk_end_min,
                        "reason": "truncated_repaired",
                        "detail": f"max_tokens cutoff: recovered {repaired_count} facts from partial JSON",
                    })
                for item in data.get("facts", []):
                    try:
                        text_ru = (item.get("text_ru") or "").strip()
                        text_en = (item.get("text_en") or item.get("text") or "").strip()
                        quote = (item.get("quote") or "").strip()
                        sid = item.get("subsection_id") or ""
                        primary = text_ru or text_en
                        if not primary or sid not in available_subsections:
                            continue
                        llm_flag = item.get("flag", "green")
                        if llm_flag not in ("green", "red", "grey"):
                            llm_flag = "green"

                        local_start = item.get("segment_idx_start")
                        local_end = item.get("segment_idx_end")
                        ls = int(local_start) if local_start is not None else 0
                        le = int(local_end) if local_end is not None else ls
                        ls = max(0, min(ls, len(chunk_indices) - 1))
                        le = max(ls, min(le, len(chunk_indices) - 1))
                        global_start = chunk_indices[ls]
                        global_end = chunk_indices[le]

                        final_flag, heur_reason = classify_with_reason(primary, llm_flag)
                        rationale = (item.get("rationale") or "").strip() or heur_reason
                        all_facts.append(ExtractedFact(
                            text=primary[:400],
                            subsection_id=sid,
                            flag=final_flag,
                            cite_ids=[1],
                            confidence=max(0.0, min(1.0, float(item.get("confidence", 0.7)))),
                            raw_paraphrase=text_en[:400],
                            rationale=_normalize_rationale(final_flag, rationale),
                            segment_idx_start=global_start,
                            segment_idx_end=global_end,
                            text_ru=text_ru[:400],
                            text_en=text_en[:400],
                            quote=quote[:600],
                        ))
                    except (KeyError, IndexError, ValueError, TypeError):
                        continue

        i = j
        chunk_start_sec = chunk_end_sec
        if i >= len(segments):
            break

    return all_facts, chunk_errors


# ─────────────────── YouTube preview summary ─────────────────────────────────

_PREVIEW_SUMMARY_SYSTEM = """\
You produce a short orientation brief for an IR analyst about to triage facts
extracted from a YouTube interview. You see the video's metadata (title,
description, channel, view count, length, upload date) and the facts the
extractor pulled, grouped by matrix subsection.

Return ONLY valid JSON in this exact shape (no markdown fences):
{
  "video_brief": "<3-6 sentences: who interviews whom, what was the angle, main themes, why this video is worth processing for the IR matrix. Plain prose, no bullet list.>",
  "cell_briefs": {
    "1.1": "<one sentence in the same language as the facts — what aspect of this cell the video covered, e.g. 'Рассказал о детстве в Москве и переезде в Тель-Авив'. Not a quote. No 'this video covers...' filler. Start with a verb.>",
    "2.2": "...",
    ...
  }
}

Rules:
- `cell_briefs` has ONE entry per subsection_id that actually appears in the facts list. Skip cells with no facts.
- Each cell brief: ONE sentence, <= 25 words, summarizing what the founder/interview revealed for that cell. Plain prose, no bullets.
- Use the language of the facts (Russian if facts are in Russian).
- Stay strictly within what the metadata + facts say. No invented detail.
- Do not duplicate the title verbatim in video_brief; paraphrase + add the angle.
"""


def summarize_youtube_preview(
    meta: dict,                           # title/description/channel_name/duration_sec/upload_date/view_count/like_count
    facts_by_sid: "dict[str, list[str]]",  # {subsection_id: [fact text, ...]} — only filled cells
    subsection_names: "dict[str, str]",   # {sid: "Origin & Childhood"}
    tone_instruction: str = "",
) -> "dict":
    """One LLM call that returns {'video_brief': str, 'cell_briefs': {sid: str}}.

    Returns empty defaults on any failure (LLM unavailable, parse error, etc).
    Caller is responsible for surfacing them; absence is non-fatal for preview.
    """
    if not facts_by_sid and not (meta.get("title") or meta.get("description")):
        return {"video_brief": "", "cell_briefs": {}}

    # Build a compact representation of facts grouped by cell
    cells_block_lines: List[str] = []
    for sid in sorted(facts_by_sid.keys()):
        facts = facts_by_sid[sid]
        if not facts:
            continue
        name = subsection_names.get(sid, "")
        cells_block_lines.append(f"\n[{sid}] {name} — {len(facts)} fact(s):")
        for f in facts[:25]:   # cap per-cell to avoid bloat
            cells_block_lines.append(f"  - {f[:300]}")
        if len(facts) > 25:
            cells_block_lines.append(f"  ... and {len(facts) - 25} more")
    cells_block = "\n".join(cells_block_lines) or "(no facts extracted)"

    duration_min = (meta.get("duration_sec") or 0) // 60
    stats_line = []
    if meta.get("view_count") is not None:
        stats_line.append(f"{meta['view_count']:,} views")
    if meta.get("like_count") is not None:
        stats_line.append(f"{meta['like_count']:,} likes")
    if duration_min:
        stats_line.append(f"{duration_min} min long")
    if meta.get("upload_date"):
        stats_line.append(f"uploaded {meta['upload_date']}")

    user_content = (
        f"VIDEO TITLE: {meta.get('title', '')}\n"
        f"CHANNEL: {meta.get('channel_name', '')}\n"
        f"STATS: {', '.join(stats_line) if stats_line else '(no stats)'}\n\n"
        f"DESCRIPTION:\n{(meta.get('description') or '(no description)')[:3000]}\n\n"
        f"FACTS BY CELL:{cells_block}"
    )

    system_prompt = _PREVIEW_SUMMARY_SYSTEM
    if tone_instruction:
        system_prompt = (
            "TONE INSTRUCTION (applies to every line you write):\n"
            + tone_instruction.strip()
            + "\n\n"
            + system_prompt
        )

    data = extract_json(generate(system_prompt, user_content, max_tokens=2000))
    if not isinstance(data, dict):
        return {"video_brief": "", "cell_briefs": {}}

    video_brief = (data.get("video_brief") or "").strip()
    cell_briefs_raw = data.get("cell_briefs") or {}
    cell_briefs: dict = {}
    if isinstance(cell_briefs_raw, dict):
        for sid, brief in cell_briefs_raw.items():
            if isinstance(brief, str) and brief.strip() and sid in facts_by_sid:
                cell_briefs[str(sid)] = brief.strip()

    return {"video_brief": video_brief, "cell_briefs": cell_briefs}


# ─────────────────── Research single-source extractor ──────────────────────

_RESEARCH_EXTRACT_SYSTEM = """\
You are a fact extractor for an IR narrative matrix (ir-storyboard).

Source: ONE web article, interview write-up, press release, blog post,
podcast transcript, or similar short-form text about a company / founder.

Matrix subsections (use ONLY these ids, exactly as written):
SUBSECTION_LIST_PLACEHOLDER

YOUR TASK: extract ALL atomic facts in the source that fit one of those
subsections. Be GENEROUS — a typical article yields 15-50 atomic facts.
Better to surface a borderline fact than to miss an important one.

Rules:
- One fact = ONE atomic claim, <=300 characters. Split bundled claims:
  "Mark is the CEO and previously worked at Google" → TWO facts.
- Stay STRICTLY within what the source says. No interpretation, no
  invention, no industry-knowledge fill-ins.
- Pick the best-fit subsection_id from the list. If genuinely uncertain,
  skip the fact — do NOT guess.
- flag:
  * green = confirmed positive / neutral fact (raise, hire, milestone,
    plan, product feature, biographical fact).
  * red = risk / concern / failure / controversy / regulatory issue /
    explicit doubt voiced by the source.
  * grey = explicit gap / "did not disclose" / "unclear" / hedged claim.
- raw_paraphrase: copy the supporting sentence(s) near-verbatim (<=300 chars).
- confidence: 0.0-1.0. Use 0.85+ for direct quotes/clear claims, 0.5-0.7
  for paraphrased context, <0.5 for inferred statements.

__RATIONALE_RULES__

Output ONLY valid JSON (no markdown fences, no commentary):
{"facts": [
  {"text": "...", "subsection_id": "X.Y", "flag": "green|red|grey",
   "confidence": 0.85, "raw_paraphrase": "...", "rationale": ""}
]}

If the source truly contains no usable facts (extremely rare for a real
article), return {"facts": []}.
"""


def extract_facts_from_research_text(
    text: str,
    source_title: str = "",
    available_subsections: Optional[List[str]] = None,
    subsection_descriptions: Optional[dict] = None,
    client_subsection_notes: Optional[dict] = None,
    tone_instruction: str = "",
) -> List["ExtractedFact"]:
    """Atomic-fact extractor tuned for a single Research source (article, etc).

    Unlike extract_facts_from_full_document this prompt:
      - does not require [N] citation markers (web articles don't have them);
      - encourages broad extraction (15-50 facts per article);
      - does not auto-skip L1 (caller controls via available_subsections).

    Returns [] silently on any LLM/parse failure — Research tab surfaces
    "0 facts" to the user, which is the meaningful signal.
    """
    from .ingest.classifiers.flag_heuristics import classify_with_reason

    text = (text or "").strip()
    if not text:
        return []

    if available_subsections is None:
        available_subsections = [
            sub.id for layer in LAYERS for sub in layer.subsections
        ]

    subsection_list = _build_subsection_list(
        available_subsections, subsection_descriptions, client_subsection_notes,
    )
    system_prompt = (
        _RESEARCH_EXTRACT_SYSTEM
        .replace("SUBSECTION_LIST_PLACEHOLDER", subsection_list)
        .replace("__RATIONALE_RULES__", _RATIONALE_RULES.strip())
    )
    if tone_instruction:
        system_prompt = (
            "TONE INSTRUCTION (applies to every fact you emit):\n"
            + tone_instruction.strip()
            + "\n\n"
            + system_prompt
        )

    header = f"TITLE: {source_title}\n\n" if source_title else ""
    # Cap to ~16K chars to stay within context with sizable subsection list
    user_content = f"{header}ARTICLE:\n{text[:16000]}"

    # repair=True salvages a fact list truncated by max_tokens
    data = extract_json(generate(system_prompt, user_content, max_tokens=8192), repair=True)
    if not isinstance(data, dict):
        return []

    results: List[ExtractedFact] = []
    for item in data.get("facts", []) or []:
        try:
            fact_text = (item.get("text") or "").strip()
            sid = item.get("subsection_id") or ""
            if not fact_text or sid not in available_subsections:
                continue
            llm_flag = item.get("flag", "green")
            if llm_flag not in ("green", "red", "grey"):
                llm_flag = "green"
            final_flag, heur_reason = classify_with_reason(fact_text, llm_flag)
            rationale = (item.get("rationale") or "").strip() or heur_reason
            results.append(ExtractedFact(
                text=fact_text[:400],
                subsection_id=sid,
                flag=final_flag,
                cite_ids=[],
                confidence=max(0.0, min(1.0, float(item.get("confidence", 0.6)))),
                raw_paraphrase=(item.get("raw_paraphrase") or fact_text)[:400],
                rationale=_normalize_rationale(final_flag, rationale),
            ))
        except (ValueError, TypeError, AttributeError):
            continue

    return results
