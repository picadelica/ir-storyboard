"""Universal add-data API.

These tests deliberately mock LLM and network pieces:
- preview endpoints must be safe/offline and must not write to DB;
- URL preview must reject private/local addresses before fetching;
- final DB writes still happen only through explicit confirm endpoints.
"""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, llm, matrix


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    import backend.main as M

    db_path = tmp_path / "universal_ingest.db"

    def _override():
        conn = db.connect(db_path)
        db.init_schema(conn)
        try:
            yield conn
        finally:
            conn.close()

    M.app.dependency_overrides[M.get_conn] = _override
    init = db.connect(db_path)
    db.init_schema(init)
    matrix.seed_layers(init)
    matrix.upsert_client(init, "co", "Test Company", sector="saas")
    matrix.ensure_full_grid(init, "co")
    init.close()

    # Keep tests deterministic: no async archive jobs and no work-item synthesis noise.
    monkeypatch.setattr(M, "enqueue_save", lambda *a, **k: None)
    monkeypatch.setattr(M, "lookup_snapshot", lambda *a, **k: "")
    monkeypatch.setattr(M, "synthesize_work_items", lambda *a, **k: [])

    yield M, TestClient(M.app), db_path
    M.app.dependency_overrides.clear()


def _fact(text="Company has a clear growth story.", sid="6.1", flag="green"):
    return llm.ExtractedFact(
        text=text,
        subsection_id=sid,
        flag=flag,
        confidence=0.91,
        raw_paraphrase=text,
        rationale="mocked extraction",
    )


def _counts(db_path: Path) -> tuple[int, int]:
    conn = db.connect(db_path)
    try:
        facts = conn.execute("SELECT count(*) FROM facts").fetchone()[0]
        sources = conn.execute("SELECT count(*) FROM sources").fetchone()[0]
        return facts, sources
    finally:
        conn.close()


def test_universal_text_preview_does_not_write_db(ctx, monkeypatch):
    _, client, db_path = ctx
    monkeypatch.setattr(llm, "extract_facts_from_research_text", lambda **kwargs: [
        _fact("Client says onboarding takes less than one day.", "1.1"),
    ])

    before = _counts(db_path)
    resp = client.post("/api/clients/co/ingest/universal/text/preview", json={
        "text": "Client says onboarding takes less than one day.",
        "source_status": "client",
        "source_title": "Client note",
    })

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["channel"] == "offline_interview"
    assert body["source_title"] == "Client note"
    assert body["candidates"][0]["suggested_subsection_id"] == "1.1"
    assert _counts(db_path) == before == (0, 0)


def test_universal_url_blocks_private_addresses(ctx):
    _, client, db_path = ctx

    resp = client.post("/api/clients/co/ingest/universal/url/preview", json={
        "url": "http://127.0.0.1:8000/secret",
        "source_status": "regular",
    })

    assert resp.status_code == 422
    assert "внутреннюю сеть" in resp.text
    assert _counts(db_path) == (0, 0)


def test_universal_url_preview_extracts_page_without_writing_db(ctx, monkeypatch):
    M, client, db_path = ctx
    html = (
        b"<html><head><title>Example Research</title></head>"
        b"<body><article>Company launched a product for founders and improved retention by 30 percent.</article></body></html>"
    )
    monkeypatch.setattr(M, "_fetch_url_payload", lambda url: (
        html,
        "text/html; charset=utf-8",
        "https://example.com/research",
    ))
    monkeypatch.setattr(llm, "extract_facts_from_research_text", lambda **kwargs: [
        _fact("Company improved retention by 30 percent.", "6.3"),
    ])

    before = _counts(db_path)
    resp = client.post("/api/clients/co/ingest/universal/url/preview", json={
        "url": "https://example.com/research",
        "source_status": "regular",
    })

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["channel"] == "online_research"
    assert body["source_url"] == "https://example.com/research"
    assert body["source_title"] == "Example Research"
    assert body["candidates"][0]["suggested_subsection_id"] == "6.3"
    assert _counts(db_path) == before == (0, 0)


@pytest.mark.parametrize(("filename", "helper_name"), [
    ("research.docx", "_docx_bytes_to_text"),
    ("client-notes.rtf", "_rtf_bytes_to_text"),
])
def test_universal_document_file_preview_without_writing_db(ctx, monkeypatch, filename, helper_name):
    M, client, db_path = ctx
    monkeypatch.setattr(M, helper_name, lambda raw: "Company expanded into a new founder segment with strong demand.")
    monkeypatch.setattr(llm, "extract_facts_from_research_text", lambda **kwargs: [
        _fact("Company expanded into a new founder segment.", "6.2"),
    ])

    before = _counts(db_path)
    with open(__file__, "rb") as f:
        resp = client.post(
            "/api/clients/co/ingest/universal/file/preview",
            data={"source_status": "regular"},
            files={"file": (filename, f, "application/octet-stream")},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["channel"] == "online_research"
    assert body["source_title"] == filename
    assert body["candidates"][0]["suggested_subsection_id"] == "6.2"
    assert _counts(db_path) == before == (0, 0)


def test_ingest_confirm_writes_only_explicit_valid_facts(ctx):
    _, client, db_path = ctx

    resp = client.post("/api/clients/co/ingest/confirm", json={
        "facts": [
            {
                "text": "Company improved retention by 30 percent.",
                "subsection_id": "6.3",
                "flag": "green",
                "channel": "online_research",
                "source_url": "https://example.com/research",
                "source_title": "Example Research",
                "evidence_snippet": "Company improved retention by 30 percent.",
                "confidence": 0.9,
            },
            {
                # Invalid online provenance: no URL, so confirm must skip it.
                "text": "This candidate was not explicitly accepted with provenance.",
                "subsection_id": "6.2",
                "flag": "green",
                "channel": "online_research",
                "source_url": "",
                "source_title": "No URL",
                "evidence_snippet": "This candidate was not explicitly accepted with provenance.",
                "confidence": 0.9,
            },
        ],
    })

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["written"]) == 1
    assert body["skipped"] == 1

    conn = db.connect(db_path)
    try:
        facts = conn.execute(
            """SELECT f.text, c.subsection_id, s.url, s.title
               FROM facts f
               JOIN cells c ON c.id = f.cell_id
               JOIN sources s ON s.id = f.source_id"""
        ).fetchall()
        assert len(facts) == 1
        row = dict(facts[0])
        assert row["subsection_id"] == "6.3"
        assert row["url"] == "https://example.com/research"
        assert row["title"] == "Example Research"
    finally:
        conn.close()
