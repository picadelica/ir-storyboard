"""URL → canonical channel classifier.

Priority order (highest first):
  1. archival   — press release domains, .gov, web.archive.org, /press /newsroom paths
  2. online_interview — YouTube, podcasts, *.fm, interview paths
  3. online_research — everything else on the web
  4. offline_interview — NEVER from a URL (that would be a bug)
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# ── archival domains / patterns ──────────────────────────────────────────────

_ARCHIVAL_DOMAINS = frozenset([
    "businesswire.com",
    "prnewswire.com",
    "globenewswire.com",
    "sec.gov",
    "edgar.sec.gov",
    "web.archive.org",
    "archive.org",
])

_ARCHIVAL_TLD = frozenset([".gov", ".gc.ca", ".europa.eu"])

_ARCHIVAL_PATH_RE = re.compile(
    r"/(press|newsroom|press-release|press_release|investor-relations|ir/|news/home)/",
    re.I,
)

# ── online_interview domains / patterns ─────────────────────────────────────

_INTERVIEW_DOMAINS = frozenset([
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "spotify.com",
    "anchor.fm",
    "soundcloud.com",
    "transistor.fm",
    "simplecast.com",
    "buzzsprout.com",
    "podbean.com",
    "podomatic.com",
    "stitcher.com",
    "iheart.com",
    "overcast.fm",
    "castbox.fm",
    "podcastaddict.com",
])

_INTERVIEW_HOST_RE = re.compile(r"\.(fm|podcast\.[a-z]{2,6})$", re.I)

_INTERVIEW_PATH_RE = re.compile(
    r"/(interview|interviews|podcast|podcasts|q-a|qanda|talk|talks|episode|episodes)/",
    re.I,
)

_SPOTIFY_EPISODE_RE = re.compile(r"/episode/", re.I)


def classify_url(url: str) -> tuple[str, str]:
    """Return (channel, reason) for a given URL.

    channel is one of: 'online_research', 'online_interview', 'archival'
    Never returns 'offline_interview' — that would be a bug.
    """
    if not url or not url.startswith(("http://", "https://")):
        return "online_research", "no valid URL — defaulting to online_research"

    parsed = urlparse(url.lower())
    host = parsed.netloc.lstrip("www.")
    path = parsed.path

    # ── 1. archival ──────────────────────────────────────────────────────────

    if host in _ARCHIVAL_DOMAINS:
        return "archival", f"archival domain: {host}"

    for tld in _ARCHIVAL_TLD:
        if host.endswith(tld):
            return "archival", f"government/official TLD: {tld}"

    if _ARCHIVAL_PATH_RE.search(path):
        return "archival", f"press/newsroom path in: {host}"

    # ── 2. online_interview ──────────────────────────────────────────────────

    if host in _INTERVIEW_DOMAINS:
        if host == "spotify.com" and _SPOTIFY_EPISODE_RE.search(path):
            return "online_interview", "Spotify episode"
        elif host == "spotify.com":
            return "online_research", "Spotify non-episode page"
        return "online_interview", f"known interview/podcast host: {host}"

    if _INTERVIEW_HOST_RE.search(host):
        return "online_interview", f"podcast TLD pattern: {host}"

    if _INTERVIEW_PATH_RE.search(path):
        return "online_interview", f"interview/podcast path: {path}"

    # u.today has a dedicated interviews subdirectory
    if host == "u.today" and "/interviews/" in path:
        return "online_interview", "u.today interviews section"

    # ── 3. online_research (default) ─────────────────────────────────────────

    return "online_research", f"web source: {host}"
