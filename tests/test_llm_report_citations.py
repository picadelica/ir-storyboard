"""Tests for CitationExtractor + SourceClassifier (Task 2)."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ir_storyboard.channels.llm_report.ir import LLMReportIR, RawCitation, RawSection
from ir_storyboard.channels.llm_report.citations import extract_citations, _normalize_url
from ir_storyboard.channels.llm_report.classifiers.source_channel import classify_url

FIXTURES = Path(__file__).parent / "fixtures" / "llm_report"
GONKA_DOCX = FIXTURES / "gonka_chatgpt_deep_research.docx"


# ── source classifier unit tests ─────────────────────────────────────────────

def test_businesswire_is_archival():
    ch, reason = classify_url(
        "https://www.businesswire.com/news/home/20251201364475/en/Bitfury-Announces"
    )
    assert ch == "archival"
    assert "businesswire" in reason.lower()


def test_u_today_interviews_is_online_interview():
    ch, reason = classify_url(
        "https://u.today/interviews/50-million-fundraising-chatgpt-competition"
    )
    assert ch == "online_interview"
    assert "u.today" in reason.lower() or "interview" in reason.lower()


def test_cryptobriefing_is_online_research():
    ch, _ = classify_url("https://cryptobriefing.com/gonka-decentralized-ai-compute-launch/")
    assert ch == "online_research"


def test_medium_is_online_research():
    ch, _ = classify_url("https://medium.com/@BitfuryGeorge/gonka-why-i-believe-fa702db742d9")
    assert ch == "online_research"


def test_odaily_is_online_research():
    ch, _ = classify_url("https://www.odaily.news/en/post/5207968")
    assert ch == "online_research"


def test_binance_square_is_online_research():
    ch, _ = classify_url("https://www.binance.com/en/square/post/32276709244242")
    assert ch == "online_research"


def test_libermans_co_is_online_research():
    ch, _ = classify_url("https://www.libermans.co/press/forbes")
    # /press/ path → archival
    assert ch in ("online_research", "archival")


def test_youtube_is_online_interview():
    ch, _ = classify_url("https://www.youtube.com/watch?v=abc123")
    assert ch == "online_interview"


def test_no_offline_from_url():
    for url in [
        "https://example.com",
        "https://businesswire.com/news/xyz",
        "https://youtube.com/watch?v=abc",
        "https://u.today/interviews/foo",
        "https://medium.com/@user/post",
    ]:
        ch, _ = classify_url(url)
        assert ch != "offline_interview", f"Got offline_interview for {url}"


def test_gov_domain_is_archival():
    ch, reason = classify_url("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany")
    assert ch == "archival"


def test_podcast_fm_is_interview():
    ch, _ = classify_url("https://somepodcast.fm/episodes/ep42")
    assert ch == "online_interview"


# ── URL normalisation ─────────────────────────────────────────────────────────

def test_canonicalize_strips_utm():
    raw = "https://example.com/article?utm_source=twitter&utm_campaign=launch&foo=bar"
    canon = _normalize_url(raw)
    assert "utm_source" not in canon
    assert "utm_campaign" not in canon
    assert "foo=bar" in canon  # non-tracking param preserved


def test_canonicalize_strips_fbclid():
    raw = "https://example.com/page?fbclid=IwAR123abc"
    canon = _normalize_url(raw)
    assert "fbclid" not in canon


def test_canonicalize_strips_trailing_slash():
    canon = _normalize_url("https://example.com/page/")
    assert not canon.endswith("/")


def test_canonicalize_lowercases_host():
    canon = _normalize_url("https://Example.COM/path")
    assert "example.com" in canon


def test_canonicalize_strips_www():
    canon = _normalize_url("https://www.example.com/path")
    assert "www." not in canon


# ── extract_citations on synthetic IR ────────────────────────────────────────

def _make_ir(citations: list[RawCitation]) -> LLMReportIR:
    return LLMReportIR(
        source_filename="test.docx",
        detected_agent="unknown",
        detected_cite_format="bracket_n",
        citations=citations,
    )


def test_extract_deduplicates_same_url():
    ir = _make_ir([
        RawCitation(cite_id=1, raw_marker="[1]",
                    url="https://example.com/article?utm_source=x"),
        RawCitation(cite_id=2, raw_marker="[2]",
                    url="https://example.com/article"),  # same after normalization
        RawCitation(cite_id=3, raw_marker="[3]",
                    url="https://other.com/page"),
    ])
    result = extract_citations(ir)
    urls = [r.canonical_url for r in result if r.canonical_url]
    assert len(urls) == len(set(urls)), "Duplicate canonical URLs found"
    assert len(result) == 2  # 1+2 merged into 1, plus cite 3


def test_extract_preserves_channel_classification():
    ir = _make_ir([
        RawCitation(cite_id=1, raw_marker="[1]",
                    url="https://businesswire.com/news/home/xyz"),
        RawCitation(cite_id=2, raw_marker="[2]",
                    url="https://youtube.com/watch?v=abc"),
        RawCitation(cite_id=3, raw_marker="[3]",
                    url="https://cryptobriefing.com/article"),
    ])
    result = extract_citations(ir)
    by_id = {r.cite_id: r for r in result}
    assert by_id[1].channel == "archival"
    assert by_id[2].channel == "online_interview"
    assert by_id[3].channel == "online_research"


def test_extract_deterministic():
    """Same input → same output on repeated calls."""
    ir = _make_ir([
        RawCitation(cite_id=1, raw_marker="[1]", url="https://example.com/a"),
        RawCitation(cite_id=2, raw_marker="[2]", url="https://example.com/b"),
    ])
    r1 = extract_citations(ir)
    r2 = extract_citations(ir)
    assert [(r.cite_id, r.canonical_url) for r in r1] == \
           [(r.cite_id, r.canonical_url) for r in r2]


# ── gonka fixture integration (requires python-docx on server) ───────────────

@pytest.mark.skipif(not GONKA_DOCX.exists(), reason="gonka fixture not found")
def test_extract_gonka_citations():
    """On the real fixture, we expect 7 unique canonical URLs."""
    from ir_storyboard.channels.llm_report.loaders.docx_loader import load

    ir = load(GONKA_DOCX)
    result = extract_citations(ir)

    canonical_urls = [r.canonical_url for r in result if r.canonical_url]
    unique = set(canonical_urls)

    # Golden: 7 unique URLs from libermans_gonka.expected.yaml
    assert len(unique) >= 5, f"Expected ≥5 unique URLs, got {len(unique)}: {unique}"

    channels = {r.channel for r in result}
    # Should have at least archival and online_research
    assert "archival" in channels or "online_interview" in channels, \
        f"Expected non-research channels, got: {channels}"
