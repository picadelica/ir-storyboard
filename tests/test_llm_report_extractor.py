"""Tests for FactExtractor + section→layer mapper + flag heuristics (Task 3)."""
from __future__ import annotations

from unittest.mock import patch

from ir_storyboard.ingest.classifiers.section_to_layer import suggest_subsection
from ir_storyboard.ingest.classifiers.flag_heuristics import apply_heuristics


# ── section → layer mapper ────────────────────────────────────────────────────

def test_section_to_layer_known():
    """Standard Gonka-report headings should map to expected subsections."""
    cases = [
        ("История и хронология", "2.1"),
        ("Основатели и структура собственности", "2.3"),
        ("Инвестиции и финансирование", "3.3"),
        ("Технология и продукт", "6.1"),
        ("Планы и дорожная карта", "6.3"),
        ("Конкурентная среда", "8.2"),
        ("Регуляторный и социальный контекст", "8.3"),
        ("Overview", "6.1"),
        ("Founders", "2.3"),
        ("Investments & Financing", "3.3"),
        ("Technology & Product", "6.1"),
        ("Roadmap", "6.3"),
        ("Competitive Landscape", "8.2"),
        ("Regulatory & Social Context", "8.3"),
    ]
    for heading, expected_sid in cases:
        got = suggest_subsection(heading)
        assert got == expected_sid, f"'{heading}' → expected {expected_sid}, got {got}"


def test_section_to_layer_unknown_returns_none():
    """Meta sections and genuinely unknown headings should return None."""
    for heading in ["Выводы", "Conclusions", "Заключение", "Open Questions for Interview",
                    "Summary", "What This Means", "Some Completely Unknown Section XYZ"]:
        assert suggest_subsection(heading) is None, \
            f"Expected None for '{heading}'"


def test_section_to_layer_case_insensitive():
    assert suggest_subsection("TECHNOLOGY & PRODUCT") == "6.1"
    assert suggest_subsection("roadmap") == "6.3"


# ── flag heuristics ───────────────────────────────────────────────────────────

def test_grey_heuristic_overrides_green():
    text = "in the report regulatory risks are not covered"
    assert apply_heuristics(text, "green") == "grey"


def test_grey_heuristic_on_russian():
    text = "Информация о коллективных провалах команды не покрыта в отчёте."
    assert apply_heuristics(text, "green") == "grey"


def test_grey_heuristic_overrides_red():
    """Grey should win even over red when the text indicates a gap."""
    text = "No information about regulatory risks is available."
    assert apply_heuristics(text, "red") == "grey"


def test_red_heuristic_upgrades_green():
    text = "The CEO was arrested and faces fraud charges in three jurisdictions."
    assert apply_heuristics(text, "green") == "red"


def test_no_override_when_neutral():
    text = "The company raised $50 million from institutional investors."
    assert apply_heuristics(text, "green") == "green"
    assert apply_heuristics(text, "red") == "red"


def test_no_override_preserves_grey():
    text = "The company raised $50 million."
    assert apply_heuristics(text, "grey") == "grey"


# ── extract_facts_from_llm_report (with mocked LLM) ──────────────────────────

def _make_citation_index():
    """Minimal stub citation index for tests."""
    from ir_storyboard.ingest.citations import ResolvedCitation
    return {
        1: ResolvedCitation(1, "https://businesswire.com/xyz", "BW Press Release",
                            "BusinessWire", "archival", "archival domain"),
        2: ResolvedCitation(2, "https://cryptobriefing.com/article", "Crypto Briefing",
                            "Crypto Briefing", "online_research", "web source"),
        3: ResolvedCitation(3, "https://u.today/interviews/test", "U.Today Interview",
                            "U.Today", "online_interview", "u.today interviews section"),
    }


def test_extract_facts_smoke_with_mocked_llm():
    """Mocked LLM returns 3 facts → function parses them correctly."""
    mock_response = """{
        "facts": [
            {"text": "Gonka raised $50M from Bitfury in December 2025.",
             "subsection_id": "3.3", "flag": "green", "cite_ids": [1],
             "confidence": 0.9, "raw_paraphrase": "Bitfury committed $50M to Gonka."},
            {"text": "The network grew 16x in two months after launch.",
             "subsection_id": "6.3", "flag": "green", "cite_ids": [2],
             "confidence": 0.85, "raw_paraphrase": "16x growth in 2 months."},
            {"text": "Regulatory risks are not covered in the report.",
             "subsection_id": "8.3", "flag": "green", "cite_ids": [],
             "confidence": 0.5, "raw_paraphrase": "Regulatory risks not covered."}
        ]
    }"""

    from ir_storyboard import llm as llm_module

    with patch.object(llm_module, "generate", return_value=mock_response):
        from ir_storyboard.llm import extract_facts_from_llm_report
        facts = extract_facts_from_llm_report(
            section_heading="Investments & Financing",
            section_paragraphs=[
                "Bitfury committed $50M to Gonka in late 2025 [1].",
                "The network grew 16x in two months [2].",
                "Regulatory risks are not covered in available sources.",
            ],
            available_subsections=["3.3", "6.3", "8.3", "8.1"],
            citation_index=_make_citation_index(),
        )

    assert len(facts) == 3, f"Expected 3 facts, got {len(facts)}"

    # Third fact mentions "not covered" → grey heuristic should fire
    assert facts[2].flag == "grey", \
        f"Expected grey for 'not covered' fact, got {facts[2].flag}"

    # First two should be green
    assert facts[0].flag == "green"
    assert facts[1].flag == "green"

    # cite_ids preserved
    assert facts[0].cite_ids == [1]
    assert facts[1].cite_ids == [2]


def test_extract_facts_stub_without_llm():
    """Without LLM key, stub returns facts from section paragraphs."""
    from ir_storyboard import llm as llm_module

    # Force stub mode by making generate return ""
    with patch.object(llm_module, "generate", return_value=""):
        from ir_storyboard.llm import extract_facts_from_llm_report
        facts = extract_facts_from_llm_report(
            section_heading="Technology & Product",
            section_paragraphs=[
                "Gonka uses Proof-of-Work 2.0 with Sprint consensus mechanism.",
                "Nearly 100% of GPU cycles go to productive AI inference.",
                "The network launched mainnet in August 2025.",
            ],
            available_subsections=["6.1", "6.2", "6.3"],
            citation_index={},
        )

    # Stub should return at least 1 fact for known section
    assert len(facts) >= 1
    for f in facts:
        assert f.subsection_id in ("6.1", "6.2", "6.3")


def test_extract_skips_unknown_subsection_from_llm():
    """If LLM returns a subsection_id not in available_subsections, skip it."""
    mock_response = """{
        "facts": [
            {"text": "Founder grew up in Moscow.",
             "subsection_id": "1.1", "flag": "green", "cite_ids": [],
             "confidence": 0.7, "raw_paraphrase": "Born in Moscow."},
            {"text": "Company raised $50M.",
             "subsection_id": "3.3", "flag": "green", "cite_ids": [],
             "confidence": 0.9, "raw_paraphrase": "$50M raised."}
        ]
    }"""

    from ir_storyboard import llm as llm_module

    with patch.object(llm_module, "generate", return_value=mock_response):
        from ir_storyboard.llm import extract_facts_from_llm_report
        facts = extract_facts_from_llm_report(
            section_heading="Investments",
            section_paragraphs=["Company raised $50M from Bitfury."],
            available_subsections=["3.3", "6.1"],  # 1.1 NOT available
            citation_index={},
        )

    # Only the 3.3 fact should survive (1.1 filtered out)
    assert len(facts) == 1
    assert facts[0].subsection_id == "3.3"
