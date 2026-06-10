"""Backend smoke for polish-4: facts written through each provenance class
round-trip the fields SourceLine renders against (channel, source_url,
source_title, source_archive_url, ingest_audit_id, captured_at).

The frontend SourceLine component switches render branches off these fields,
so this test guards the API contract the component depends on.
"""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix


@pytest.fixture
def api(tmp_path):
    from backend.main import app, get_conn

    db_path = tmp_path / "source_line.db"

    def _override():
        conn = db.connect(db_path)
        db.init_schema(conn)
        matrix.seed_layers(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = _override
    init = db.connect(db_path)
    db.init_schema(init)
    matrix.seed_layers(init)
    matrix.upsert_client(init, "src_co", "Source Co")
    matrix.ensure_full_grid(init, "src_co")
    init.close()

    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


def _post_fact(api, *, channel, source_url, source_title, snippet, flag="green"):
    return api.post(
        "/api/clients/src_co/cells/2.1/facts",
        json={
            "text": f"Fact for {channel}",
            "flag": flag,
            "channel": channel,
            "source_url": source_url,
            "source_title": source_title,
            "evidence_snippet": snippet,
        },
    )


def test_web_provenance_round_trip(api):
    resp = _post_fact(
        api,
        channel="online_research",
        source_url="https://example.com/article",
        source_title="Example Article",
        snippet="The founder publicly stated their intent in this article.",
    )
    assert resp.status_code == 200, resp.text
    fact = resp.json()
    assert fact["source_url"] == "https://example.com/article"
    assert fact["source_channel"] == "online_research"
    assert fact["source_title"] == "Example Article"
    assert fact["captured_at"]


def test_offline_provenance_round_trip(api):
    resp = _post_fact(
        api,
        channel="offline_interview",
        source_url="",
        source_title="Interview with Founder 2026-05-12",
        snippet="",  # offline does not require snippet
    )
    assert resp.status_code == 200, resp.text
    fact = resp.json()
    assert (fact["source_url"] or "") == ""
    assert fact["source_channel"] == "offline_interview"
    assert fact["source_title"] == "Interview with Founder 2026-05-12"


def test_internal_pseudo_url_hidden_but_audit_exposed(api, tmp_path):
    """internal:// URLs stay hidden in the response (so SourceLine routes via
    ingest_audit_id instead of trying to render them as web links)."""
    from ir_storyboard import db as _db
    db_path = list((tmp_path).glob("source_line.db"))[0]
    conn = _db.connect(db_path)

    src_id = matrix.add_source(
        conn,
        channel="archival",
        title="LLM Report: foo.docx",
        url="internal://llm_report/abc123",
    )
    fid = matrix.add_fact(
        conn, client_id="src_co", subsection_id="2.1",
        text="From a paraphrased LLM report fact.",
        flag="green",
        source_id=src_id,
        evidence_snippet="Paraphrased sentence from the LLM report fact.",
    )
    conn.execute(
        "UPDATE facts SET ingest_audit_id = ? WHERE id = ?",
        ("abc123", fid),
    )
    conn.commit()
    conn.close()

    facts = api.get("/api/clients/src_co/cells/2.1/facts").json()
    target = next(f for f in facts if f["id"] == fid)
    assert target["source_url"] is None, \
        "internal:// URL must stay hidden so SourceLine takes the llm_report branch"
    assert target["ingest_audit_id"] == "abc123"
    assert target["source_channel"] == "archival"


def test_missing_provenance_renders_as_anomaly(api, tmp_path):
    """A fact with no http source_url and no ingest_audit_id should still
    round-trip — SourceLine renders ⚠ no source for these legacy rows."""
    from ir_storyboard import db as _db
    db_path = list((tmp_path).glob("source_line.db"))[0]
    conn = _db.connect(db_path)

    src_id = matrix.add_source(
        conn,
        channel="archival",
        title="",
        url="",
    )
    fid = matrix.add_fact(
        conn, client_id="src_co", subsection_id="2.1",
        text="Orphan fact with no provenance.",
        flag="green",
        source_id=src_id,
        evidence_snippet="Some evidence quote long enough to clear minimum.",
    )
    conn.commit()
    conn.close()

    facts = api.get("/api/clients/src_co/cells/2.1/facts").json()
    target = next(f for f in facts if f["id"] == fid)
    assert (target["source_url"] or "") == ""
    assert not target.get("ingest_audit_id")
