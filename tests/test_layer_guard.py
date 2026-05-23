"""Tests for layer_guard.py."""
from ir_storyboard.ingest.layer_guard import guard_layers, ALLOWED_LAYERS_BY_CHANNEL
from ir_storyboard.ingest.snippet_anchor import AnchoredFact


def _make_anchored(subsection_id, flag="green"):
    return AnchoredFact(
        text="Some fact text that is meaningful.",
        subsection_id=subsection_id,
        flag=flag,
        evidence_snippet="literal quote from transcript segment here",
        source_url="https://www.youtube.com/watch?v=abc&t=100s",
    )


# ── passes ────────────────────────────────────────────────────────────────────

def test_guard_passes_l1_l4_l7():
    facts = [
        _make_anchored("1.1"),
        _make_anchored("1.2"),
        _make_anchored("1.3"),
        _make_anchored("4.1"),
        _make_anchored("4.2"),
        _make_anchored("7.1"),
        _make_anchored("7.3"),
    ]
    allowed, skipped = guard_layers(facts, "online_interview")
    assert len(allowed) == 7
    assert len(skipped) == 0


# ── blocked ───────────────────────────────────────────────────────────────────

def test_guard_blocks_l5_l6_l8():
    facts = [
        _make_anchored("5.1"),
        _make_anchored("6.1"),
        _make_anchored("8.2"),
    ]
    allowed, skipped = guard_layers(facts, "online_interview")
    assert len(allowed) == 0
    assert len(skipped) == 3


def test_guard_skipped_facts_carry_text():
    """Skipped facts expose their text and reason for override-UX."""
    facts = [_make_anchored("5.3")]
    _, skipped = guard_layers(facts, "online_interview")

    assert len(skipped) == 1
    sf = skipped[0]
    assert "Some fact text" in sf.fact.text
    assert "5.3" in sf.reason or "5" in sf.reason
    assert sf.override_allowed is True


# ── mixed batch ───────────────────────────────────────────────────────────────

def test_guard_mixed_batch():
    facts = [
        _make_anchored("2.1"),   # allowed
        _make_anchored("6.2"),   # blocked
        _make_anchored("3.2"),   # allowed
        _make_anchored("8.3"),   # blocked
        _make_anchored("7.2"),   # allowed
    ]
    allowed, skipped = guard_layers(facts, "online_interview")
    assert len(allowed) == 3
    assert len(skipped) == 2
    assert all(sf.override_allowed for sf in skipped)


# ── unknown channel has no restrictions ──────────────────────────────────────

def test_guard_unknown_channel_passes_all():
    facts = [_make_anchored("6.1"), _make_anchored("8.1")]
    allowed, skipped = guard_layers(facts, "archival")
    assert len(allowed) == 2
    assert len(skipped) == 0
