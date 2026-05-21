"""Adapt a Transcript into a LLMReportIR for FactExtractor reuse."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .ir import LLMReportIR, RawCitation, RawSection

if TYPE_CHECKING:
    from .loaders.transcriber import Transcript
    from .loaders.youtube_url import YouTubeVideoMeta


_PAUSE_THRESHOLD_SEC = 2.0   # group segments into paragraphs on pauses > this
_MAX_PARAGRAPH_CHARS = 500   # or split when a paragraph exceeds this


def transcript_to_ir(transcript: "Transcript", meta: "YouTubeVideoMeta") -> LLMReportIR:
    """Convert Transcript → LLMReportIR compatible with FactExtractor.

    Produces:
      - One RawSection "Transcript" with paragraphs built from segments,
        split on pauses > 2s OR every ~500 chars.
      - One RawCitation with forced_channel='online_interview'.
      - parser_notes includes JSON-serialised segments for SnippetAnchor (Task 5).
    """
    segs = transcript.segments

    # Build paragraphs: group segments by pause or char limit
    paragraphs: list[str] = []
    current_parts: list[str] = []
    current_chars = 0

    for i, seg in enumerate(segs):
        text = seg.text.strip()
        if not text:
            continue

        # Detect pause relative to previous segment
        long_pause = (
            i > 0
            and (seg.start - segs[i - 1].end) > _PAUSE_THRESHOLD_SEC
        )
        char_overflow = current_chars + len(text) > _MAX_PARAGRAPH_CHARS

        if (long_pause or char_overflow) and current_parts:
            paragraphs.append(" ".join(current_parts))
            current_parts = []
            current_chars = 0

        current_parts.append(text)
        current_chars += len(text) + 1

    if current_parts:
        paragraphs.append(" ".join(current_parts))

    section = RawSection(
        heading="Transcript",
        level=1,
        paragraphs=paragraphs,
    )

    citation = RawCitation(
        cite_id=1,
        raw_marker="[1]",
        url=meta.canonical_url,
        title=meta.title,
        publisher=meta.channel_name,
        forced_channel="online_interview",
    )

    # Serialise segments into parser_notes for SnippetAnchor
    segments_note = "__transcript_segments__:" + json.dumps([
        {"text": s.text, "start": s.start, "end": s.end}
        for s in segs
    ])

    return LLMReportIR(
        source_filename=meta.canonical_url,
        detected_agent="youtube",
        detected_cite_format="bracket_n",
        sections=[section],
        citations=[citation],
        parser_notes=[segments_note],
    )
