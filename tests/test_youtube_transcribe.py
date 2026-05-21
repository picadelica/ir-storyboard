"""Tests for transcriber.py — caching, multi-chunk, overlap dedup."""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from ir_storyboard.channels.llm_report.loaders.transcriber import (
    TranscriptSegment,
    Transcript,
    dedup_overlap_segments,
    get_or_transcribe,
    _ensure_transcripts_table,
    LocalFasterWhisperTranscriber,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _ensure_transcripts_table(conn)
    return conn


def _make_meta(video_id="test123", duration_sec=1800):
    m = MagicMock()
    m.video_id = video_id
    m.canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    m.title = "Test Video"
    m.channel_name = "Test Channel"
    m.duration_sec = duration_sec
    m.language = "en"
    return m


def _seed_cache(conn, video_id, transcriber_name, segments, duration_sec=1800):
    segs_json = json.dumps([{"text": s.text, "start": s.start, "end": s.end} for s in segments])
    conn.execute(
        """INSERT INTO youtube_transcripts
            (video_id, canonical_url, title, channel_name, duration_sec,
             language, transcriber, segments_json, transcribed_at, transcribe_duration_sec)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 0)""",
        (video_id, f"https://www.youtube.com/watch?v={video_id}",
         "Cached Video", "Cached Channel", duration_sec,
         "en", transcriber_name, segs_json),
    )
    conn.commit()


# ── cache hit ─────────────────────────────────────────────────────────────────

def test_get_or_transcribe_cache_hit_same_transcriber(tmp_path):
    conn = _make_conn()
    meta = _make_meta()
    segs = [TranscriptSegment("hello world", 0.0, 2.0)]
    _seed_cache(conn, "test123", "local-faster-whisper:large-v3-turbo", segs)

    mock_transcriber = MagicMock()
    mock_transcriber.name = "local-faster-whisper:large-v3-turbo"

    with patch("ir_storyboard.channels.llm_report.loaders.transcriber.fetch_audio") as fa, \
         patch("ir_storyboard.channels.llm_report.loaders.transcriber.split_audio") as sa:
        result = get_or_transcribe("test123", meta, mock_transcriber, conn, cache_dir=tmp_path)

    fa.assert_not_called()
    sa.assert_not_called()
    mock_transcriber.transcribe.assert_not_called()
    assert len(result.segments) == 1
    assert result.segments[0].text == "hello world"


# ── cache miss, single chunk ──────────────────────────────────────────────────

def test_get_or_transcribe_cache_miss_single_chunk(tmp_path):
    conn = _make_conn()
    meta = _make_meta()

    mock_transcriber = MagicMock()
    mock_transcriber.name = "local-faster-whisper:large-v3-turbo"
    mock_transcriber.transcribe.return_value = [
        TranscriptSegment("segment one", 0.0, 2.0),
        TranscriptSegment("segment two", 2.5, 5.0),
    ]

    fake_audio = tmp_path / "test123.opus"
    fake_audio.touch()

    from ir_storyboard.channels.llm_report.loaders.audio_chunker import AudioChunk
    fake_chunk = AudioChunk(path=fake_audio, chunk_start_sec=0.0, chunk_end_sec=1800.0)

    with patch("ir_storyboard.channels.llm_report.loaders.transcriber.fetch_audio", return_value=fake_audio), \
         patch("ir_storyboard.channels.llm_report.loaders.transcriber.split_audio", return_value=[fake_chunk]):
        result = get_or_transcribe("test123", meta, mock_transcriber, conn, cache_dir=tmp_path)

    assert len(result.segments) == 2
    assert result.segments[0].text == "segment one"

    row = conn.execute("SELECT * FROM youtube_transcripts WHERE video_id='test123'").fetchone()
    assert row is not None
    stored = json.loads(row["segments_json"])
    assert len(stored) == 2


# ── multi-chunk offset timestamps ────────────────────────────────────────────

def test_get_or_transcribe_multi_chunk_offsets_timestamps(tmp_path):
    conn = _make_conn()
    meta = _make_meta(duration_sec=7200)

    def fake_transcribe(audio_path, language_hint=None):
        # Returns same segments for each chunk (relative to chunk start = 0)
        return [
            TranscriptSegment("chunk text A", 0.0, 60.0),
            TranscriptSegment("chunk text B", 60.0, 120.0),
            TranscriptSegment("chunk text C", 120.0, 180.0),
        ]

    mock_transcriber = MagicMock()
    mock_transcriber.name = "local-faster-whisper:large-v3-turbo"
    mock_transcriber.transcribe.side_effect = fake_transcribe

    fake_audio = tmp_path / "long.opus"
    fake_audio.touch()
    chunk1 = tmp_path / "chunk0.opus"
    chunk1.touch()
    chunk2 = tmp_path / "chunk1.opus"
    chunk2.touch()

    from ir_storyboard.channels.llm_report.loaders.audio_chunker import AudioChunk
    chunks = [
        AudioChunk(path=chunk1, chunk_start_sec=0.0, chunk_end_sec=3600.0),
        AudioChunk(path=chunk2, chunk_start_sec=3600.0, chunk_end_sec=7200.0),
    ]

    with patch("ir_storyboard.channels.llm_report.loaders.transcriber.fetch_audio", return_value=fake_audio), \
         patch("ir_storyboard.channels.llm_report.loaders.transcriber.split_audio", return_value=chunks):
        result = get_or_transcribe("long123", meta, mock_transcriber, conn, cache_dir=tmp_path)

    starts = [s.start for s in result.segments]
    # chunk 0: 0, 60, 120 ; chunk 1 (offset 3600): 3600, 3660, 3720
    assert 0.0 in starts
    assert 3600.0 in starts
    assert 3660.0 in starts


# ── overlap dedup ─────────────────────────────────────────────────────────────

def test_overlap_dedup_drops_duplicate_in_boundary_zone():
    # chunk[0] last segment ends just before boundary
    chunk0 = [
        TranscriptSegment("we joined Bitfury in 2014", 3594.0, 3598.0),
    ]
    # chunk[1] first segment is a near-duplicate, starts slightly before boundary
    chunk1 = [
        TranscriptSegment("we joined Bitfury in 2014", 3596.0, 3600.0),  # duplicate
        TranscriptSegment("and left in 2019", 3600.0, 3605.0),
    ]
    boundary = 3600.0
    merged = dedup_overlap_segments([chunk0, chunk1], [0.0, boundary], overlap_sec=5)

    texts = [s.text for s in merged]
    assert texts.count("we joined Bitfury in 2014") == 1
    assert "and left in 2019" in texts


# ── cache invalidation on transcriber change ──────────────────────────────────

def test_cache_invalidates_on_transcriber_change(tmp_path):
    conn = _make_conn()
    meta = _make_meta()

    # Seed cache with old transcriber
    _seed_cache(conn, "test123", "openai-whisper-1",
                [TranscriptSegment("old text", 0.0, 2.0)])

    new_transcriber = MagicMock()
    new_transcriber.name = "local-faster-whisper:large-v3-turbo"
    new_transcriber.transcribe.return_value = [
        TranscriptSegment("new text", 0.0, 2.0),
    ]

    fake_audio = tmp_path / "test123.opus"
    fake_audio.touch()
    from ir_storyboard.channels.llm_report.loaders.audio_chunker import AudioChunk
    fake_chunk = AudioChunk(path=fake_audio, chunk_start_sec=0.0, chunk_end_sec=1800.0)

    with patch("ir_storyboard.channels.llm_report.loaders.transcriber.fetch_audio", return_value=fake_audio), \
         patch("ir_storyboard.channels.llm_report.loaders.transcriber.split_audio", return_value=[fake_chunk]):
        result = get_or_transcribe("test123", meta, new_transcriber, conn, cache_dir=tmp_path)

    new_transcriber.transcribe.assert_called_once()
    assert result.segments[0].text == "new text"
    row = conn.execute("SELECT transcriber FROM youtube_transcripts WHERE video_id='test123'").fetchone()
    assert row["transcriber"] == "local-faster-whisper:large-v3-turbo"


# ── faster-whisper import error hint ─────────────────────────────────────────

def test_local_faster_whisper_import_error_hint():
    t = LocalFasterWhisperTranscriber()
    with patch.dict(sys.modules, {"faster_whisper": None}):
        with pytest.raises(RuntimeError, match="faster-whisper is not installed"):
            t.transcribe(Path("/fake/audio.opus"))
