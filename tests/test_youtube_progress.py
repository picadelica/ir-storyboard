"""run_youtube_preview must emit human-readable progress stages via progress_cb so
the UI can show a real status bar (метаданные → аудио → транскрибирование чанков →
извлечение фактов). Earlier the YouTube job ran with no progress_cb, so the bar was
always blank. Everything external (yt-dlp, ffmpeg, whisper, LLM) is mocked."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_audio_ingest import MockTranscriber, _mock_extracted_facts, _make_conn


def _meta():
    from ir_storyboard.ingest.loaders.youtube_url import YouTubeVideoMeta
    return YouTubeVideoMeta(
        video_id="abc123", canonical_url="https://www.youtube.com/watch?v=abc123",
        title="Founder interview", channel_name="Some Pod", channel_url="",
        duration_sec=65, upload_date="2026-01-01", description="", language="en",
    )


def _yt_patches(stack, transcriber):
    from ir_storyboard.ingest.loaders.audio_chunker import AudioChunk
    stack.enter_context(patch(
        "ir_storyboard.ingest.youtube_pipeline.fetch_metadata", return_value=_meta()))
    stack.enter_context(patch(
        "ir_storyboard.ingest.youtube_pipeline.get_transcriber", return_value=transcriber))
    stack.enter_context(patch(
        "ir_storyboard.ingest.loaders.transcriber.fetch_audio",
        side_effect=lambda vid, cache_dir: Path(cache_dir) / f"{vid}.opus"))
    stack.enter_context(patch(
        "ir_storyboard.ingest.loaders.transcriber.split_audio",
        side_effect=lambda p, **kw: [AudioChunk(path=p, chunk_start_sec=0.0, chunk_end_sec=65.0)]))
    stack.enter_context(patch(
        "ir_storyboard.ingest.youtube_pipeline.extract_facts_from_transcript",
        return_value=(_mock_extracted_facts(), [])))
    stack.enter_context(patch(
        "ir_storyboard.ingest.youtube_pipeline.summarize_youtube_preview",
        return_value={"video_brief": "", "cell_briefs": {}}))


def test_preview_emits_progress_stages(tmp_path):
    from ir_storyboard.ingest.youtube_pipeline import run_youtube_preview

    conn = _make_conn(tmp_path)
    stages: list[str] = []
    with ExitStack() as stack:
        _yt_patches(stack, MockTranscriber())
        run_youtube_preview("test_founder", "https://youtu.be/abc123", conn,
                            cache_dir=tmp_path, progress_cb=stages.append)

    joined = " | ".join(stages)
    assert any("метаданные" in s for s in stages), joined
    assert any("аудио" in s for s in stages), joined          # download
    assert any("чанк" in s for s in stages), joined           # per-chunk transcription
    assert any("факт" in s for s in stages), joined           # LLM extraction


def test_committed_at_pending_until_commit(tmp_path):
    """A fresh preview is PENDING (committed_at NULL) so a history reopen stays
    editable; committing sets committed_at. Guards the bug where confirmed_at
    (NOT NULL DEFAULT CURRENT_TIMESTAMP) made every preview look committed →
    reopen was always read-only."""
    from ir_storyboard.ingest.youtube_pipeline import run_youtube_preview, run_youtube_commit

    conn = _make_conn(tmp_path)
    with ExitStack() as stack:
        _yt_patches(stack, MockTranscriber())
        result = run_youtube_preview("test_founder", "https://youtu.be/abc123", conn,
                                     cache_dir=tmp_path)
        pid = result.preview_id

        row = conn.execute("SELECT committed_at FROM ingest_audit WHERE id=?", (pid,)).fetchone()
        assert row["committed_at"] is None, "preview must be pending (committed_at NULL)"

        run_youtube_commit(preview_id=pid, accepted_fact_ids=list(range(len(result.facts))),
                           overrides=[], conn=conn, expert_email="a@b.com")
        row2 = conn.execute("SELECT committed_at FROM ingest_audit WHERE id=?", (pid,)).fetchone()
        assert row2["committed_at"] is not None, "commit must set committed_at"


def test_cache_hit_reports_cached_stage(tmp_path):
    from ir_storyboard.ingest.youtube_pipeline import run_youtube_preview

    conn = _make_conn(tmp_path)
    with ExitStack() as stack:
        _yt_patches(stack, MockTranscriber())
        # first run populates the transcript cache
        run_youtube_preview("test_founder", "https://youtu.be/abc123", conn,
                            cache_dir=tmp_path)
        # second run should hit cache and say so
        stages: list[str] = []
        run_youtube_preview("test_founder", "https://youtu.be/abc123", conn,
                            cache_dir=tmp_path, progress_cb=stages.append)

    assert any("кэше" in s for s in stages), " | ".join(stages)
