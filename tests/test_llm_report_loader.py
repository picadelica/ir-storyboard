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


@pytest.mark.parametrize("sources_header", [
    "## Источники",          # markdown-заголовок (эталон)
    "**Источники:**",        # жирным — частый вывод Claude
    "__Sources__",           # жирным (underscore)
    "Источники:",            # просто строкой с двоеточием
    "#### Sources",          # 4 решётки (markdown до 6)
    "###### References",     # 6 решёток
])
def test_md_loader_lenient_sources_header(tmp_path, sources_header):
    """Секция источников распознаётся не только markdown-заголовком `##`, но и когда LLM
    отдал её жирным (`**Sources**`), строкой с двоеточием (`Sources:`) или 4-6 решётками —
    URL из `[N] … URL` парсятся во всех случаях (робастность к формату вывода LLM)."""
    from ir_storyboard.ingest.loaders.md_loader import load

    md = textwrap.dedent(f"""\
        ## Founder
        Запустил стартап в 2021 [1]. Раунд A на $5M [2].

        {sources_header}
        [1] TechCrunch — Launch — https://techcrunch.com/a
        [2] Forbes — Series A — https://forbes.com/b
        """)
    f = tmp_path / "report.md"
    f.write_text(md, encoding="utf-8")
    ir = load(f)

    assert len(ir.citations) == 2
    urls = {c.url for c in ir.citations}
    assert urls == {"https://techcrunch.com/a", "https://forbes.com/b"}


def test_md_loader_bold_label_in_body_not_a_source_section(tmp_path):
    """Ложное срабатывание: жирный ярлык в теле (не «источники/sources/…») режим НЕ
    переключает — остаётся контентом."""
    from ir_storyboard.ingest.loaders.md_loader import load

    md = textwrap.dedent("""\
        ## Founder
        **Ключевые факты:**
        Запустил в 2021 [1] https://tc.com/a

        ## Sources
        [1] TechCrunch — https://tc.com/a
        """)
    f = tmp_path / "report.md"
    f.write_text(md, encoding="utf-8")
    ir = load(f)
    # жирный ярлык остался в контент-секции Founder; источники разобраны из ## Sources
    assert any("Ключевые факты" in p for p in ir.sections[0].paragraphs)
    assert len(ir.citations) == 1 and ir.citations[0].url == "https://tc.com/a"


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
