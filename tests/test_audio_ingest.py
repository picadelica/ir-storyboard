"""Audio file Ingest tests.

faster-whisper / ffmpeg / ffprobe are NOT available locally — everything
external is mocked:
  * _probe_duration (ffprobe)        → fixed duration
  * split_audio (ffmpeg)             → single chunk, original file
  * Transcriber                      → MockTranscriber with call counter
  * extract_facts_from_transcript    → fixed ExtractedFact list
  * summarize_youtube_preview        → empty brief

Covers: sha256 transcript cache, preview → ingest_audit kind 'audio_file',
commit writes facts to the matrix, repeat upload → from_cache, and the
backend multipart endpoints (job flow, extension check, sha dedup on disk).
"""
from __future__ import annotations

import json
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


MOCK_SEGMENTS = [
    {"text": "Hi, I'm the founder, this is a recording of our offline talk.", "start": 0.0, "end": 4.0},
    {"text": "I joined Bitfury in 2014 as one of the early engineers there.", "start": 4.1, "end": 9.0},
    {"text": "Our mission is to make AI accessible to everyone on the planet.", "start": 9.1, "end": 14.0},
    {"text": "The DePIN market is growing rapidly according to analysts.", "start": 14.1, "end": 19.0},
]


class MockTranscriber:
    name = "mock-transcriber"

    def __init__(self):
        self.calls = 0

    def transcribe(self, audio_path, language_hint=None):
        from ir_storyboard.ingest.loaders.transcriber import TranscriptSegment
        self.calls += 1
        return [TranscriptSegment(**s) for s in MOCK_SEGMENTS]


def _mock_extracted_facts():
    from ir_storyboard.llm import ExtractedFact
    return [
        ExtractedFact(
            text="Founder joined Bitfury in 2014 as an early engineer.",
            subsection_id="2.1",
            flag="green",
            confidence=0.9,
            raw_paraphrase="I joined Bitfury in 2014 as one of the early engineers there.",
            segment_idx_start=1,
            segment_idx_end=1,
        ),
        ExtractedFact(
            text="Mission: make AI accessible to everyone on the planet.",
            subsection_id="7.1",
            flag="green",
            confidence=0.95,
            raw_paraphrase="Our mission is to make AI accessible to everyone on the planet.",
            segment_idx_start=2,
            segment_idx_end=2,
        ),
        ExtractedFact(
            text="DePIN market revenue projections — L8 content.",
            subsection_id="8.2",
            flag="green",
            confidence=0.6,
            raw_paraphrase="The DePIN market is growing rapidly according to analysts.",
            segment_idx_start=3,
            segment_idx_end=3,
        ),
    ]


def _make_conn(tmp_path):
    from ir_storyboard import db, matrix
    db_path = tmp_path / "audio.db"
    conn = db.connect(db_path)
    db.init_schema(conn)
    matrix.seed_layers(conn)
    matrix.upsert_client(conn, "test_founder", "Test Founder Co", sector="deeptech")
    return conn


@pytest.fixture
def audio_file(tmp_path):
    p = tmp_path / "interview.m4a"
    p.write_bytes(b"fake audio bytes for sha256 hashing - not a real m4a")
    return p


def _pipeline_patches(stack: ExitStack, transcriber: MockTranscriber):
    """Mock all external dependencies of run_audio_preview."""
    from ir_storyboard.ingest.loaders.audio_chunker import AudioChunk
    stack.enter_context(patch(
        "ir_storyboard.ingest.audio_pipeline._probe_duration",
        return_value=65.0,
    ))
    stack.enter_context(patch(
        "ir_storyboard.ingest.audio_pipeline.get_transcriber",
        return_value=transcriber,
    ))
    stack.enter_context(patch(
        "ir_storyboard.ingest.loaders.transcriber.split_audio",
        side_effect=lambda p, **kw: [AudioChunk(path=p, chunk_start_sec=0.0, chunk_end_sec=65.0)],
    ))
    stack.enter_context(patch(
        "ir_storyboard.ingest.youtube_pipeline.extract_facts_from_transcript",
        return_value=(_mock_extracted_facts(), []),
    ))
    stack.enter_context(patch(
        "ir_storyboard.ingest.youtube_pipeline.summarize_youtube_preview",
        return_value={"video_brief": "", "cell_briefs": {}},
    ))


