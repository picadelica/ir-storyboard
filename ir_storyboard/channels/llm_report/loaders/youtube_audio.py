"""Download YouTube audio as opus 16kHz mono via yt-dlp."""
from __future__ import annotations

import os
from pathlib import Path


def fetch_audio(video_id: str, cache_dir: Path) -> Path:
    """Download audio for video_id to cache_dir as <video_id>.opus.

    Uses yt-dlp with bestaudio + FFmpegExtractAudio → opus 16kHz mono.
    If the file already exists in cache_dir, skips download and returns path.

    Returns the path to the cached .opus file.
    """
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError(
            "yt-dlp is not installed. Run: pip install yt-dlp"
        )

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{video_id}.opus"

    if out_path.exists():
        return out_path

    canonical_url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        "format": "bestaudio",
        "outtmpl": str(cache_dir / f"{video_id}.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "opus",
                "preferredquality": "64",
            }
        ],
        "postprocessor_args": ["-ac", "1", "-ar", "16000"],
        "quiet": True,
        "no_warnings": True,
        "ratelimit": 1_000_000,       # 1 MB/s — polite
        "retries": 3,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([canonical_url])
        except Exception as e:
            raise RuntimeError(f"yt-dlp audio download failed for {video_id}: {e}") from e

    if not out_path.exists():
        # yt-dlp may have picked a different extension; find it
        candidates = list(cache_dir.glob(f"{video_id}.*"))
        if candidates:
            return candidates[0]
        raise RuntimeError(f"Audio file not found after download for {video_id}")

    return out_path
