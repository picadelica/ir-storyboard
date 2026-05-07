"""Tests for Task 2: source provenance enforcement."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix
from ir_storyboard.matrix import validate_provenance


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "acme", "Acme")
    matrix.ensure_full_grid(c, "acme")
    yield c
    c.close()


# ── validate_provenance unit tests ──────────────────────────────────────────

def test_online_research_requires_url():
    with pytest.raises(ValueError, match="source_url"):
        validate_provenance("online_research", "", "A" * 25)


def test_online_research_requires_https_prefix():
    with pytest.raises(ValueError, match="http"):
        validate_provenance("online_research", "ftp://example.com", "A" * 25)


def test_online_research_requires_snippet_20chars():
    with pytest.raises(ValueError, match="evidence_snippet"):
        validate_provenance("online_research", "https://example.com", "short")


def test_online_research_valid():
    # should not raise
    validate_provenance("online_research", "https://example.com", "A" * 25)


def test_archival_requires_snippet():
    with pytest.raises(ValueError, match="evidence_snippet"):
        validate_provenance("archival", "https://example.com", "tiny")


def test_online_interview_requires_snippet():
    with pytest.raises(ValueError, match="evidence_snippet"):
        validate_provenance("online_interview", "https://example.com", "")


def test_offline_interview_requires_title():
    with pytest.raises(ValueError, match="source_title"):
        validate_provenance("offline_interview", "", "", source_title="")


def test_offline_interview_no_snippet_ok():
    # snippet is optional for offline
    validate_provenance("offline_interview", "", "", source_title="Interview with X 2026-05-07")


def test_offline_interview_internal_url_ok():
    validate_provenance("offline_interview", "internal://rec-001", "",
                        source_title="Interview with X 2026-05-07")


# ── matrix.add_fact stores evidence_snippet ─────────────────────────────────

def test_add_fact_stores_evidence_snippet(conn):
    src_id = matrix.add_source(conn, channel="archival",
                               title="Wikipedia", url="https://en.wikipedia.org/wiki/Test")
    fid = matrix.add_fact(conn, client_id="acme", subsection_id="2.1",
                          text="Some fact", flag="green", source_id=src_id,
                          evidence_snippet="This is a long enough evidence snippet.")
    row = matrix.get_fact(conn, fid)
    assert row["evidence_snippet"] == "This is a long enough evidence snippet."


# ── grey flag: snippet optional even for online channels ────────────────────

def test_grey_fact_snippet_optional():
    # grey = "we know we don't know" — snippet optional even for online channels
    validate_provenance("online_research", "https://example.com", "", flag="grey")
    # but URL is still required for online channels even for grey
    with pytest.raises(ValueError, match="http"):
        validate_provenance("online_research", "", "", flag="grey")


# ── API smoke: POST fact with bad payload → 422 ──────────────────────────────

def test_api_bad_provenance_returns_422():
    from fastapi.testclient import TestClient
    import sys
    sys.path.insert(0, str(ROOT))
    from backend.main import app
    client = TestClient(app)

    # seed accumulator so client exists
    client.post("/api/clients/accumulator/seed-accumulator")

    resp = client.post(
        "/api/clients/accumulator/cells/2.1/facts",
        json={
            "text": "Some fact",
            "flag": "green",
            "channel": "online_research",
            "source_url": "",          # missing URL
            "evidence_snippet": "",    # missing snippet
        },
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "source_url" in str(body).lower() or "http" in str(body).lower()


def test_api_valid_fact_returns_201_or_200():
    from fastapi.testclient import TestClient
    import sys
    sys.path.insert(0, str(ROOT))
    from backend.main import app
    client = TestClient(app)

    client.post("/api/clients/accumulator/seed-accumulator")

    resp = client.post(
        "/api/clients/accumulator/cells/2.1/facts",
        json={
            "text": "Patrick Collison founded Stripe in 2010.",
            "flag": "green",
            "channel": "online_research",
            "source_url": "https://en.wikipedia.org/wiki/Stripe_(company)",
            "source_title": "Stripe — Wikipedia",
            "evidence_snippet": "Stripe was founded in 2010 by Irish entrepreneurs Patrick and John Collison.",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["evidence_snippet"] == "Stripe was founded in 2010 by Irish entrepreneurs Patrick and John Collison."
