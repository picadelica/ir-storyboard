"""Tests for LLM Report loaders (Task 1)."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "llm_report"
GONKA_DOCX = FIXTURES / "gonka_chatgpt_deep_research.docx"


# ─────────────────────────── docx loader ────────────────────────────────────

@pytest.mark.skipif(not GONKA_DOCX.exists(), reason="gonka fixture not found")
def test_docx_loader_on_gonka_fixture():
    from ir_storyboard.ingest.loaders.docx_loader import load

    ir = load(GONKA_DOCX)

    # Should detect sections
    assert len(ir.sections) >= 8, (
        f"Expected ≥8 sections, got {len(ir.sections)}: {[s.heading for s in ir.sections]}"
    )

    # Should have citations
    assert len(ir.citations) >= 1, "Expected at least 1 citation"

    # cite format should be bracket_n for ChatGPT Deep Research
    assert ir.detected_cite_format in ("bracket_n", "unknown"), ir.detected_cite_format

    # filename preserved
    assert ir.source_filename == GONKA_DOCX.name

    # No section should be None
    for s in ir.sections:
        assert s.heading, "Section has empty heading"
        assert isinstance(s.paragraphs, list)


def test_md_loader_basic_smoke(tmp_path):
    from ir_storyboard.ingest.loaders.md_loader import load

    md_content = textwrap.dedent("""\
        # Overview

        Gonka is a decentralized AI compute network [1].
        It uses Proof-of-Work 2.0 [2].

        # Technology & Product

        The Sprint consensus mechanism [1] enables 100% GPU utilization.

        # Sources

        [1] Crypto Briefing — Gonka Launch — https://cryptobriefing.com/gonka-launch/
        [2] BusinessWire — Bitfury Invests $50M — https://www.businesswire.com/news/home/20251201364475
    """)

    md_file = tmp_path / "test_report.md"
    md_file.write_text(md_content, encoding="utf-8")

    ir = load(md_file)

    assert len(ir.sections) == 2
    assert ir.sections[0].heading == "Overview"
    assert ir.sections[1].heading == "Technology & Product"

    # Should parse 2 citations
    assert len(ir.citations) == 2
    urls = {c.url for c in ir.citations}
    assert "https://cryptobriefing.com/gonka-launch/" in urls
    assert "https://www.businesswire.com/news/home/20251201364475" in urls

    assert ir.detected_cite_format == "bracket_n"


def test_md_loader_skips_conclusions(tmp_path):
    from ir_storyboard.ingest.loaders.md_loader import load

    md_content = textwrap.dedent("""\
        # Technology

        Some tech facts [1].

        # Conclusions

        This is the best project ever.

        # Sources

        [1] Example — https://example.com/article
    """)
    f = tmp_path / "report.md"
    f.write_text(md_content)
    ir = load(f)

    headings = [s.heading for s in ir.sections]
    assert "Technology" in headings
    assert "Conclusions" not in headings
    assert any("Skipped" in n for n in ir.parser_notes)


def test_md_loader_open_questions(tmp_path):
    from ir_storyboard.ingest.loaders.md_loader import load

    md_content = textwrap.dedent("""\
        # Technology

        Some tech [1].

        # Open Questions for Interview

        - What is the founder's personal motivation?
        - How did childhood shape the vision?

        # Sources

        [1] Title — https://example.com/
    """)
    f = tmp_path / "report.md"
    f.write_text(md_content)
    ir = load(f)

    assert len(ir.open_questions) == 2
    assert "founder" in ir.open_questions[0].lower()
