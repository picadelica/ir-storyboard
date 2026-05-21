"""Tests for YouTube Ingest backend endpoints and pipeline."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path):
    """TestClient with isolated file-based SQLite DB (thread-safe)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from ir_storyboard import db as _db, matrix
    from backend.main import app, get_conn

    db_path = tmp_path / "test_yt.db"

    def _override_conn():
        conn = _db.connect(db_path)
        _db.init_schema(conn)
        matrix.seed_layers(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = _override_conn

    # Seed test client
    conn = _db.connect(db_path)
    _db.init_schema(conn)
    matrix.seed_layers(conn)
    matrix.upsert_client(conn, "test_client", "Test Client", sector="test")
    conn.close()

    with TestClient(app) as tc:
        yield tc

    app.dependency_overrides.clear()


# ── mock helpers ───────────────────────────────────────────────────────────────

def _make_meta(video_id="testVID"):
    m = MagicMock()
    m.video_id = video_id
    m.canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    m.title = "Test Interview"
    m.channel_name = "Test Channel"
    m.channel_url = "https://youtube.com/@test"
    m.duration_sec = 1800
    m.upload_date = "2026-01-15"
    m.description = ""
    m.language = "en"
    return m


def _make_preview_result(video_id="testVID"):
    from ir_storyboard.channels.llm_report.snippet_anchor import AnchoredFact
    from ir_storyboard.channels.llm_report.youtube_pipeline import YouTubePreviewResult

    facts = [
        AnchoredFact(
            text="Founder joined Bitfury in 2014 as an early engineer.",
            subsection_id="2.1",
            flag="green",
            confidence=0.9,
            evidence_snippet="I joined Bitfury in 2014, basically right after it was founded by the team.",
            source_url=f"https://www.youtube.com/watch?v={video_id}&t=420s",
            snippet_start_sec=420.0,
            snippet_end_sec=424.0,
        ),
        AnchoredFact(
            text="Company focuses on decentralised physical infrastructure networks.",
            subsection_id="7.1",
            flag="green",
            confidence=0.85,
            evidence_snippet="We are building decentralised physical infrastructure networks that matter.",
            source_url=f"https://www.youtube.com/watch?v={video_id}&t=600s",
            snippet_start_sec=600.0,
            snippet_end_sec=605.0,
        ),
    ]
    return YouTubePreviewResult(
        preview_id="test-preview-id-123",
        meta=_make_meta(video_id),
        facts=facts,
        skipped=[],
        notes=["Transcript loaded from cache"],
        stats={"facts_emitted": 2, "greys": 0, "channel_warnings": 0},
        from_cache=True,
        transcribe_cost_usd=None,
    )


def _make_preview_result_with_l5(video_id="testVID"):
    from ir_storyboard.channels.llm_report.snippet_anchor import AnchoredFact
    from ir_storyboard.channels.llm_report.layer_guard import SkippedFact
    from ir_storyboard.channels.llm_report.youtube_pipeline import YouTubePreviewResult

    allowed = [
        AnchoredFact(
            text="Founder was Director of Product at Snap Inc. for three years.",
            subsection_id="2.1",
            flag="green",
            confidence=0.9,
            evidence_snippet="I was Director of Product at Snap Incorporated for three years before this.",
            source_url=f"https://www.youtube.com/watch?v={video_id}&t=100s",
        ),
    ]
    l5_fact = AnchoredFact(
        text="Client saw 10x revenue after adopting the platform.",
        subsection_id="5.1",
        flag="green",
        confidence=0.7,
        evidence_snippet="One of our clients saw ten times revenue growth after joining us.",
        source_url=f"https://www.youtube.com/watch?v={video_id}&t=800s",
    )
    skipped = [SkippedFact(
        fact=l5_fact,
        reason="L5 (5.1) is not allowed for online_interview — requires archival or online_research",
    )]
    return YouTubePreviewResult(
        preview_id="test-l5-preview-id",
        meta=_make_meta(video_id),
        facts=allowed,
        skipped=skipped,
        notes=[],
        stats={"facts_emitted": 2, "greys": 0, "channel_warnings": 1},
        from_cache=False,
        transcribe_cost_usd=None,
    )


# ── tests ──────────────────────────────────────────────────────────────────────

def test_preview_returns_facts_with_anchors(client, tmp_path):
    with patch(
        "ir_storyboard.channels.llm_report.youtube_pipeline.run_youtube_preview",
        return_value=_make_preview_result(),
    ):
        resp = client.post(
            "/api/clients/test_client/ingest/youtube/preview",
            json={"url": "https://www.youtube.com/watch?v=testVID"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["facts"]) == 2
    for fact in data["facts"]:
        assert "&t=" in fact["source_url"]
        assert len(fact["evidence_snippet"]) >= 20


def test_preview_separates_skipped_l5_facts(client, tmp_path):
    with patch(
        "ir_storyboard.channels.llm_report.youtube_pipeline.run_youtube_preview",
        return_value=_make_preview_result_with_l5(),
    ):
        resp = client.post(
            "/api/clients/test_client/ingest/youtube/preview",
            json={"url": "https://www.youtube.com/watch?v=testVID"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["facts"]) == 1
    assert len(data["skipped"]) == 1
    assert "L5" in data["skipped"][0]["reason"] or "5.1" in data["skipped"][0]["reason"]


def _seed_preview_audit(tmp_path, preview_result, client_id="test_client"):
    """Write the preview audit row that run_youtube_preview would normally write."""
    import sqlite3 as _sq
    from ir_storyboard.channels.llm_report.youtube_pipeline import (
        _ensure_audit_table_youtube, _anchored_to_dict,
    )
    db_path = tmp_path / "test_yt.db"
    conn = _sq.connect(str(db_path))
    conn.row_factory = _sq.Row
    _ensure_audit_table_youtube(conn)

    from ir_storyboard.channels.llm_report.snippet_anchor import AnchoredFact
    facts_data = [_anchored_to_dict(f) for f in preview_result.facts]
    skipped_data = [
        {"text": s.fact.text, "reason": s.reason,
         "subsection_id": s.fact.subsection_id,
         "source_url": s.fact.source_url,
         "evidence_snippet": s.fact.evidence_snippet}
        for s in preview_result.skipped
    ]
    preview_json = json.dumps({
        "preview_id": preview_result.preview_id,
        "video_id": preview_result.meta.video_id,
        "canonical_url": preview_result.meta.canonical_url,
        "facts": facts_data,
        "skipped": skipped_data,
        "stats": preview_result.stats,
        "notes": preview_result.notes,
        "meta": {
            "title": preview_result.meta.title,
            "channel_name": preview_result.meta.channel_name,
        },
    })
    conn.execute(
        """INSERT OR REPLACE INTO ingest_audit
            (id, client_id, ingest_kind, source_artifact, agent,
             parsed_at, facts_emitted, facts_committed, greys_emitted,
             channel_warnings, expert_email, confirmed_at, preview_json,
             video_id, transcriber)
           VALUES (?, ?, 'youtube', ?, 'youtube',
                   CURRENT_TIMESTAMP, ?, 0, 0, 0, '', CURRENT_TIMESTAMP, ?, ?,
                   'local-faster-whisper:large-v3-turbo')""",
        (
            preview_result.preview_id, client_id,
            preview_result.meta.canonical_url,
            preview_result.stats.get("facts_emitted", 0),
            preview_json,
            preview_result.meta.video_id,
        ),
    )
    conn.commit()
    conn.close()


def test_commit_writes_to_matrix(client, tmp_path):
    preview_result = _make_preview_result()
    _seed_preview_audit(tmp_path, preview_result)

    resp = client.post(
        "/api/clients/test_client/ingest/youtube/commit",
        json={
            "preview_id": preview_result.preview_id,
            "accepted_fact_ids": [0, 1],
            "overrides": [],
            "expert_email": "test@example.com",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["committed"] >= 1


def test_commit_idempotent_on_replay(client, tmp_path):
    preview_result = _make_preview_result()
    _seed_preview_audit(tmp_path, preview_result)

    commit_payload = {"preview_id": preview_result.preview_id, "accepted_fact_ids": [0, 1], "overrides": []}

    client.post("/api/clients/test_client/ingest/youtube/commit", json=commit_payload)
    resp2 = client.post("/api/clients/test_client/ingest/youtube/commit", json=commit_payload)

    assert resp2.status_code == 200
    assert resp2.json()["committed"] == 0


def test_commit_respects_overrides(client, tmp_path):
    preview_result = _make_preview_result_with_l5()
    _seed_preview_audit(tmp_path, preview_result)

    resp = client.post(
        "/api/clients/test_client/ingest/youtube/commit",
        json={
            "preview_id": preview_result.preview_id,
            "accepted_fact_ids": [0],
            "overrides": [{"fact_idx": 0, "force_keep": True}],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["committed"] == 2   # 2.1 fact + override L5 fact


def test_youtube_history_empty(client, tmp_path):
    resp = client.get("/api/clients/test_client/ingest/youtube/history")
    assert resp.status_code == 200
    assert resp.json() == []
