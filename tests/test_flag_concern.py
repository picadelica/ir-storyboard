"""Fix A: red/grey facts promoted by the keyword heuristic must carry a concern.

The heuristic in ``flag_heuristics`` can promote a fact green→red or →grey by a
keyword match even when the LLM left the rationale empty (it considered the fact
green). Previously such facts surfaced as red/grey with an empty concern. These
tests lock in that the heuristic now yields a reason, and that the extractor
normalizes the rationale so no red/grey fact is ever empty.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard.ingest.classifiers.flag_heuristics import (
    apply_heuristics,
    classify_with_reason,
)
from ir_storyboard.llm import _normalize_rationale, _stub_extract


# ── classify_with_reason ────────────────────────────────────────────────────

def test_red_trigger_on_green_returns_reason():
    """green + red keyword → red with a non-empty reason carrying the keyword."""
    flag, reason = classify_with_reason("The company faced a major lawsuit", "green")
    assert flag == "red"
    assert reason
    assert "lawsuit" in reason


def test_grey_trigger_returns_reason():
    flag, reason = classify_with_reason("No information available on revenue", "green")
    assert flag == "grey"
    assert reason
    assert "no information" in reason.lower()


def test_unchanged_flag_returns_empty_reason():
    """When the heuristic does not change the flag, reason is empty so the
    LLM-supplied rationale is preserved by the caller."""
    flag, reason = classify_with_reason("A perfectly neutral statement.", "green")
    assert flag == "green"
    assert reason == ""

    # LLM already said red → heuristic does not re-author the reason
    flag, reason = classify_with_reason("There was a lawsuit", "red")
    assert flag == "red"
    assert reason == ""


def test_apply_heuristics_wrapper_matches_flag():
    assert apply_heuristics("The company faced a major lawsuit", "green") == "red"
    assert apply_heuristics("No information available", "green") == "grey"
    assert apply_heuristics("A neutral statement.", "green") == "green"


# ── _normalize_rationale belt-and-suspenders ────────────────────────────────

def test_normalize_rationale_red_empty_gets_placeholder():
    assert _normalize_rationale("red", "") == "(требует уточнения экспертом)"
    assert _normalize_rationale("grey", None) == "(требует уточнения экспертом)"


def test_normalize_rationale_prefers_real_reason():
    real = "авто-классификатор: ключевое слово «lawsuit» (риск/споры/негатив)"
    assert _normalize_rationale("red", real) == real


def test_normalize_rationale_green_drops():
    assert _normalize_rationale("green", "anything") == ""


# ── end-to-end through the stub extractor (no LLM key needed) ────────────────

def test_stub_extract_red_fact_carries_rationale():
    """A paragraph with a red trigger, classified green by the (stub) LLM,
    must emerge red WITH a non-empty rationale — never an empty concern."""
    paragraphs = [
        "The founder was named in a lawsuit by former investors over the round.",
    ]
    facts = _stub_extract("Founder background", paragraphs, ["1.1"])
    assert facts, "expected at least one extracted fact"
    red = [f for f in facts if f.flag == "red"]
    assert red, "red trigger should have promoted the fact to red"
    for f in red:
        assert f.rationale.strip(), "red fact must carry a non-empty rationale"
