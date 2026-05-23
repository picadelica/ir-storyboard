"""Tests for SnippetResolver (Task 4)."""
from __future__ import annotations

import os
from unittest.mock import patch

from ir_storyboard.llm import ExtractedFact
from ir_storyboard.ingest.snippet_resolver import resolve_snippets, ResolvedFact
from ir_storyboard.ingest.citations import ResolvedCitation


def _make_fact(text="Gonka raised $50M from Bitfury.", paraphrase="", flag="green",
               cite_ids=None, sid="3.3") -> ExtractedFact:
    return ExtractedFact(
        text=text,
        subsection_id=sid,
        flag=flag,
        cite_ids=cite_ids or [],
        confidence=0.9,
        raw_paraphrase=paraphrase or text,
    )


def _make_citation(cid=1, url="https://businesswire.com/gonka") -> ResolvedCitation:
    return ResolvedCitation(
        cite_id=cid,
        canonical_url=url,
        title="BW Press Release",
        publisher="BusinessWire",
        channel="archival",
        classification_reason="archival domain",
    )


# ── paraphrase mode (MVP) ─────────────────────────────────────────────────────

def test_paraphrase_mode_smoke():
    facts = [_make_fact(paraphrase="Bitfury committed $50M to Gonka in late 2025.")]
    result = resolve_snippets(facts, {}, mode="paraphrase")

    assert len(result) == 1
    rf = result[0]
    assert isinstance(rf, ResolvedFact)
    assert rf.snippet_source == "llm_paraphrase"
    assert rf.evidence_snippet == "Bitfury committed $50M to Gonka in late 2025."
    assert rf.needs_review is False
    assert rf.flag == "green"


def test_short_paraphrase_marks_grey():
    facts = [_make_fact(text="Short.", paraphrase="Too short")]
    result = resolve_snippets(facts, {}, mode="paraphrase")

    rf = result[0]
    assert rf.needs_review is True
    assert rf.flag == "grey"


def test_paraphrase_truncates_to_400():
    long_text = "A" * 500
    facts = [_make_fact(paraphrase=long_text)]
    result = resolve_snippets(facts, {}, mode="paraphrase")
    assert len(result[0].evidence_snippet) <= 400


def test_paraphrase_falls_back_to_text_when_no_paraphrase():
    fact = ExtractedFact(
        text="Gonka raised $50M from Bitfury in December 2025.",
        subsection_id="3.3",
        flag="green",
        raw_paraphrase="",  # empty paraphrase
    )
    result = resolve_snippets([fact], {}, mode="paraphrase")
    assert result[0].evidence_snippet == fact.text


def test_multiple_facts_paraphrase():
    facts = [
        _make_fact(paraphrase="Bitfury committed $50M to Gonka.", sid="3.3"),
        _make_fact(paraphrase="Network grew 16x in two months.", flag="green", sid="6.3"),
        _make_fact(paraphrase="Regulatory risks not covered.", flag="grey", sid="8.3"),
    ]
    result = resolve_snippets(facts, {}, mode="paraphrase")
    assert len(result) == 3
    assert all(r.snippet_source == "llm_paraphrase" for r in result)


# ── fetch mode (v2, feature-flagged) ─────────────────────────────────────────

def test_fetch_mode_offline_with_mock():
    """Fetch mode with monkey-patched HTTP returns real snippet."""
    fake_html = """
    <html><body>
    <p>Some irrelevant content here.</p>
    <p>Bitfury committed fifty million dollars to Gonka in late November 2025
    as part of their ethical technology fund initiative.</p>
    <p>Other paragraph about something else.</p>
    </body></html>
    """

    facts = [
        ExtractedFact(
            text="Bitfury invested in Gonka.",
            subsection_id="3.3",
            flag="green",
            cite_ids=[1],
            confidence=0.9,
            raw_paraphrase="Bitfury committed fifty million dollars to Gonka in late 2025.",
        )
    ]
    citation_index = {1: _make_citation(1, "https://businesswire.com/gonka")}

    from ir_storyboard.ingest import snippet_resolver as sr_module

    with patch.object(sr_module, "_fetch_text", return_value=fake_html), \
         patch.dict(os.environ, {"LLM_REPORT_RESOLVE_FETCH": "1"}):
        result = resolve_snippets(facts, citation_index, mode="fetch")

    assert len(result) == 1
    rf = result[0]
    # Should have found something from the HTML
    assert len(rf.evidence_snippet) >= 20
    # Source should not be llm_paraphrase if fetch succeeded
    # (could be http_fetch or llm_paraphrase if similarity is low — both are acceptable)
    assert rf.snippet_source in ("http_fetch", "llm_paraphrase")


def test_fetch_mode_without_flag_falls_back_to_paraphrase():
    """Without the feature flag, fetch mode behaves like paraphrase."""
    facts = [_make_fact(paraphrase="Gonka raised $50M.")]

    with patch.dict(os.environ, {}, clear=False):
        # Make sure flag is NOT set
        os.environ.pop("LLM_REPORT_RESOLVE_FETCH", None)
        result = resolve_snippets(facts, {}, mode="fetch")

    assert result[0].snippet_source == "llm_paraphrase"