# ── pipeline tests ─────────────────────────────────────────────────────────────


def test_preview_audit_kind_and_anchors(tmp_path, audio_file):
    from ir_storyboard.ingest.audio_pipeline import run_audio_preview, file_sha256

    conn = _make_conn(tmp_path)
    transcriber = MockTranscriber()

    with ExitStack() as stack:
        _pipeline_patches(stack, transcriber)
        preview = run_audio_preview("test_founder", audio_file, "", conn)

    sha = file_sha256(audio_file)

    # Meta: title defaults to the file name, canonical_url is file://sha16
    assert preview.meta.title == "interview.m4a"
    assert preview.meta.canonical_url == f"file://{sha[:16]}"
    assert preview.meta.channel_name == "audio upload"
    assert preview.meta.duration_sec == 65
    assert preview.from_cache is False
    assert transcriber.calls == 1

    # Facts: L2/L7 allowed, snippet present, no per-fact URL for file uploads
    assert len(preview.facts) == 2
    for f in preview.facts:
        assert f.source_url == ""
        assert len(f.evidence_snippet.strip()) >= 20

    # LayerGuard: the 8.2 fact must be skipped (online_interview channel)
    assert len(preview.skipped) == 1
    assert preview.skipped[0].fact.subsection_id == "8.2"

    # Audit row: ingest_kind='audio_file', source_artifact = file:// url
    row = conn.execute(
        "SELECT * FROM ingest_audit WHERE id = ?", (preview.preview_id,)
    ).fetchone()
    assert row is not None
    assert row["ingest_kind"] == "audio_file"
    assert row["source_artifact"] == f"file://{sha[:16]}"
    assert row["transcriber"] == "mock-transcriber"
    assert row["video_id"] == sha[:16]
    data = json.loads(row["preview_json"])
    assert data["channel"] == "online_interview"


def test_sha_cache_second_preview_from_cache(tmp_path, audio_file):
    from ir_storyboard.ingest.audio_pipeline import run_audio_preview, file_sha256

    conn = _make_conn(tmp_path)
    transcriber = MockTranscriber()

    with ExitStack() as stack:
        _pipeline_patches(stack, transcriber)
        first = run_audio_preview("test_founder", audio_file, "Talk #1", conn)
        second = run_audio_preview("test_founder", audio_file, "Talk #1", conn)

    assert first.from_cache is False
    assert second.from_cache is True
    # Transcribed exactly once — second run served from audio_transcripts
    assert transcriber.calls == 1
    assert any("cache" in n for n in second.notes)

    sha = file_sha256(audio_file)
    row = conn.execute(
        "SELECT transcriber, duration_sec FROM audio_transcripts WHERE file_sha256 = ?",
        (sha,),
    ).fetchone()
    assert row is not None
    assert row["transcriber"] == "mock-transcriber"
    assert row["duration_sec"] == 65


