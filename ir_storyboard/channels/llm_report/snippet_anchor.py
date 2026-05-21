"""SnippetAnchor: attach timestamp URL + literal evidence_snippet to YouTube facts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ...llm import ExtractedFact
    from .loaders.transcriber import Transcript, TranscriptSegment


@dataclass
class AnchoredFact:
    """ExtractedFact enriched with YouTube-specific provenance."""
    text: str
    subsection_id: str
    flag: str
    cite_ids: list[int] = field(default_factory=list)
    confidence: float = 0.5
    raw_paraphrase: str = ""
    segment_idx_start: Optional[int] = None
    segment_idx_end: Optional[int] = None
    layer_warning: bool = False

    # Added by SnippetAnchor
    evidence_snippet: str = ""
    source_url: str = ""          # canonical_url?t={start_sec}s
    snippet_start_sec: float = 0.0
    snippet_end_sec: float = 0.0
    needs_review: bool = False


_MIN_SNIPPET_CHARS = 20
_MAX_EXPAND = 2   # how many extra segments we try when snippet is too short


def anchor_facts(
    facts: "list[ExtractedFact]",
    transcript: "Transcript",
    canonical_url: str,
) -> list[AnchoredFact]:
    """Build AnchoredFact list: evidence_snippet + timestamp URL for each fact.

    For each fact:
      - joins transcript.segments[idx_start..idx_end].text → evidence_snippet
      - if result < 20 chars: expands idx_end up to idx_end+2
      - if still < 20: needs_review=True, flag→grey
      - source_url = f'{canonical_url}&t={int(start_sec)}s'
    """
    segs = transcript.segments
    n = len(segs)
    anchored: list[AnchoredFact] = []

    for fact in facts:
        idx_start = fact.segment_idx_start
        idx_end = fact.segment_idx_end

        # Facts without segment indices (e.g. from document mode): minimal anchor
        if idx_start is None or idx_end is None:
            anchored.append(AnchoredFact(
                text=fact.text,
                subsection_id=fact.subsection_id,
                flag=fact.flag,
                cite_ids=fact.cite_ids,
                confidence=fact.confidence,
                raw_paraphrase=fact.raw_paraphrase,
                segment_idx_start=idx_start,
                segment_idx_end=idx_end,
                layer_warning=fact.layer_warning,
                evidence_snippet=fact.raw_paraphrase or fact.text,
                source_url=canonical_url,
                needs_review=True,
            ))
            continue

        # Clamp to valid range
        idx_start = max(0, min(idx_start, n - 1))
        idx_end = max(idx_start, min(idx_end, n - 1))

        snippet, idx_end = _build_snippet(segs, idx_start, idx_end, n)

        needs_review = False
        flag = fact.flag
        if len(snippet.strip()) < _MIN_SNIPPET_CHARS:
            needs_review = True
            if flag != "grey":
                flag = "grey"

        start_sec = segs[idx_start].start if segs else 0.0
        end_sec = segs[idx_end].end if segs else 0.0
        source_url = f"{canonical_url}&t={int(start_sec)}s"

        anchored.append(AnchoredFact(
            text=fact.text,
            subsection_id=fact.subsection_id,
            flag=flag,
            cite_ids=fact.cite_ids,
            confidence=fact.confidence,
            raw_paraphrase=fact.raw_paraphrase,
            segment_idx_start=idx_start,
            segment_idx_end=idx_end,
            layer_warning=fact.layer_warning,
            evidence_snippet=snippet,
            source_url=source_url,
            snippet_start_sec=start_sec,
            snippet_end_sec=end_sec,
            needs_review=needs_review,
        ))

    return anchored


def _build_snippet(
    segs: "list[TranscriptSegment]",
    idx_start: int,
    idx_end: int,
    n: int,
) -> tuple[str, int]:
    """Join segments[idx_start..idx_end] into snippet.  Expand if < 20 chars."""
    snippet = " ".join(s.text.strip() for s in segs[idx_start: idx_end + 1])

    for _ in range(_MAX_EXPAND):
        if len(snippet.strip()) >= _MIN_SNIPPET_CHARS:
            break
        if idx_end + 1 < n:
            idx_end += 1
            snippet = " ".join(s.text.strip() for s in segs[idx_start: idx_end + 1])
        else:
            break

    return snippet.strip(), idx_end
