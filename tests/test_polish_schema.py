"""Tests for polish-1: schema migrations + ClientOut.created_at exposure."""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test_polish.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    yield c
    c.close()


@pytest.fixture
def api(tmp_path):
    from backend.main import app, get_conn

    db_path = tmp_path / "test_polish_api.db"

    def _override():
        conn = db.connect(db_path)
        db.init_schema(conn)
        matrix.seed_layers(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = _override
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


def _cols(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_facts_has_rationale_column(conn):
    assert "rationale" in _cols(conn, "facts")


def test_facts_has_created_by_column(conn):
    assert "created_by" in _cols(conn, "facts")


def test_clients_has_created_by_column(conn):
    assert "created_by" in _cols(conn, "clients")


def test_idempotent_re_init(tmp_path):
    """init_schema is safe to run twice — both times exit clean."""
    db_path = tmp_path / "twice.db"
    c1 = db.connect(db_path)
    db.init_schema(c1)
    c1.close()
    c2 = db.connect(db_path)
    db.init_schema(c2)
    cols = _cols(c2, "facts")
    assert "rationale" in cols
    assert "created_by" in cols
    c2.close()


def test_client_out_includes_created_at(api):
    api.post("/api/clients", json={"id": "polish_co", "name": "Polish Co"})
    resp = api.get("/api/clients/polish_co")
    assert resp.status_code == 200
    body = resp.json()
    assert body["created_at"], "ClientOut should expose created_at"
    assert body["created_by"] is None


def test_fact_out_includes_rationale_and_created_by(api, tmp_path):
    api.post("/api/clients", json={"id": "polish_fc", "name": "Polish FC"})
    payload = {
        "text": "Founded Stripe in 2010.",
        "flag": "green",
        "channel": "online_research",
        "source_url": "https://en.wikipedia.org/wiki/Stripe_(company)",
        "source_title": "Wikipedia",
        "evidence_snippet": "Stripe was founded in 2010 by Patrick and John Collison.",
    }
    resp = api.post("/api/clients/polish_fc/cells/2.1/facts", json=payload)
    assert resp.status_code in (200, 201)

    resp = api.get("/api/clients/polish_fc/cells/2.1/facts")
    assert resp.status_code == 200
    facts = resp.json()
    assert len(facts) == 1
    f = facts[0]
    assert "rationale" in f
    assert f["rationale"] == ""
    assert "created_by" in f
    assert f["created_by"] is None
