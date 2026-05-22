"""Split audio into time-limited chunks via ffmpeg for Whisper transcription."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AudioChunk:
    path: Path
    chunk_start_sec: float   # offset in the original file this chunk starts at
    chunk_end_sec: float     # nominal end (without overlap extension)


def _probe_duration(audio_path: Path) -> float:
    """Return audio duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def split_audio(
    audio_path: Path,
    max_chunk_sec: int | None = None,
    overlap_sec: int | None = None,
    chunk_dir: Path | None = None,
) -> list[AudioChunk]:
    """Split audio into chunks of at most max_chunk_sec seconds.

    If duration <= max_chunk_sec, returns a single AudioChunk with the
    original path (no ffmpeg call).

    overlap_sec: each chunk extends overlap_sec beyond its nominal end so
    that boundary words are not cut mid-sentence. The *next* chunk's
    chunk_start_sec is NOT shifted back — overlap goes forward only.

    Env overrides: MAX_CHUNK_SEC, CHUNK_OVERLAP_SEC.
    """
    if max_chunk_sec is None:
        max_chunk_sec = int(os.environ.get("MAX_CHUNK_SEC", "1200"))
    if overlap_sec is None:
        overlap_sec = int(os.environ.get("CHUNK_OVERLAP_SEC", "5"))

    duration = _probe_duration(audio_path)

    if duration <= max_chunk_sec:
        return [AudioChunk(path=audio_path, chunk_start_sec=0.0, chunk_end_sec=duration)]

    if chunk_dir is None:
        chunk_dir = audio_path.parent / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    chunks: list[AudioChunk] = []
    start = 0.0
    idx = 0
    while start < duration:
        end = min(start + max_chunk_sec, duration)
        chunk_path = chunk_dir / f"{audio_path.stem}_chunk{idx:03d}{audio_path.suffix}"

        # Actual slice length: nominal + overlap (clamped to file end)
        slice_len = min(end - start + overlap_sec, duration - start)

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(audio_path),
                "-ss", str(start),
                "-t", str(slice_len),
                "-c", "copy",
                str(chunk_path),
            ],
            capture_output=True,
            check=True,
        )

        chunks.append(AudioChunk(path=chunk_path, chunk_start_sec=start, chunk_end_sec=end))

        if end >= duration:
            break
        start = end   # next chunk starts at nominal end (overlap goes forward)
        idx += 1

    return chunks
