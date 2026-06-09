"""Tests for polish-2: rationale validation + extractor prompt block."""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix, llm
from ir_storyboard.matrix import validate_rationale


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test_rationale.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "acme", "Acme")
    matrix.ensure_full_grid(c, "acme")
    yield c
    c.close()


@pytest.fixture
def api(tmp_path):
    from backend.main import app, get_conn

    db_path = tmp_path / "test_rationale_api.db"

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
    matrix.upsert_client(init, "acme", "Acme")
    matrix.ensure_full_grid(init, "acme")
    init.close()
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


# ── validate_rationale unit tests ──────────────────────────────────────────

def test_validate_rationale_red_requires_text():
    with pytest.raises(ValueError, match="red fact requires rationale"):
        validate_rationale("red", "")
    with pytest.raises(ValueError):
        validate_rationale("red", "   ")
    with pytest.raises(ValueError):
        validate_rationale("red", None)


def test_validate_rationale_grey_optional():
    assert validate_rationale("grey", "") == ""
    assert validate_rationale("grey", None) == ""
    assert validate_rationale("grey", " explanatory note ") == "explanatory note"


def test_validate_rationale_green_silently_drops():
    assert validate_rationale("green", "should be removed") == ""
    assert validate_rationale("green", "") == ""
    assert validate_rationale("green", None) == ""


def test_validate_rationale_red_with_text_returns_stripped():
    assert validate_rationale("red", "  concern explanation  ") == "concern explanation"


# ── matrix.add_fact / update_fact ──────────────────────────────────────────

def test_add_fact_red_without_rationale_raises(conn):
    matrix.add_source(conn, channel="online_research",
                      title="t", url="https://example.com/x",
                      archive_url="")
    src_id = conn.execute("SELECT id FROM sources ORDER BY id DESC LIMIT 1").fetchone()["id"]
    with pytest.raises(ValueError, match="rationale"):
        matrix.add_fact(conn, client_id="acme", subsection_id="2.1",
                        text="X", flag="red", source_id=src_id,
                        evidence_snippet="some evidence text exceeding 20 chars",
                        rationale=None)


def test_add_fact_red_with_rationale_succeeds(conn):
    src_id = matrix.add_source(conn, channel="online_research",
                               title="t", url="https://example.com/x")
    fid = matrix.add_fact(conn, client_id="acme", subsection_id="2.1",
                          text="X", flag="red", source_id=src_id,
                          evidence_snippet="some evidence text exceeding 20 chars",
                          rationale="Founder concealed material conflict of interest.")
    row = matrix.get_fact(conn, fid)
    assert row["rationale"] == "Founder concealed material conflict of interest."


def test_add_fact_green_with_rationale_silently_drops(conn):
    src_id = matrix.add_source(conn, channel="online_research",
                               title="t", url="https://example.com/x")
    fid = matrix.add_fact(conn, client_id="acme", subsection_id="2.1",
                          text="X", flag="green", source_id=src_id,
                          evidence_snippet="some evidence text exceeding 20 chars",
                          rationale="irrelevant")
    row = matrix.get_fact(conn, fid)
    assert row["rationale"] == ""


def test_update_fact_set_rationale(conn):
    src_id = matrix.add_source(conn, channel="online_research",
                               title="t", url="https://example.com/x")
    fid = matrix.add_fact(conn, client_id="acme", subsection_id="2.1",
                          text="X", flag="red", source_id=src_id,
                          evidence_snippet="some evidence text exceeding 20 chars",
                          rationale="initial concern")
    matrix.update_fact(conn, fid, rationale="updated concern explanation")
    row = matrix.get_fact(conn, fid)
    assert row["rationale"] == "updated concern explanation"


def test_update_fact_flag_red_without_existing_rationale_raises(conn):
    src_id = matrix.add_source(conn, channel="online_research",
                               title="t", url="https://example.com/x")
    fid = matrix.add_fact(conn, client_id="acme", subsection_id="2.1",
                          text="X", flag="green", source_id=src_id,
                          evidence_snippet="some evidence text exceeding 20 chars")
    with pytest.raises(ValueError, match="rationale"):
        matrix.update_fact(conn, fid, flag="red")


