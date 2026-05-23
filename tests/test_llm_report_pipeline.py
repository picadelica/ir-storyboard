"""Tests for LLM Report Ingest pipeline (Task 5)."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from ir_storyboard import db as _db, matrix
from ir_storyboard.ingest.pipeline import (
    preview_llm_report,
    commit_llm_report,
    _normalize_fact_text,
    _normalize_url,
)

FIXTURES = Path(__file__).parent / "fixtures" / "llm_report"
GONKA_DOCX = FIXTURES / "gonka_chatgpt_deep_research.docx"


# ── helpers ───────────────────────────────────────────────────────────────────

def _fresh_conn(tmp_path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    conn = _db.connect(db_path)
    _db.init_schema(conn)
    matrix.seed_layers(conn)
    return conn


def _seed_client(conn, client_id="libermans-gonka"):
    matrix.upsert_client(conn, client_id, "Libermans (Gonka AI)", sector="DePIN")


# ── normalisation unit tests ──────────────────────────────────────────────────

def test_normalize_fact_text_strips_numbers_in_parens():
    t = "Capacity grew to 6000 H100 GPUs (as of December 2025)"
    n = _normalize_fact_text(t)
    assert "6000" in n  # numbers alone preserved
    assert "(as of December 2025)" not in n  # parenthesised text removed


def test_normalize_fact_text_lowercases():
    assert _normalize_fact_text("Gonka Raised $50M") == "gonka raised $50m"


def test_normalize_url_strips_utm():
    url = "https://cryptobriefing.com/article?utm_source=tw&foo=1"
    n = _normalize_url(url)
    assert "utm_source" not in n
    assert "foo=1" in n


# ── pipeline with mocked LLM ──────────────────────────────────────────────────

def _make_mock_extract(sid="6.1"):
    """Return a mock for extract_facts_from_llm_report that produces one fact."""
    from ir_storyboard.llm import ExtractedFact

    def _mock(section_heading, section_paragraphs, available_subsections, citation_index):
        if not section_paragraphs:
            return []
        return [ExtractedFact(
            text=section_paragraphs[0][:240],
            subsection_id=sid if sid in available_subsections else available_subsections[0],
            flag="green",
            cite_ids=list(citation_index.keys())[:1],
            confidence=0.85,
            raw_paraphrase=section_paragraphs[0][:400],
        )]

    return _mock


@pytest.mark.skipif(not GONKA_DOCX.exists(), reason="gonka fixture not found")
def test_preview_then_commit_gonka(tmp_path):
    """Full pipeline on the real Gonka docx — mocked LLM, real loader + classifier."""
    from ir_storyboard import llm as llm_module

    conn = _fresh_conn(tmp_path)
    _seed_client(conn, "libermans-gonka")

    with patch.object(llm_module, "generate", return_value=""):
        # generate="" → stub extractor (no real LLM call)
        preview = preview_llm_report(GONKA_DOCX, "libermans-gonka", conn)

    assert preview.audit_id, "audit_id should be set"
    assert len(preview.sources) >= 1, f"Expected ≥1 source, got {len(preview.sources)}"
    assert len(preview.facts) >= 1, f"Expected ≥1 fact, got {len(preview.facts)}"
    assert preview.detected_agent is not None

    # Commit
    result = commit_llm_report(preview, "libermans-gonka", conn, "ci@example.com")

    assert result.committed_facts >= 1
    # Audit row exists
    row = conn.execute(
        "SELECT * FROM ingest_audit WHERE id = ?", (preview.audit_id,)
    ).fetchone()
    assert row is not None
    assert row["client_id"] == "libermans-gonka"
    assert row["expert_email"] == "ci@example.com"


@pytest.mark.skipif(not GONKA_DOCX.exists(), reason="gonka fixture not found")
def test_double_commit_is_idempotent(tmp_path):
    """Committing the same preview twice should produce 0 new rows on second run."""
    from ir_storyboard import llm as llm_module

    conn = _fresh_conn(tmp_path)
    _seed_client(conn, "libermans-gonka")

    with patch.object(llm_module, "generate", return_value=""):
        preview = preview_llm_report(GONKA_DOCX, "libermans-gonka", conn)

    r1 = commit_llm_report(preview, "libermans-gonka", conn, "ci@example.com")
    r2 = commit_llm_report(preview, "libermans-gonka", conn, "ci@example.com")

    # First commit: some facts
    assert r1.committed_facts >= 1
    # Second commit: all facts already exist → 0 new
    assert r2.committed_facts == 0, \
        f"Expected 0 new facts on second commit, got {r2.committed_facts}"


def test_commit_with_drop_edit(tmp_path):
    """Expert drops one fact → it should not be committed."""
    from ir_storyboard import llm as llm_module
    from ir_storyboard.ingest.snippet_resolver import ResolvedFact
    from ir_storyboard.ingest.citations import ResolvedCitation
    from ir_storyboard.ingest.pipeline import IngestPreview

    conn = _fresh_conn(tmp_path)
    _seed_client(conn, "test-client")

    # Build a synthetic preview with 2 facts
    cit = ResolvedCitation(1, "https://cryptobriefing.com/article", "CB Article",
                           "Crypto Briefing", "online_research", "web source")
    rf1 = ResolvedFact(
        text="Gonka raised $50M from Bitfury.",
        subsection_id="3.3", flag="green", cite_ids=[1], confidence=0.9,
        evidence_snippet="Bitfury committed $50M to Gonka in late 2025.",
    )
    rf2 = ResolvedFact(
        text="The network supports 2200 developers.",
        subsection_id="5.1", flag="green", cite_ids=[1], confidence=0.85,
        evidence_snippet="As of December 2025 Gonka serves over 2,200 developers.",
    )

    preview = IngestPreview(
        audit_id="test-audit-001",
        source_artifact_path="/tmp/test.docx",
        detected_agent="chatgpt-deep-research",
        sources=[cit],
        facts=[rf1, rf2],
        notes=[],
        stats={"facts_emitted": 2, "greys": 0, "channel_warnings": 0},
    )

    # Drop fact at index 1
    result = commit_llm_report(
        preview, "test-client", conn, "ci@example.com",
        edits=[{"fact_idx": 1, "action": "drop"}],
    )

    assert result.committed_facts == 1, \
        f"Expected 1 committed fact (dropped one), got {result.committed_facts}"


def test_edit_action_changes_subsection(tmp_path):
    """Expert changes subsection via edit → committed with new subsection_id."""
    from ir_storyboard.ingest.snippet_resolver import ResolvedFact
    from ir_storyboard.ingest.citations import ResolvedCitation
    from ir_storyboard.ingest.pipeline import IngestPreview

    conn = _fresh_conn(tmp_path)
    _seed_client(conn, "test-client2")

    cit = ResolvedCitation(1, "https://example.com/article", "Example",
                           "Example", "online_research", "web source")
    rf = ResolvedFact(
        text="Gonka uses Sprint consensus mechanism.",
        subsection_id="6.1", flag="green", cite_ids=[1], confidence=0.9,
        evidence_snippet="Sprint consensus channels GPU cycles to productive AI inference.",
    )
    preview = IngestPreview(
        audit_id="test-audit-002",
        source_artifact_path="/tmp/test2.docx",
        detected_agent=None,
        sources=[cit],
        facts=[rf],
        notes=[],
        stats={"facts_emitted": 1, "greys": 0, "channel_warnings": 0},
    )

    result = commit_llm_report(
        preview, "test-client2", conn, "ci@example.com",
        edits=[{"fact_idx": 0, "action": "edit", "new_subsection_id": "6.2"}],
    )

    assert result.committed_facts == 1
    # Check fact is in 6.2, not 6.1
    facts_6_2 = matrix.facts_for_cell(conn, "test-client2", "6.2")
    facts_6_1 = matrix.facts_for_cell(conn, "test-client2", "6.1")
    assert len(facts_6_2) == 1
    assert len(facts_6_1) == 0


def test_audit_table_created_by_init_schema(tmp_path):
    """init_schema should create ingest_audit table."""
    conn = _fresh_conn(tmp_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "ingest_audit" in tables