def test_commit_writes_facts_to_matrix(tmp_path, audio_file):
    from ir_storyboard import matrix
    from ir_storyboard.ingest.audio_pipeline import (
        run_audio_preview, run_audio_commit, file_sha256,
    )

    conn = _make_conn(tmp_path)
    transcriber = MockTranscriber()

    with ExitStack() as stack:
        _pipeline_patches(stack, transcriber)
        preview = run_audio_preview("test_founder", audio_file, "Founder Talk", conn)

    commit = run_audio_commit(
        preview_id=preview.preview_id,
        accepted_fact_ids=list(range(len(preview.facts))),
        overrides=[],
        conn=conn,
        expert_email="expert@example.com",
    )
    assert commit.committed == 2

    # Source row: online_interview channel, file:// url, custom title
    sha = file_sha256(audio_file)
    src = conn.execute(
        "SELECT * FROM sources WHERE url = ?", (f"file://{sha[:16]}",)
    ).fetchone()
    assert src is not None
    assert src["channel"] == "online_interview"
    assert src["title"] == "Founder Talk"

    facts_21 = matrix.facts_for_cell(conn, "test_founder", "2.1")
    assert any("Bitfury" in f["text"] for f in facts_21)

    # Audit updated
    row = conn.execute(
        "SELECT facts_committed, expert_email FROM ingest_audit WHERE id = ?",
        (preview.preview_id,),
    ).fetchone()
    assert row["facts_committed"] == 2
    assert row["expert_email"] == "expert@example.com"

    # Replay → idempotent, 0 new facts
    replay = run_audio_commit(
        preview_id=preview.preview_id,
        accepted_fact_ids=list(range(len(preview.facts))),
        overrides=[],
        conn=conn,
    )
    assert replay.committed == 0


