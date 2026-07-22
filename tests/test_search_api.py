"""Поиск по фактам: matrix.search_facts (кириллица регистронезависимо, скоуп)
+ GET /api/search (client vs all). Скрытые дубли не в выдаче. Offline."""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "search.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    for cid, name in [("co", "Acme Co"), ("co2", "Beta Inc")]:
        matrix.upsert_client(c, cid, name)
        matrix.ensure_full_grid(c, cid)
    matrix.add_fact(c, client_id="co", subsection_id="2.1", text="Основатель родился в Москве", flag="green")
    matrix.add_fact(c, client_id="co", subsection_id="1.1", text="Любит велоспорт", flag="green")
    matrix.add_fact(c, client_id="co2", subsection_id="2.1", text="Фаундер учился в Москве тоже", flag="green")
    return c


def test_search_client_scope(conn):
    hits = matrix.search_facts(conn, "москве", client_id="co")
    assert len(hits) == 1
    assert hits[0]["client_id"] == "co" and hits[0]["subsection_id"] == "2.1"


def test_search_case_insensitive_cyrillic(conn):
    # capital М не должно мешать (SQLite LIKE — только ASCII, тут pylower)
    assert len(matrix.search_facts(conn, "МОСКВЕ", client_id="co")) == 1


def test_search_all_scope(conn):
    hits = matrix.search_facts(conn, "москве", client_id=None)
    ids = {h["client_id"] for h in hits}
    assert ids == {"co", "co2"}


def test_search_excludes_merged(conn):
    a = matrix.add_fact(conn, client_id="co", subsection_id="3.1", text="Дубль про Москве один", flag="green")
    b = matrix.add_fact(conn, client_id="co", subsection_id="3.1", text="Дубль про Москве два", flag="green")
    matrix.merge_facts(conn, keep_id=a, merge_ids=[b])
    texts = [h["text"] for h in matrix.search_facts(conn, "дубль", client_id="co")]
    assert any("один" in t for t in texts)      # keep остаётся
    assert not any("два" in t for t in texts)   # rejected дубль скрыт


def test_search_endpoint(conn, tmp_path):
    from backend.main import app, get_conn

    def _override():
        yield conn

    app.dependency_overrides[get_conn] = _override
    try:
        client = TestClient(app)
        r = client.get("/api/search", params={"q": "москве", "scope": "all"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["scope"] == "all"
        assert {h["client_id"] for h in body["results"]} == {"co", "co2"}

        r2 = client.get("/api/search", params={"q": "москве", "scope": "client", "client_id": "co"})
        assert {h["client_id"] for h in r2.json()["results"]} == {"co"}

        # слишком короткий запрос → пусто
        assert client.get("/api/search", params={"q": "м"}).json()["results"] == []
    finally:
        app.dependency_overrides.clear()
