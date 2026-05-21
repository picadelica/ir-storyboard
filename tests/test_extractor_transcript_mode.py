"""Tests for FactExtractor in transcript-mode (segment_idx_* + layer_warning)."""
import json
from unittest.mock import patch

from ir_storyboard.llm import extract_facts_from_full_document, ExtractedFact


_AVAILABLE = [
    "1.1", "1.2", "1.3",
    "2.1", "2.2", "2.3",
    "3.1", "3.2", "3.3",
    "4.1", "4.2", "4.3",
    "5.1", "5.2", "5.3",
    "6.1", "6.2", "6.3",
    "7.1", "7.2", "7.3",
    "8.1", "8.2", "8.3",
]


def _mock_generate(response_dict):
    """Patch llm.generate to return a fake JSON response."""
    return patch(
        "ir_storyboard.llm.generate",
        return_value=json.dumps(response_dict),
    )


# ── segment indices preserved ─────────────────────────────────────────────────

def test_transcript_mode_returns_segment_indices():
    """Facts with segment_idx_* survive through extract_facts_from_full_document."""
    fake_response = {
        "facts": [
            {
                "text": "Founder joined Bitfury in 2014.",
                "subsection_id": "2.1",
                "flag": "green",
                "cite_ids": [1],
                "confidence": 0.9,
                "raw_paraphrase": "I joined Bitfury in 2014.",
                "segment_idx_start": 5,
                "segment_idx_end": 7,
                "layer_warning": False,
            },
            {
                "text": "Left Bitfury in 2019 after Series B.",
                "subsection_id": "2.1",
                "flag": "green",
                "cite_ids": [1],
                "confidence": 0.85,
                "raw_paraphrase": "we left in 2019 after the Series B.",
                "segment_idx_start": 8,
                "segment_idx_end": 8,
                "layer_warning": False,
            },
            {
                "text": "Currently building Gonka.ai.",
                "subsection_id": "2.2",
                "flag": "green",
                "cite_ids": [1],
                "confidence": 0.8,
                "raw_paraphrase": "we are building Gonka.ai right now.",
                "segment_idx_start": 12,
                "segment_idx_end": 13,
                "layer_warning": False,
            },
        ]
    }

    sections = [("Transcript", ["Some transcript paragraph text here."])]

    with _mock_generate(fake_response):
        facts = extract_facts_from_full_document(
            sections=sections,
            available_subsections=_AVAILABLE,
            citation_index={},
        )

    assert len(facts) == 3
    assert facts[0].segment_idx_start == 5
    assert facts[0].segment_idx_end == 7
    assert facts[1].segment_idx_start == 8
    assert facts[1].segment_idx_end == 8
    assert facts[2].segment_idx_start == 12
    assert facts[2].segment_idx_end == 13
    assert not facts[0].layer_warning


# ── layer_warning passed through ─────────────────────────────────────────────

def test_transcript_mode_layer_warning_passed_through():
    """L5 fact with layer_warning=true reaches ExtractedFact with layer_warning=True."""
    fake_response = {
        "facts": [
            {
                "text": "DePIN market will reach $32B by 2028.",
                "subsection_id": "5.1",   # L5 — will be guarded later by LayerGuard
                "flag": "green",
                "cite_ids": [1],
                "confidence": 0.7,
                "raw_paraphrase": "The DePIN market will reach 32 billion by 2028.",
                "segment_idx_start": 20,
                "segment_idx_end": 21,
                "layer_warning": True,
            },
        ]
    }

    sections = [("Transcript", ["Some transcript content."])]

    with _mock_generate(fake_response):
        facts = extract_facts_from_full_document(
            sections=sections,
            available_subsections=_AVAILABLE,
            citation_index={},
        )

    assert len(facts) == 1
    assert facts[0].layer_warning is True
    assert facts[0].subsection_id == "5.1"
    assert facts[0].segment_idx_start == 20


# ── document-mode facts don't get segment fields ──────────────────────────────

def test_document_mode_facts_have_none_segment_indices():
    """Regular document-mode facts: segment_idx_* should be None."""
    fake_response = {
        "facts": [
            {
                "text": "Company raised $10M in 2023.",
                "subsection_id": "6.1",
                "flag": "green",
                "cite_ids": [],
                "confidence": 0.8,
                "raw_paraphrase": "raised 10 million in 2023.",
            },
        ]
    }

    sections = [("Business Model", ["Company details paragraph."])]

    with _mock_generate(fake_response):
        facts = extract_facts_from_full_document(
            sections=sections,
            available_subsections=_AVAILABLE,
            citation_index={},
        )

    assert len(facts) == 1
    assert facts[0].segment_idx_start is None
    assert facts[0].segment_idx_end is None
    assert facts[0].layer_warning is False
