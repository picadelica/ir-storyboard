"""CitationExtractor: LLMReportIR → list[ResolvedCitation].

Deterministic — no LLM calls. Takes raw citations from the IR,
canonicalises URLs, deduplicates, classifies to channel.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from .ir import LLMReportIR, RawCitation
from .classifiers.source_channel import classify_url

# UTM / tracking params to strip
_TRACKING_PARAMS = frozenset([
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "fbclid", "gclid", "msclkid", "twclid",
    "ref", "referrer", "source", "mc_cid", "mc_eid",
])

# Publisher display name overrides for well-known hosts
_PUBLISHER_MAP: dict[str, str] = {
    "businesswire.com": "BusinessWire",
    "prnewswire.com": "PR Newswire",
    "globenewswire.com": "GlobeNewswire",
    "sec.gov": "SEC EDGAR",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "medium.com": "Medium",
    "u.today": "U.Today",
    "odaily.news": "Odaily",
    "cryptobriefing.com": "Crypto Briefing",
    "binance.com": "Binance Square",
    "libermans.co": "Libermans Co.",
    "twitter.com": "Twitter/X",
    "x.com": "Twitter/X",
    "linkedin.com": "LinkedIn",
    "techcrunch.com": "TechCrunch",
    "coindesk.com": "CoinDesk",
    "cointelegraph.com": "CoinTelegraph",
    "decrypt.co": "Decrypt",
    "theblock.co": "The Block",
    "forbes.com": "Forbes",
    "bloomberg.com": "Bloomberg",
    "wsj.com": "Wall Street Journal",
    "nytimes.com": "New York Times",
}


@dataclass
class ResolvedCitation:
    cite_id: int
    canonical_url: str
    title: str
    publisher: str
    channel: Literal["online_research", "online_interview", "archival", "offline_interview"]
    classification_reason: str


def _normalize_url(url: str) -> str:
    """Canonicalize URL: lowercase host, strip trailing slash, remove tracking params."""
    if not url:
        return ""
    try:
        p = urlparse(url)
        host = p.netloc.lower().lstrip("www.")
        # Strip tracking query params
        qs = parse_qs(p.query, keep_blank_values=True)
        clean_qs = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
        new_query = urlencode(clean_qs, doseq=True)
        # Rebuild without fragment, with cleaned query
        canonical = urlunparse((
            p.scheme.lower(),
            host,
            p.path.rstrip("/"),
            p.params,
            new_query,
            "",  # drop fragment
        ))
        return canonical
    except Exception:
        return url.lower().rstrip("/")


def _publisher_from_url(url: str) -> str:
    """Derive a human-readable publisher name from a URL."""
    if not url:
        return ""
    try:
        host = urlparse(url).netloc.lower().lstrip("www.")
        # Check exact map
        if host in _PUBLISHER_MAP:
            return _PUBLISHER_MAP[host]
        # medium.com/@handle → Medium / handle
        if host == "medium.com":
            m = re.search(r"/@([^/]+)", url)
            if m:
                return f"Medium / {m.group(1)}"
        # Strip common subdomains
        parts = host.split(".")
        if len(parts) >= 2:
            domain = ".".join(parts[-2:])
            if domain in _PUBLISHER_MAP:
                return _PUBLISHER_MAP[domain]
        return host
    except Exception:
        return ""


def extract_citations(ir: LLMReportIR) -> list[ResolvedCitation]:
    """Convert raw IR citations → resolved, deduplicated, classified citations.

    Deterministic: same input always produces same output.
    """
    # Group raw citations by canonical URL; keep the one with the lowest cite_id
    url_to_raw: dict[str, RawCitation] = {}

    for raw in ir.citations:
        canon = _normalize_url(raw.url)
        if not canon:
            # No URL — keep as standalone entry with empty canonical
            key = f"__no_url_{raw.cite_id}"
            url_to_raw[key] = raw
            continue
        if canon not in url_to_raw:
            url_to_raw[canon] = raw
        # else: duplicate URL — keep first (lowest cite_id by iteration order)

    result: list[ResolvedCitation] = []
    for canon, raw in url_to_raw.items():
        channel, reason = classify_url(raw.url)
        publisher = _publisher_from_url(raw.url) or raw.publisher
        result.append(ResolvedCitation(
            cite_id=raw.cite_id,
            canonical_url=canon if not canon.startswith("__no_url_") else "",
            title=raw.title,
            publisher=publisher,
            channel=channel,  # type: ignore[arg-type]
            classification_reason=reason,
        ))

    # Sort by original cite_id for stable output
    result.sort(key=lambda c: c.cite_id)
    return result
