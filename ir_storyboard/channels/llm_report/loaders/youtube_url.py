"""YouTube URL normalization + metadata fetching via yt-dlp."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from typing import Optional


@dataclass
class YouTubeVideoMeta:
    video_id: str
    canonical_url: str
    title: str
    channel_name: str
    channel_url: str
    duration_sec: int
    upload_date: str        # 'YYYY-MM-DD'
    description: str
    language: Optional[str]


_YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "youtu.be", "www.youtu.be",
}

# Query params that survive normalization (only v= matters for dedup)
_KEEP_PARAMS = frozenset(["v"])

# Params stripped from the canonical watch URL
_STRIP_PARAMS = frozenset(["t", "list", "index", "pp", "si", "feature", "start_radio"])


def _extract_video_id(parsed) -> Optional[str]:
    """Pull video_id from a parsed YouTube URL. Returns None if not found."""
    host = parsed.netloc.lower().lstrip("www.").lstrip("m.")
    path = parsed.path.rstrip("/")

    if host == "youtu.be":
        # https://youtu.be/VID
        vid = path.lstrip("/")
        return vid if vid else None

    if host in ("youtube.com",):
        if path.startswith("/watch"):
            qs = parse_qs(parsed.query)
            vid = qs.get("v", [None])[0]
            return vid

        for prefix in ("/shorts/", "/live/", "/embed/", "/v/"):
            if path.startswith(prefix):
                vid = path[len(prefix):].split("/")[0].split("?")[0]
                return vid if vid else None

    return None


def _resolve_shortlink(raw_url: str) -> str:
    """Follow HTTP redirects until we reach a non-shortlink URL."""
    try:
        import requests
        resp = requests.head(raw_url, allow_redirects=True, timeout=10,
                             headers={"User-Agent": "ir-storyboard/2.0"})
        return resp.url
    except Exception:
        return raw_url


def normalize_url(raw_url: str) -> str:
    """Normalize any YouTube URL variant to canonical https://www.youtube.com/watch?v=VID.

    Strips t=, list=, pp=, si= and other tracking/session params.
    Short-links (t.co, bit.ly, lnkd.in) are followed via HEAD redirect.
    Raises ValueError if the result is not a YouTube URL.
    """
    url = raw_url.strip()
    parsed = urlparse(url)

    host = parsed.netloc.lower().lstrip("www.").lstrip("m.")

    # Resolve short-links that are not YouTube domains
    if host and host not in _YOUTUBE_HOSTS:
        url = _resolve_shortlink(url)
        parsed = urlparse(url)
        host = parsed.netloc.lower().lstrip("www.").lstrip("m.")

    if host not in _YOUTUBE_HOSTS:
        raise ValueError(f"Not a YouTube URL: {raw_url}")

    video_id = _extract_video_id(parsed)
    if not video_id:
        raise ValueError(f"Could not extract video_id from: {raw_url}")

    canonical = f"https://www.youtube.com/watch?v={video_id}"
    return canonical


def fetch_metadata(canonical_url: str) -> YouTubeVideoMeta:
    """Fetch video metadata using yt-dlp (no audio download).

    Raises RuntimeError if yt-dlp is not installed or fetch fails.
    """
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "yt-dlp is not installed. Run: pip install yt-dlp"
        )

    parsed = urlparse(canonical_url)
    qs = parse_qs(parsed.query)
    video_id = qs.get("v", [None])[0]
    if not video_id:
        raise ValueError(f"No video_id in canonical URL: {canonical_url}")

    import yt_dlp

    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(canonical_url, download=False)
        except Exception as e:
            raise RuntimeError(f"yt-dlp failed to fetch metadata: {e}") from e

    if info is None:
        raise RuntimeError(f"yt-dlp returned no info for {canonical_url}")

    upload_date_raw = info.get("upload_date") or ""
    if len(upload_date_raw) == 8:
        upload_date = f"{upload_date_raw[:4]}-{upload_date_raw[4:6]}-{upload_date_raw[6:]}"
    else:
        upload_date = upload_date_raw

    return YouTubeVideoMeta(
        video_id=video_id,
        canonical_url=canonical_url,
        title=info.get("title") or "",
        channel_name=info.get("uploader") or info.get("channel") or "",
        channel_url=info.get("uploader_url") or info.get("channel_url") or "",
        duration_sec=int(info.get("duration") or 0),
        upload_date=upload_date,
        description=(info.get("description") or "")[:2000],
        language=info.get("language"),
    )
