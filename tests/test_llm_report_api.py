"""Tests for LLM Report Ingest API endpoints (Task 6)."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures" / "llm_report"
GONKA_DOCX = FIXTURES / "gonka_chatgpt_deep_research.docx"


@pytest.fixture
def client(tmp_path):
    """TestClient with isolated in-memory SQLite DB."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from ir_storyboard import db as _db, matrix
    from backend.main import app, get_conn

    db_path = tmp_path / "test.db"

    def _override_conn():
        conn = _db.connect(db_path)
        _db.init_schema(conn)
        matrix.seed_layers(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = _override_conn

    # Seed a client
    conn = _db.connect(db_path)
    _db.init_schema(conn)
    matrix.seed_layers(conn)
    matrix.upsert_client(conn, "libermans-gonka", "Libermans (Gonka AI)", sector="DePIN")
    conn.close()

    with TestClient(app) as tc:
        yield tc

    app.dependency_overrides.clear()


def _make_md_content() -> bytes:
    content = (
        "# Technology & Product\n\n"
        "Gonka uses Proof-of-Work 2.0 consensus [1].\n"
        "The network grew 16x in two months after launch [2].\n\n"
        "# Sources\n\n"
        "[1] Crypto Briefing - Gonka Launch - https://cryptobriefing.com/gonka-decentralized-ai-compute-launch/\n"
        "[2] BusinessWire - Bitfury $50M - https://www.businesswire.com/news/home/20251201364475/en/Bitfury\n"
    )
    return content.encode("utf-8")


# ── preview endpoint ──────────────────────────────────────────────────────────

def test_preview_endpoint_md(client, tmp_path):
    """Preview with a simple markdown file — no external deps needed."""
    from ir_storyboard import llm as llm_module

    with patch.object(llm_module, "generate", return_value=""):
        resp = client.post(
            "/api/clients/libermans-gonka/ingest/llm-report/preview",
            files={"file": ("report.md", _make_md_content(), "text/markdown")},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "audit_id" in data
    assert "facts" in data
    assert "sources" in data
    assert isinstance(data["facts"], list)
    assert isinstance(data["sources"], list)


def test_preview_endpoint_unknown_client(client):
    resp = client.post(
        "/api/clients/nonexistent-xyz/ingest/llm-report/preview",
        files={"file": ("report.md", _make_md_content(), "text/markdown")},
    )
    assert resp.status_code == 404


def test_preview_endpoint_bad_extension(client):
    resp = client.post(
        "/api/clients/libermans-gonka/ingest/llm-report/preview",
        files={"file": ("report.xlsx", b"garbage", "application/vnd.ms-excel")},
    )
    assert resp.status_code == 400


@pytest.mark.skipif(not GONKA_DOCX.exists(), reason="gonka docx fixture not found")
def test_preview_endpoint_docx(client):
    """Preview with the real Gonka docx — requires python-docx on server."""
    from ir_storyboard import llm as llm_module

    with patch.object(llm_module, "generate", return_value=""), \
         open(GONKA_DOCX, "rb") as f:
        resp = client.post(
            "/api/clients/libermans-gonka/ingest/llm-report/preview",
            files={"file": ("gonka_chatgpt_deep_research.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["sources"]) >= 1
    assert len(data["facts"]) >= 1


# ── commit endpoint ───────────────────────────────────────────────────────────

def _build_preview_payload(audit_id: str = "test-audit-001") -> dict:
    return {
        "preview": {
            "audit_id": audit_id,
            "source_artifact_path": "/tmp/nonexistent.md",
            "detected_agent": "unknown",
            "sources": [
                {
                    "cite_id": 1,
                    "canonical_url": "cryptobriefing.com/gonka-decentralized-ai-compute-launch",
                    "title": "Crypto Briefing — Gonka Launch",
                    "publisher": "Crypto Briefing",
                    "channel": "online_research",
                    "classification_reason": "web source",
                }
            ],
            "facts": [
                {
                    "text": "Gonka uses Proof-of-Work 2.0 consensus for AI inference.",
                    "subsection_id": "6.1",
                    "flag": "green",
                    "cite_ids": [1],
                    "confidence": 0.9,
                    "raw_paraphrase": "Gonka uses Proof-of-Work 2.0.",
                    "evidence_snippet": "Unlike traditional PoW, Gonka's Sprint consensus channels GPU cycles.",
                    "needs_review": False,
                    "snippet_source": "llm_paraphrase",
                },
                {
                    "text": "The network grew 16x in two months after mainnet launch.",
                    "subsection_id": "6.3",
                    "flag": "green",
                    "cite_ids": [1],
                    "confidence": 0.85,
                    "raw_paraphrase": "Network grew 16x in two months.",
                    "evidence_snippet": "The network has grown 16x in two months and is targeting 10,000 GPUs.",
                    "needs_review": False,
                    "snippet_source": "llm_paraphrase",
                },
            ],
            "notes": [],
            "stats": {"facts_emitted": 2, "greys": 0, "channel_warnings": 0},
        },
        "edits": [],
        "expert_email": "ci@example.com",
    }


def test_commit_endpoint(client):
    payload = _build_preview_payload()
    resp = client.post(
        "/api/clients/libermans-gonka/ingest/llm-report/commit",
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["committed_facts"] == 2
    assert data["audit_id"] == "test-audit-001"


def test_commit_with_drop_edit(client):
    payload = _build_preview_payload("test-audit-002")
    payload["edits"] = [{"fact_idx": 1, "action": "drop"}]

    resp = client.post(
        "/api/clients/libermans-gonka/ingest/llm-report/commit",
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["committed_facts"] == 1, f"Expected 1, got {data['committed_facts']}"


# ── history endpoint ──────────────────────────────────────────────────────────

def test_history_endpoint(client):
    # First commit something
    payload = _build_preview_payload("hist-audit-001")
    client.post(
        "/api/clients/libermans-gonka/ingest/llm-report/commit",
        json=payload,
    )

    resp = client.get("/api/clients/libermans-gonka/ingest/llm-report/history")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) >= 1
    assert rows[0]["id"] == "hist-audit-001"
    assert rows[0]["expert_email"] == "ci@example.com"


def test_history_empty(client):
    """New client with no ingests → empty list."""
    resp = client.get("/api/clients/libermans-gonka/ingest/llm-report/history")
    assert resp.status_code == 200
    assert resp.json() == []


# ── generate-prompt + paste-text (proposal #3 part B) ───────────────────────────

def test_llm_report_prompt_generation(client):
    r = client.get("/api/clients/libermans-gonka/ingest/llm-report/prompt", params={"agent": "chatgpt"})
    assert r.status_code == 200
    d = r.json()
    assert d["agent"] == "chatgpt" and "chatgpt" in d["agents"]
    assert "Libermans (Gonka AI)" in d["prompt"]          # subject filled
    assert "L1 Founder Personal Story" in d["prompt"]     # matrix intro present
    assert "Open Questions for Interview" in d["prompt"]
    # a different agent yields a different body
    claude = client.get("/api/clients/libermans-gonka/ingest/llm-report/prompt", params={"agent": "claude"}).json()
    assert claude["prompt"] != d["prompt"]


def test_llm_report_preview_text(client):
    pasted = (
        "## Technology & Product\n"
        "Gonka runs a decentralized GPU network for AI training [1].\n\n"
        "## Investments & Financing\n"
        "Raised a $10M seed round in 2024 led by Bitfury [2].\n\n"
        "## Sources\n"
        "[1] Gonka Docs — gonka.ai — https://gonka.ai/docs\n"
        "[2] TechCrunch — TechCrunch — https://techcrunch.com/gonka\n"
    )
    r = client.post("/api/clients/libermans-gonka/ingest/llm-report/preview-text",
                    json={"text": pasted, "agent_hint": "chatgpt-deep-research"})
    assert r.status_code == 200, r.text
    d = r.json()
    # same pipeline as a file upload: facts extracted + parsed [N] sources
    assert d["facts"], "pasted markdown report should yield facts"
    assert any("gonka.ai" in (s.get("canonical_url") or "") for s in d["sources"])
    # empty text rejected
    assert client.post("/api/clients/libermans-gonka/ingest/llm-report/preview-text",
                       json={"text": "   "}).status_code == 400
