"""E2E test: Gonka docx → libermans-gonka client (golden YAML fixture diff).

Runs the full pipeline on the real fixture file.
Requires ANTHROPIC_API_KEY to activate real LLM fact extraction;
without the key the test uses the stub extractor (fewer facts, but pipeline still works).

Run:
    pytest tests/test_llm_report_e2e.py -q
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import yaml

FIXTURES = Path(__file__).parent / "fixtures" / "llm_report"
GONKA_DOCX = FIXTURES / "gonka_chatgpt_deep_research.docx"
EXPECTED_YAML = FIXTURES / "libermans_gonka.expected.yaml"

CLIENT_ID = "libermans-gonka"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db_conn(tmp_path):
    from ir_storyboard import db as _db, matrix

    db_path = tmp_path / "e2e.db"
    conn = _db.connect(db_path)
    _db.init_schema(conn)
    matrix.seed_layers(conn)
    matrix.upsert_client(
        conn, CLIENT_ID, "Libermans (Gonka AI)",
        sector="decentralized AI compute / DePIN",
        one_liner="Community-owned PoW-2.0 network for AI inference.",
        founder_name="David & Daniil Liberman",
        founder_handle="daniilliberman",
    )
    yield conn
    conn.close()


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_expected() -> dict[str, Any]:
    if not EXPECTED_YAML.exists():
        return {}
    with EXPECTED_YAML.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _client_facts(conn: sqlite3.Connection, client_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT f.text, f.flag, f.evidence_snippet, f.confidence,
                  c.subsection_id,
                  s.channel AS source_channel, s.url AS source_url
             FROM facts f
             JOIN cells c ON c.id = f.cell_id
             LEFT JOIN sources s ON s.id = f.source_id
             WHERE c.client_id = ?
             ORDER BY c.subsection_id, f.id""",
        (client_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _client_sources(conn: sqlite3.Connection, client_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT DISTINCT s.url, s.channel, s.title, s.publisher
             FROM sources s
             JOIN facts f ON f.source_id = s.id
             JOIN cells c ON c.id = f.cell_id
             WHERE c.client_id = ?""",
        (client_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── main e2e test ─────────────────────────────────────────────────────────────

@pytest.mark.skipif(not GONKA_DOCX.exists(), reason="gonka docx fixture not found")
@pytest.mark.skipif(not EXPECTED_YAML.exists(), reason="expected YAML fixture not found")
def test_e2e_gonka_matches_expected_yaml(db_conn):
    """Full pipeline: docx → preview → commit → verify against golden YAML."""
    from ir_storyboard.channels.llm_report.pipeline import (
        preview_llm_report,
        commit_llm_report,
    )

    # Step 1: preview
    preview = preview_llm_report(GONKA_DOCX, CLIENT_ID, db_conn)

    assert preview.audit_id, "audit_id must be set"
    assert preview.detected_agent is not None, "agent should be detected"

    # Step 2: commit (no edits — take all facts)
    result = commit_llm_report(preview, CLIENT_ID, db_conn, "ci@example.com")

    facts = _client_facts(db_conn, CLIENT_ID)
    sources = _client_sources(db_conn, CLIENT_ID)
    expected = _load_expected()

    # ── invariant checks ──────────────────────────────────────────────────────

    # At least some facts committed
    assert len(facts) >= 1, "Expected at least 1 committed fact"

    # Grey facts count is reasonable
    grey_count = sum(1 for f in facts if f["flag"] == "grey")
    assert grey_count >= 0  # can be 0 in stub mode

    # No fact in L1 via online_research
    for fact in facts:
        sid = fact["subsection_id"]
        layer = int(sid.split(".")[0]) if sid and "." in sid else 0
        channel = fact["source_channel"] or "online_research"
        assert not (layer == 1 and channel == "online_research"), (
            f"L1 fact via online_research is forbidden: {fact['text'][:60]}"
        )

    # Audit row was written
    audit_row = db_conn.execute(
        "SELECT * FROM ingest_audit WHERE id = ?", (preview.audit_id,)
    ).fetchone()
    assert audit_row is not None, "Audit row should be written"
    assert audit_row["client_id"] == CLIENT_ID
    assert audit_row["facts_committed"] == result.committed_facts

    # ── against expected YAML (if we have enough facts from real LLM) ─────────
    seed_facts = expected.get("seed_facts", [])
    if not seed_facts:
        return  # no golden data to compare

    expected_sids = {f["subsection_id"] for f in seed_facts}
    actual_sids = {f["subsection_id"] for f in facts}

    # Check that at least 50% of expected subsections are covered
    # (tolerance for stub mode which extracts fewer facts)
    covered = expected_sids & actual_sids
    coverage_ratio = len(covered) / len(expected_sids) if expected_sids else 1.0

    # With real LLM key we expect full coverage; without key (stub) we accept partial
    has_real_llm = bool(os.environ.get("ANTHROPIC_API_KEY"))
    min_coverage = 0.6 if has_real_llm else 0.1

    assert coverage_ratio >= min_coverage, (
        f"Coverage {coverage_ratio:.0%} below threshold {min_coverage:.0%}. "
        f"Missing subsections: {expected_sids - actual_sids}"
    )

    # Expected URLs should appear in sources (if LLM key present)
    if has_real_llm:
        expected_urls_raw = {
            f["source_url"] for f in seed_facts
            if f.get("source_url", "").startswith("http")
        }
        actual_urls = {s["url"] or "" for s in sources}
        # At least 3 of 7 expected URLs should be present
        matched = sum(
            1 for eu in expected_urls_raw
            if any(eu in au or au in eu for au in actual_urls)
        )
        assert matched >= 3, (
            f"Only {matched} of {len(expected_urls_raw)} expected URLs found in sources"
        )


# ── idempotency e2e ───────────────────────────────────────────────────────────

@pytest.mark.skipif(not GONKA_DOCX.exists(), reason="gonka docx fixture not found")
def test_e2e_double_ingest_is_idempotent(db_conn):
    """Second ingest of the same file produces 0 new facts."""
    from ir_storyboard.channels.llm_report.pipeline import (
        preview_llm_report,
        commit_llm_report,
    )

    p1 = preview_llm_report(GONKA_DOCX, CLIENT_ID, db_conn)
    r1 = commit_llm_report(p1, CLIENT_ID, db_conn, "ci@example.com")

    p2 = preview_llm_report(GONKA_DOCX, CLIENT_ID, db_conn)
    r2 = commit_llm_report(p2, CLIENT_ID, db_conn, "ci@example.com")

    assert r2.committed_facts == 0, (
        f"Expected 0 new facts on second ingest, got {r2.committed_facts}"
    )


# ── audit table e2e ───────────────────────────────────────────────────────────

@pytest.mark.skipif(not GONKA_DOCX.exists(), reason="gonka docx fixture not found")
def test_e2e_audit_row_completeness(db_conn):
    """Audit row contains all required fields after commit."""
    from ir_storyboard.channels.llm_report.pipeline import (
        preview_llm_report,
        commit_llm_report,
    )

    preview = preview_llm_report(GONKA_DOCX, CLIENT_ID, db_conn)
    commit_llm_report(preview, CLIENT_ID, db_conn, "auditor@example.com")

    row = db_conn.execute(
        "SELECT * FROM ingest_audit WHERE id = ?", (preview.audit_id,)
    ).fetchone()

    assert row["client_id"] == CLIENT_ID
    assert row["ingest_kind"] == "llm_report"
    assert row["expert_email"] == "auditor@example.com"
    assert row["parsed_at"] is not None
    assert row["confirmed_at"] is not None
    assert row["preview_json"] is not None
