"""Two-step online research: queries are generated for analyst review first,
then search runs on the (possibly edited) queries. Offline (web_search mocked)."""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix, llm


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    import backend.main as M
    db_path = tmp_path / "research.db"

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
    matrix.upsert_client(init, "co", "Gonka AI", founder_name="Daniil Liberman", sector="ai")
    init.close()
    yield M, TestClient(M.app)
    M.app.dependency_overrides.clear()


def test_queries_generated_without_searching(ctx, monkeypatch):
    M, client = ctx
    called = {"n": 0}
    monkeypatch.setattr(M, "web_search", lambda q, max_hits=4: called.__setitem__("n", called["n"] + 1) or [])
    qs = client.post("/api/clients/co/research/queries").json()["queries"]
    assert any("Gonka AI" in q for q in qs)          # built from the client
    assert any("Daniil Liberman" in q for q in qs)   # founder combined in
    assert called["n"] == 0                           # step 1 must NOT search


def test_search_uses_edited_queries(ctx, monkeypatch):
    M, client = ctx
    seen = []
    monkeypatch.setattr(M, "web_search", lambda q, max_hits=4: seen.append(q) or
                        [llm.SearchHit(title="t", url=f"https://x.test/{len(seen)}", snippet="s")])
    edited = ['"Gonka AI" наградах 2026', 'gonka ai team']
    res = client.post("/api/clients/co/research", json={"queries": edited}).json()
    assert seen == edited                              # searched exactly the analyst's queries
    assert res["queries_used"] == edited
    assert len(res["hits"]) == 2


def test_search_without_body_autobuilds(ctx, monkeypatch):
    M, client = ctx
    seen = []
    monkeypatch.setattr(M, "web_search", lambda q, max_hits=4: seen.append(q) or [])
    client.post("/api/clients/co/research", json={})
    assert any("Gonka AI" in q for q in seen)          # back-compat: auto-built queries
