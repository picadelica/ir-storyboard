"""Tests for youtube_url.py — URL normalization + metadata fetch."""
import pytest
from unittest.mock import patch, MagicMock

from ir_storyboard.channels.llm_report.loaders.youtube_url import (
    normalize_url,
    fetch_metadata,
    YouTubeVideoMeta,
)


# ── normalize_url ─────────────────────────────────────────────────────────────

def test_normalize_watch_url():
    assert normalize_url("https://www.youtube.com/watch?v=abc123XYZ") == \
        "https://www.youtube.com/watch?v=abc123XYZ"


def test_normalize_short_youtu_be():
    assert normalize_url("https://youtu.be/abc123XYZ") == \
        "https://www.youtube.com/watch?v=abc123XYZ"


def test_normalize_shorts():
    assert normalize_url("https://www.youtube.com/shorts/abc123XYZ") == \
        "https://www.youtube.com/watch?v=abc123XYZ"


def test_normalize_live():
    assert normalize_url("https://www.youtube.com/live/abc123XYZ") == \
        "https://www.youtube.com/watch?v=abc123XYZ"


def test_normalize_mobile():
    assert normalize_url("https://m.youtube.com/watch?v=abc123XYZ") == \
        "https://www.youtube.com/watch?v=abc123XYZ"


def test_normalize_strips_query_params():
    url = "https://www.youtube.com/watch?v=abc123XYZ&t=120&list=PL123&si=xxx&pp=foo"
    assert normalize_url(url) == "https://www.youtube.com/watch?v=abc123XYZ"


def test_normalize_rejects_non_youtube():
    with pytest.raises(ValueError, match="Not a YouTube URL"):
        normalize_url("https://example.com/foo")


def test_normalize_tco_shortlink():
    fake_final = "https://www.youtube.com/watch?v=abc123XYZ"
    with patch(
        "ir_storyboard.channels.llm_report.loaders.youtube_url._resolve_shortlink",
        return_value=fake_final,
    ):
        result = normalize_url("https://t.co/SomeShortCode")
    assert result == "https://www.youtube.com/watch?v=abc123XYZ"


def test_normalize_bitly_shortlink():
    fake_final = "https://youtu.be/abc123XYZ"
    with patch(
        "ir_storyboard.channels.llm_report.loaders.youtube_url._resolve_shortlink",
        return_value=fake_final,
    ):
        result = normalize_url("https://bit.ly/SomeCode")
    assert result == "https://www.youtube.com/watch?v=abc123XYZ"


# ── fetch_metadata ────────────────────────────────────────────────────────────

def _make_yt_info(**overrides):
    base = {
        "id": "abc123XYZ",
        "title": "Test Video Title",
        "uploader": "Test Channel",
        "uploader_url": "https://www.youtube.com/@TestChannel",
        "channel_url": "https://www.youtube.com/channel/UC123",
        "duration": 3723,
        "upload_date": "20260115",
        "description": "A test description.",
        "language": "en",
    }
    base.update(overrides)
    return base


def _mock_yt_dlp(fake_info: dict):
    """Context manager: inject a fake yt_dlp module with controllable extract_info."""
    import sys
    mock_ydl_instance = MagicMock()
    mock_ydl_instance.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_instance.__exit__ = MagicMock(return_value=False)
    mock_ydl_instance.extract_info = MagicMock(return_value=fake_info)

    mock_yt_dlp_module = MagicMock()
    mock_yt_dlp_module.YoutubeDL = MagicMock(return_value=mock_ydl_instance)

    return patch.dict(sys.modules, {"yt_dlp": mock_yt_dlp_module})


def test_fetch_metadata_stub():
    """fetch_metadata correctly maps yt-dlp info dict to YouTubeVideoMeta."""
    import importlib
    import ir_storyboard.channels.llm_report.loaders.youtube_url as mod

    canonical = "https://www.youtube.com/watch?v=abc123XYZ"
    fake_info = _make_yt_info()

    with _mock_yt_dlp(fake_info):
        importlib.reload(mod)
        from ir_storyboard.channels.llm_report.loaders.youtube_url import fetch_metadata as fm
        meta = fm(canonical)

    assert meta.video_id == "abc123XYZ"
    assert meta.canonical_url == canonical
    assert meta.title == "Test Video Title"
    assert meta.channel_name == "Test Channel"
    assert meta.duration_sec == 3723
    assert meta.upload_date == "2026-01-15"
    assert meta.language == "en"


def test_fetch_metadata_upload_date_formatted():
    """upload_date '20260521' → '2026-05-21'."""
    import importlib
    import ir_storyboard.channels.llm_report.loaders.youtube_url as mod

    canonical = "https://www.youtube.com/watch?v=abc123XYZ"
    fake_info = _make_yt_info(upload_date="20260521")

    with _mock_yt_dlp(fake_info):
        importlib.reload(mod)
        from ir_storyboard.channels.llm_report.loaders.youtube_url import fetch_metadata as fm
        meta = fm(canonical)

    assert meta.upload_date == "2026-05-21"


def test_fetch_metadata_no_yt_dlp_raises():
    """If yt-dlp not installed, RuntimeError with install hint."""
    import sys
    canonical = "https://www.youtube.com/watch?v=abc123XYZ"
    with patch.dict(sys.modules, {"yt_dlp": None}):
        with pytest.raises(RuntimeError, match="yt-dlp is not installed"):
            fetch_metadata(canonical)
