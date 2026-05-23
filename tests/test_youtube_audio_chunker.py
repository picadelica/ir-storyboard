"""Tests for audio_chunker.py."""
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import pytest

from ir_storyboard.ingest.loaders.audio_chunker import (
    split_audio,
    AudioChunk,
    _probe_duration,
)


def _mock_probe(duration_sec: float):
    """Patch _probe_duration to return a fixed value."""
    return patch(
        "ir_storyboard.ingest.loaders.audio_chunker._probe_duration",
        return_value=float(duration_sec),
    )


def _mock_ffmpeg_ok():
    """Patch subprocess.run for ffmpeg to succeed without actually running."""
    mock = MagicMock(return_value=MagicMock(returncode=0))
    return patch("subprocess.run", mock)


# ── single chunk (under max) ─────────────────────────────────────────────────

def test_split_under_max_returns_one_chunk(tmp_path):
    audio = tmp_path / "test.opus"
    audio.touch()
    with _mock_probe(1800.0):  # 30 min
        chunks = split_audio(audio, max_chunk_sec=3600, overlap_sec=5)

    assert len(chunks) == 1
    assert chunks[0].path == audio
    assert chunks[0].chunk_start_sec == 0.0
    assert chunks[0].chunk_end_sec == 1800.0


def test_split_equal_to_max_returns_one_chunk(tmp_path):
    audio = tmp_path / "test.opus"
    audio.touch()
    with _mock_probe(3600.0):
        chunks = split_audio(audio, max_chunk_sec=3600, overlap_sec=5)

    assert len(chunks) == 1
    assert chunks[0].chunk_start_sec == 0.0


# ── 2-hour video → 2 chunks ──────────────────────────────────────────────────

def test_split_2h_video_with_default_settings(tmp_path):
    audio = tmp_path / "long.opus"
    audio.touch()

    captured_calls = []

    def fake_run(cmd, **kwargs):
        captured_calls.append(cmd)
        # Create the output file so split_audio doesn't error
        out = Path(cmd[-1])
        out.touch()
        return MagicMock(returncode=0)

    with _mock_probe(7200.0), patch("subprocess.run", fake_run):
        chunks = split_audio(audio, max_chunk_sec=3600, overlap_sec=5, chunk_dir=tmp_path / "chunks")

    assert len(chunks) == 2
    assert chunks[0].chunk_start_sec == 0.0
    assert chunks[0].chunk_end_sec == 3600.0
    assert chunks[1].chunk_start_sec == 3600.0
    assert chunks[1].chunk_end_sec == 7200.0


# ── overlap goes forward ──────────────────────────────────────────────────────

def test_split_uses_overlap(tmp_path):
    """chunk[0] slice length = max_chunk + overlap; chunk[1].chunk_start_sec not shifted back."""
    audio = tmp_path / "med.opus"
    audio.touch()

    ffmpeg_calls = []

    def fake_run(cmd, **kwargs):
        ffmpeg_calls.append(cmd)
        Path(cmd[-1]).touch()
        return MagicMock(returncode=0)

    with _mock_probe(5000.0), patch("subprocess.run", fake_run):
        chunks = split_audio(audio, max_chunk_sec=3600, overlap_sec=5, chunk_dir=tmp_path / "chunks")

    assert len(chunks) == 2
    # chunk[1] starts at the nominal boundary, not shifted back by overlap_sec
    assert chunks[1].chunk_start_sec == 3600.0

    # First ffmpeg call: -t should be 3600+5 = 3605
    first_cmd = ffmpeg_calls[0]
    t_idx = first_cmd.index("-t")
    assert float(first_cmd[t_idx + 1]) == pytest.approx(3605.0, abs=1.0)


# ── ffmpeg args ───────────────────────────────────────────────────────────────

def test_split_invokes_ffmpeg_correctly(tmp_path):
    """Verify ffmpeg is called with -ss, -t, -c copy for each chunk."""
    audio = tmp_path / "vid.opus"
    audio.touch()

    ffmpeg_calls = []

    def fake_run(cmd, **kwargs):
        ffmpeg_calls.append(cmd)
        Path(cmd[-1]).touch()
        return MagicMock(returncode=0)

    # 4000s → 2 chunks; check structure of first call
    with _mock_probe(4000.0), patch("subprocess.run", fake_run):
        split_audio(audio, max_chunk_sec=3600, overlap_sec=5, chunk_dir=tmp_path / "chunks")

    assert len(ffmpeg_calls) >= 1
    cmd = ffmpeg_calls[0]   # first chunk
    assert "ffmpeg" in cmd[0]
    assert "-ss" in cmd
    assert "-t" in cmd
    assert "-c" in cmd
    c_idx = cmd.index("-c")
    assert cmd[c_idx + 1] == "copy"
    ss_idx = cmd.index("-ss")
    assert float(cmd[ss_idx + 1]) == pytest.approx(0.0)
    # Second call starts at 3600
    cmd2 = ffmpeg_calls[1]
    ss_idx2 = cmd2.index("-ss")
    assert float(cmd2[ss_idx2 + 1]) == pytest.approx(3600.0)
