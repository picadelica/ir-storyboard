"""Tests for transcript_to_ir.py + forced_channel in citations."""
import json
import pytest
from unittest.mock import MagicMock

from ir_storyboard.ingest.loaders.transcriber import TranscriptSegment, Transcript
from ir_storyboard.ingest.transcript_to_ir import transcript_to_ir
from ir_storyboard.ingest.citations import extract_citations
from ir_storyboard.ingest.ir import RawCitation, LLMReportIR, RawSection


def _make_meta(url="https://www.youtube.com/watch?v=abc123"):
    m = MagicMock()
    m.canonical_url = url
    m.title = "Test Video"
    m.channel_name = "Test Channel"
    m.language = "en"
    m.video_id = "abc123"
    return m


def _make_transcript(segments):
    return Transcript(
        segments=segments,
        language="en",
        transcriber="local-faster-whisper:large-v3-turbo",
        duration_sec=int(segments[-1].end) if segments else 0,
    )


# ── transcript_to_ir basic ────────────────────────────────────────────────────

def test_transcript_to_ir_basic():
    segs = [
        TranscriptSegment("Hello, I'm the founder.", 0.0, 2.0),
        TranscriptSegment("We started in 2020.", 2.5, 4.5),
        # pause > 2s
        TranscriptSegment("Our mission is big.", 10.0, 12.0),
        TranscriptSegment("We want to change the world.", 12.5, 14.5),
        TranscriptSegment("That is what drives us.", 15.0, 17.0),
        TranscriptSegment("Every single day.", 17.5, 18.5),
        TranscriptSegment("It matters.", 19.0, 20.0),
        TranscriptSegment("Deeply.", 20.5, 21.0),
        TranscriptSegment("Always.", 21.5, 22.0),
        TranscriptSegment("Forever.", 22.5, 23.0),
    ]
    transcript = _make_transcript(segs)
    meta = _make_meta()

    ir = transcript_to_ir(transcript, meta)

    assert len(ir.sections) == 1
    assert ir.sections[0].heading == "Transcript"
    assert len(ir.sections[0].paragraphs) >= 1

    assert len(ir.citations) == 1
    cit = ir.citations[0]
    assert cit.forced_channel == "online_interview"
    assert cit.url == meta.canonical_url
    assert cit.cite_id == 1


def test_transcript_to_ir_preserves_segments_in_notes():
    """parser_notes must contain serialised segments for SnippetAnchor."""
    segs = [
        TranscriptSegment("Segment one.", 0.0, 2.0),
        TranscriptSegment("Segment two.", 3.0, 5.0),
    ]
    transcript = _make_transcript(segs)
    meta = _make_meta()

    ir = transcript_to_ir(transcript, meta)

    seg_note = next((n for n in ir.parser_notes if n.startswith("__transcript_segments__:")), None)
    assert seg_note is not None, "parser_notes must contain __transcript_segments__ entry"

    stored = json.loads(seg_note.split(":", 1)[1])
    assert len(stored) == 2
    assert stored[0]["text"] == "Segment one."
    assert stored[0]["start"] == pytest.approx(0.0)
    assert stored[1]["end"] == pytest.approx(5.0)


def test_transcript_to_ir_pause_splits_paragraphs():
    """Segments separated by >2s pause → different paragraphs."""
    segs = [
        TranscriptSegment("Part one.", 0.0, 1.0),
        # 5s pause
        TranscriptSegment("Part two.", 6.0, 7.0),
    ]
    transcript = _make_transcript(segs)
    ir = transcript_to_ir(transcript, _make_meta())

    assert len(ir.sections[0].paragraphs) == 2
    assert "Part one." in ir.sections[0].paragraphs[0]
    assert "Part two." in ir.sections[0].paragraphs[1]


# ── forced_channel in citations.extract_citations ─────────────────────────────

def test_classify_respects_forced_channel():
    """A RawCitation with forced_channel skips URL classifier."""
    # YouTube URL would normally → online_interview, but forced_channel overrides
    citation = RawCitation(
        cite_id=1,
        raw_marker="[1]",
        url="https://www.youtube.com/watch?v=abc123",
        title="Some Video",
        publisher="Channel",
        forced_channel="online_interview",
    )
    ir = LLMReportIR(
        source_filename="test",
        detected_agent="youtube",
        detected_cite_format="bracket_n",
        citations=[citation],
    )
    resolved = extract_citations(ir)

    assert len(resolved) == 1
    assert resolved[0].channel == "online_interview"
    assert "forced_channel" in resolved[0].classification_reason


def test_classify_forced_channel_overrides_url_classifier():
    """Even a non-interview URL respects forced_channel."""
    citation = RawCitation(
        cite_id=1,
        raw_marker="[1]",
        url="https://www.sec.gov/filing",   # would be 'archival' without forced
        title="Filing",
        publisher="SEC",
        forced_channel="online_interview",
    )
    ir = LLMReportIR(
        source_filename="test",
        detected_agent="youtube",
        detected_cite_format="bracket_n",
        citations=[citation],
    )
    resolved = extract_citations(ir)

    assert resolved[0].channel == "online_interview"