# ── API tests ──────────────────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path):
    """TestClient with isolated file-based SQLite DB (thread-safe)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from ir_storyboard import db as _db, matrix
    from backend.main import app, get_conn

    db_path = tmp_path / "test_audio.db"

    def _override_conn():
        conn = _db.connect(db_path)
        _db.init_schema(conn)
        matrix.seed_layers(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = _override_conn

    conn = _db.connect(db_path)
    _db.init_schema(conn)
    matrix.seed_layers(conn)
    matrix.upsert_client(conn, "test_client", "Test Client", sector="test")
    conn.close()

    with TestClient(app) as tc:
        yield tc

    app.dependency_overrides.clear()


def _fake_audio_preview_result(title="Interview"):
    from ir_storyboard.ingest.audio_pipeline import AudioFileMeta
    from ir_storyboard.ingest.snippet_anchor import AnchoredFact
    from ir_storyboard.ingest.youtube_pipeline import YouTubePreviewResult

    meta = AudioFileMeta(
        video_id="abc123def4567890",
        canonical_url="file://abc123def4567890",
        title=title,
        duration_sec=65,
    )
    facts = [
        AnchoredFact(
            text="Founder joined Bitfury in 2014 as an early engineer.",
            subsection_id="2.1",
            flag="green",
            confidence=0.9,
            evidence_snippet="I joined Bitfury in 2014 as one of the early engineers there.",
            source_url="",
            snippet_start_sec=4.1,
            snippet_end_sec=9.0,
        ),
    ]
    return YouTubePreviewResult(
        preview_id="audio-preview-id-1",
        meta=meta,
        facts=facts,
        skipped=[],
        notes=[],
        stats={"facts_emitted": 1, "greys": 0, "channel_warnings": 0},
        from_cache=False,
        transcribe_cost_usd=None,
    )


def _poll_job(client, job_id, timeout_sec=5.0):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        resp = client.get(f"/api/clients/test_client/ingest/audio/preview/{job_id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        if data["status"] != "processing":
            return data
        time.sleep(0.05)
    pytest.fail("audio preview job did not finish in time")


def test_api_preview_job_flow(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIO_UPLOADS_DIR", str(tmp_path / "uploads"))

    with patch(
        "ir_storyboard.db.DEFAULT_DB_PATH", tmp_path / "jobs.db",
    ), patch(
        "ir_storyboard.ingest.audio_pipeline.run_audio_preview",
        return_value=_fake_audio_preview_result(),
    ):
        resp = client.post(
            "/api/clients/test_client/ingest/audio/preview",
            files={"file": ("interview.m4a", b"fake-audio-bytes", "audio/mp4")},
            data={"title": "Interview"},
        )
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        assert resp.json()["status"] == "processing"

        data = _poll_job(client, job_id)

    assert data["status"] == "done", data.get("error")
    result = data["result"]
    assert result["preview_id"] == "audio-preview-id-1"
    assert result["meta"]["title"] == "Interview"
    assert result["meta"]["channel_name"] == "audio upload"
    assert result["meta"]["canonical_url"].startswith("file://")
    assert len(result["facts"]) == 1
    assert result["facts"][0]["source_url"] == ""


def test_api_rejects_unsupported_extension(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIO_UPLOADS_DIR", str(tmp_path / "uploads"))
    resp = client.post(
        "/api/clients/test_client/ingest/audio/preview",
        files={"file": ("notes.txt", b"not audio", "text/plain")},
    )
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.text


def test_api_rejects_empty_file(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIO_UPLOADS_DIR", str(tmp_path / "uploads"))
    resp = client.post(
        "/api/clients/test_client/ingest/audio/preview",
        files={"file": ("empty.mp3", b"", "audio/mpeg")},
    )
    assert resp.status_code == 400


def test_api_upload_dedup_by_sha(client, tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    monkeypatch.setenv("AUDIO_UPLOADS_DIR", str(uploads))

    content = b"identical audio content uploaded twice"
    with patch(
        "ir_storyboard.db.DEFAULT_DB_PATH", tmp_path / "jobs.db",
    ), patch(
        "ir_storyboard.ingest.audio_pipeline.run_audio_preview",
        return_value=_fake_audio_preview_result(),
    ):
        for _ in range(2):
            resp = client.post(
                "/api/clients/test_client/ingest/audio/preview",
                files={"file": ("talk.mp3", content, "audio/mpeg")},
            )
            assert resp.status_code == 202, resp.text
            _poll_job(client, resp.json()["job_id"])

    stored = list(uploads.glob("*.mp3"))
    assert len(stored) == 1, f"expected sha-dedup to keep one file, got {stored}"
    import hashlib
    assert stored[0].name == hashlib.sha256(content).hexdigest() + ".mp3"


def test_api_commit_endpoint(client, tmp_path):
    """Commit endpoint writes previewed audio facts via the shared commit core."""
    import sqlite3 as _sq
    from ir_storyboard.ingest.youtube_pipeline import (
        _ensure_audit_table_youtube, _anchored_to_dict,
    )

    preview_result = _fake_audio_preview_result()

    db_path = tmp_path / "test_audio.db"
    conn = _sq.connect(str(db_path))
    conn.row_factory = _sq.Row
    _ensure_audit_table_youtube(conn)
    preview_json = json.dumps({
        "preview_id": preview_result.preview_id,
        "video_id": preview_result.meta.video_id,
        "canonical_url": preview_result.meta.canonical_url,
        "channel": "online_interview",
        "facts": [_anchored_to_dict(f) for f in preview_result.facts],
        "skipped": [],
        "stats": preview_result.stats,
        "notes": [],
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
           VALUES (?, 'test_client', 'audio_file', ?, 'mock-transcriber',
                   CURRENT_TIMESTAMP, 1, 0, 0, 0, '', CURRENT_TIMESTAMP, ?, ?,
                   'mock-transcriber')""",
        (
            preview_result.preview_id,
            preview_result.meta.canonical_url,
            preview_json,
            preview_result.meta.video_id,
        ),
    )
    conn.commit()
    conn.close()

    resp = client.post(
        "/api/clients/test_client/ingest/audio/commit",
        json={
            "preview_id": preview_result.preview_id,
            "accepted_fact_ids": [0],
            "overrides": [],
            "expert_email": "test@example.com",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["committed"] == 1

    # Source row created with the file:// url and online_interview channel
    conn = _sq.connect(str(db_path))
    conn.row_factory = _sq.Row
    src = conn.execute(
        "SELECT channel, url FROM sources WHERE url = ?",
        (preview_result.meta.canonical_url,),
    ).fetchone()
    assert src is not None
    assert src["channel"] == "online_interview"
    conn.close()
