"""SnippetResolver: attach evidence_snippet to each extracted fact.

MVP mode (default, 'paraphrase'):
  Uses raw_paraphrase from the LLM report as the snippet.
  No HTTP calls. Facts with short paraphrase (<20 chars) are downgraded to grey + needs_review.

v2 mode ('fetch', behind LLM_REPORT_RESOLVE_FETCH=1):
  HTTP-fetches the source URL, finds the closest sentence to raw_paraphrase,
  returns it as evidence_snippet. Falls back to paraphrase on network errors.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from ..llm import ExtractedFact

if TYPE_CHECKING:
    from .citations import ResolvedCitation


@dataclass
class ResolvedFact:
    """ExtractedFact enriched with evidence_snippet for matrix commit."""
    # Core fields from ExtractedFact
    text: str
    subsection_id: str
    flag: str
    cite_ids: list[int] = field(default_factory=list)
    confidence: float = 0.5
    raw_paraphrase: str = ""
    rationale: str = ""

    # Snippet fields added by resolver
    evidence_snippet: str = ""
    needs_review: bool = False
    snippet_source: Literal["llm_paraphrase", "http_fetch", "wayback_fetch"] = "llm_paraphrase"


def resolve_snippets(
    facts: list[ExtractedFact],
    citation_index: "dict[int, ResolvedCitation]",
    mode: Literal["paraphrase", "fetch"] = "paraphrase",
) -> list[ResolvedFact]:
    """Attach evidence_snippet to each fact.

    mode='paraphrase': MVP — use raw_paraphrase, no network.
    mode='fetch': v2 — HTTP fetch + sentence similarity (behind feature flag).
    """
    if mode == "fetch" and os.environ.get("LLM_REPORT_RESOLVE_FETCH") == "1":
        return _resolve_fetch(facts, citation_index)
    return _resolve_paraphrase(facts)


# ── paraphrase mode (MVP) ─────────────────────────────────────────────────────

def _resolve_paraphrase(facts: list[ExtractedFact]) -> list[ResolvedFact]:
    result = []
    for f in facts:
        snippet = (f.raw_paraphrase or f.text).strip()[:400]
        short = len(snippet.strip()) < 20
        flag = "grey" if short else f.flag
        result.append(ResolvedFact(
            text=f.text,
            subsection_id=f.subsection_id,
            flag=flag,
            cite_ids=f.cite_ids,
            confidence=f.confidence,
            raw_paraphrase=f.raw_paraphrase,
            rationale=(f.rationale if flag != "green" else ""),
            evidence_snippet=snippet,
            needs_review=short,
            snippet_source="llm_paraphrase",
        ))
    return result


# ── fetch mode (v2, behind LLM_REPORT_RESOLVE_FETCH=1) ──────────────────────

_MIN_SIMILARITY = 0.7
_FETCH_TIMEOUT = 10.0


def _word_shingles(text: str, n: int = 3) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i: i + n]) for i in range(len(words) - n + 1)}


def _similarity(a: str, b: str) -> float:
    sa = _word_shingles(a)
    sb = _word_shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _best_sentence(text: str, reference: str) -> tuple[str, float]:
    """Find the sentence in text most similar to reference."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    best, best_score = "", 0.0
    for sent in sentences:
        score = _similarity(sent, reference)
        if score > best_score:
            best, best_score = sent, score
    return best.strip()[:400], best_score


def _fetch_text(url: str) -> str | None:
    """Fetch URL text. Returns None on errors."""
    try:
        import urllib.request
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ir-storyboard/2.0 (snippet-resolver; +https://ir-storyboard.internal)"},
        )
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            raw = resp.read(500_000).decode("utf-8", errors="replace")
        return _extract_text_from_html(raw)
    except Exception:
        return None


def _extract_text_from_html(html: str) -> str:
    """Basic HTML → text extraction without third-party deps."""
    # Strip script/style
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _wayback_url(url: str) -> str:
    return f"https://web.archive.org/web/2*/{url}"


def _resolve_fetch(
    facts: list[ExtractedFact],
    citation_index: "dict[int, ResolvedCitation]",
) -> list[ResolvedFact]:
    result = []
    for f in facts:
        snippet, source, needs_review, flag = _fetch_snippet_for_fact(f, citation_index)
        final_flag = "grey" if needs_review else flag
        result.append(ResolvedFact(
            text=f.text,
            subsection_id=f.subsection_id,
            flag=final_flag,
            cite_ids=f.cite_ids,
            confidence=f.confidence,
            raw_paraphrase=f.raw_paraphrase,
            rationale=(f.rationale if final_flag != "green" else ""),
            evidence_snippet=snippet,
            needs_review=needs_review,
            snippet_source=source,
        ))
    return result


def _fetch_snippet_for_fact(
    fact: ExtractedFact,
    citation_index: "dict[int, ResolvedCitation]",
) -> tuple[str, Literal["llm_paraphrase", "http_fetch", "wayback_fetch"], bool, str]:
    """Try to fetch a real snippet; returns (snippet, source, needs_review, flag)."""
    # Find a URL to fetch
    url = None
    for cid in fact.cite_ids:
        cit = citation_index.get(cid)
        if cit and cit.canonical_url:
            url = cit.canonical_url
            break

    if not url:
        return _paraphrase_fallback(fact)

    # Try direct fetch
    page_text = _fetch_text(url)
    if page_text:
        sentence, score = _best_sentence(page_text, fact.raw_paraphrase or fact.text)
        if score >= _MIN_SIMILARITY and len(sentence) >= 20:
            return sentence, "http_fetch", False, fact.flag

    # Try Wayback fallback
    page_text = _fetch_text(_wayback_url(url))
    if page_text:
        sentence, score = _best_sentence(page_text, fact.raw_paraphrase or fact.text)
        if score >= _MIN_SIMILARITY and len(sentence) >= 20:
            return sentence, "wayback_fetch", False, fact.flag

    return _paraphrase_fallback(fact)


def _paraphrase_fallback(
    fact: ExtractedFact,
) -> tuple[str, Literal["llm_paraphrase"], bool, str]:
    snippet = (fact.raw_paraphrase or fact.text).strip()[:400]
    short = len(snippet.strip()) < 20
    return snippet, "llm_paraphrase", True, "grey" if short else fact.flag