def test_update_fact_text_only_does_not_revalidate_rationale(conn):
    """Existing red facts with empty rationale (legacy) can have their text updated."""
    src_id = matrix.add_source(conn, channel="online_research",
                               title="t", url="https://example.com/x")
    fid = matrix.add_fact(conn, client_id="acme", subsection_id="2.1",
                          text="X", flag="green", source_id=src_id,
                          evidence_snippet="some evidence text exceeding 20 chars")
    # Simulate legacy red fact (was inserted before validation existed)
    conn.execute("UPDATE facts SET flag='red', rationale='' WHERE id=?", (fid,))
    conn.commit()
    # text-only update should NOT trigger rationale validation
    matrix.update_fact(conn, fid, text="updated text")


# ── API endpoint validation ────────────────────────────────────────────────

def test_api_red_fact_without_rationale_returns_422(api):
    resp = api.post(
        "/api/clients/acme/cells/2.1/facts",
        json={
            "text": "Founder evaded a regulatory disclosure obligation.",
            "flag": "red",
            "channel": "online_research",
            "source_url": "https://example.com/article",
            "source_title": "Investigation",
            "evidence_snippet": "He refused to file the required disclosure when asked.",
        },
    )
    assert resp.status_code == 422
    assert "rationale" in resp.text.lower()


def test_api_red_fact_with_rationale_succeeds(api):
    resp = api.post(
        "/api/clients/acme/cells/2.1/facts",
        json={
            "text": "Founder evaded a regulatory disclosure obligation.",
            "flag": "red",
            "channel": "online_research",
            "source_url": "https://example.com/article",
            "source_title": "Investigation",
            "evidence_snippet": "He refused to file the required disclosure when asked.",
            "rationale": "Avoided mandatory filings; signals governance risk for IPO timing.",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rationale"].startswith("Avoided mandatory filings")


def test_api_patch_fact_rationale(api):
    # create green fact, then PATCH to red+rationale
    create = api.post(
        "/api/clients/acme/cells/2.1/facts",
        json={
            "text": "Initial green fact.",
            "flag": "green",
            "channel": "online_research",
            "source_url": "https://example.com/x",
            "source_title": "S",
            "evidence_snippet": "Initial green fact evidence quote.",
        },
    )
    assert create.status_code == 200, create.text
    fact_id = create.json()["id"]

    resp = api.patch(
        f"/api/facts/{fact_id}",
        json={"flag": "red", "rationale": "Reclassified as red after new evidence."},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["flag"] == "red"
    assert "new evidence" in resp.json()["rationale"]


def test_api_patch_flag_to_red_without_rationale_422(api):
    create = api.post(
        "/api/clients/acme/cells/2.1/facts",
        json={
            "text": "Initial green fact.",
            "flag": "green",
            "channel": "online_research",
            "source_url": "https://example.com/x",
            "source_title": "S",
            "evidence_snippet": "Initial green fact evidence quote.",
        },
    )
    fact_id = create.json()["id"]
    resp = api.patch(f"/api/facts/{fact_id}", json={"flag": "red"})
    assert resp.status_code == 422


def test_existing_red_with_empty_rationale_round_trips(conn):
    """Legacy red facts (rationale='') survive GET without exploding."""
    src_id = matrix.add_source(conn, channel="online_research",
                               title="t", url="https://example.com/x")
    fid = matrix.add_fact(conn, client_id="acme", subsection_id="2.1",
                          text="X", flag="green", source_id=src_id,
                          evidence_snippet="some evidence text exceeding 20 chars")
    # Simulate legacy: flag flipped to red with empty rationale (pre-polish row)
    conn.execute("UPDATE facts SET flag='red', rationale='' WHERE id=?", (fid,))
    conn.commit()
    row = matrix.get_fact(conn, fid)
    assert row["flag"] == "red"
    assert (row["rationale"] or "") == ""


# ── Prompt smoke ───────────────────────────────────────────────────────────

def test_extractor_prompts_include_rationale_block():
    """All three prompt templates carry the __RATIONALE_RULES__ placeholder
    and the constant defines red/grey/green rules."""
    assert "RATIONALE field rules" in llm._RATIONALE_RULES
    assert 'red"' in llm._RATIONALE_RULES
    assert 'green"' in llm._RATIONALE_RULES
    for tmpl in (llm._BATCH_EXTRACT_SYSTEM_TMPL,
                 llm._EXTRACT_SYSTEM_TMPL,
                 llm._TRANSCRIPT_CHUNK_SYSTEM,
                 llm._RESEARCH_EXTRACT_SYSTEM):
        assert "__RATIONALE_RULES__" in tmpl, "prompt template missing rationale placeholder"
        assert '"rationale"' in tmpl, "prompt JSON example missing rationale field"
