"""Tests for snippet_anchor.py."""
import pytest
from unittest.mock import MagicMock

from ir_storyboard.channels.llm_report.snippet_anchor import anchor_facts, AnchoredFact
from ir_storyboard.channels.llm_report.loaders.transcriber import TranscriptSegment, Transcript
from ir_storyboard.llm import ExtractedFact


def _make_transcript(segments):
    return Transcript(
        segments=segments,
        language="en",
        transcriber="local-faster-whisper:large-v3-turbo",
        duration_sec=int(segments[-1].end) if segments else 0,
    )


def _make_fact(subsection_id="2.1", flag="green", idx_start=0, idx_end=0, text="Test fact."):
    return ExtractedFact(
        text=text,
        subsection_id=subsection_id,
        flag=flag,
        segment_idx_start=idx_start,
        segment_idx_end=idx_end,
        confidence=0.9,
        raw_paraphrase="raw paraphrase text here",
    )


# ── happy path ────────────────────────────────────────────────────────────────

def test_anchor_single_segment_above_20chars():
    segs = [TranscriptSegment("I joined Bitfury back in 2014.", 420.0, 423.0)]
    transcript = _make_transcript(segs)
    fact = _make_fact(idx_start=0, idx_end=0)

    result = anchor_facts([fact], transcript, "https://www.youtube.com/watch?v=abc123")

    assert len(result) == 1
    af = result[0]
    assert af.evidence_snippet == "I joined Bitfury back in 2014."
    assert "t=420s" in af.source_url
    assert af.needs_review is False
    assert af.flag == "green"


def test_anchor_source_url_has_timestamp():
    segs = [TranscriptSegment("We started this journey long ago and never looked back.", 756.0, 760.0)]
    transcript = _make_transcript(segs)
    fact = _make_fact(idx_start=0, idx_end=0)

    result = anchor_facts([fact], transcript, "https://www.youtube.com/watch?v=abc123")
    assert "t=756s" in result[0].source_url


# ── short segment expansion ────────────────────────────────────────────────────

def test_anchor_expands_short_segments():
    """Short first segment (<20 chars) → expands to include next segment."""
    segs = [
        TranscriptSegment("Short one.", 0.0, 1.0),   # 10 chars — too short alone
        TranscriptSegment("But this makes it long enough to pass the check.", 1.5, 4.0),
    ]
    transcript = _make_transcript(segs)
    fact = _make_fact(idx_start=0, idx_end=0)

    result = anchor_facts([fact], transcript, "https://www.youtube.com/watch?v=abc123")
    af = result[0]
    assert len(af.evidence_snippet.strip()) >= 20
    assert af.needs_review is False


def test_anchor_falls_back_to_grey():
    """If all reachable segments are too short, flag→grey and needs_review=True."""
    segs = [
        TranscriptSegment("Hi.", 0.0, 0.5),
        TranscriptSegment("Yes.", 1.0, 1.5),
        TranscriptSegment("OK.", 2.0, 2.5),
    ]
    transcript = _make_transcript(segs)
    fact = _make_fact(idx_start=0, idx_end=0, flag="green")

    result = anchor_facts([fact], transcript, "https://www.youtube.com/watch?v=abc123")
    af = result[0]
    assert af.needs_review is True
    assert af.flag == "grey"


# ── snippet_start_sec / snippet_end_sec ──────────────────────────────────────

def test_anchor_stores_time_range():
    segs = [
        TranscriptSegment("First segment here.", 100.0, 103.0),
        TranscriptSegment("Second segment here.", 103.5, 106.0),
    ]
    transcript = _make_transcript(segs)
    fact = _make_fact(idx_start=0, idx_end=1)

    result = anchor_facts([fact], transcript, "https://www.youtube.com/watch?v=abc123")
    af = result[0]
    assert af.snippet_start_sec == pytest.approx(100.0)
    assert af.snippet_end_sec == pytest.approx(106.0)
