"""Идентичность компании: (1) создание клиента заводит company+founder сущности,
(2) упомянутые (внешние) компании CRUD. Offline."""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix


@pytest.fixture
def client(tmp_path):
    from backend.main import app, get_conn
    db_path = tmp_path / "ident.db"

    def _override():
        conn = db.connect(db_path)
        db.init_schema(conn)
        matrix.seed_layers(conn)   # как реальный get_conn
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = _override
    init = db.connect(db_path); db.init_schema(init); matrix.seed_layers(init); init.close()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_client_creation_bootstraps_entities(client):
    r = client.post("/api/clients", json={
        "id": "co", "name": "Co Inc", "sector": "saas",
        "founder_name": "Jane Doe", "founder_handle": "@jane",
    })
    assert r.status_code == 200, r.text
    ents = client.get("/api/clients/co/entities").json()
    kinds = {e["kind"]: e for e in ents}
    assert kinds["company"]["name"] == "Co Inc"
    assert kinds["founder"]["name"] == "Jane Doe"
    assert kinds["founder"]["links"].get("telegram") == "https://t.me/jane"


def test_mentioned_companies_crud(client):
    client.post("/api/clients", json={"id": "co", "name": "Co Inc"})
    r = client.post("/api/clients/co/mentioned-companies",
                    json={"name": "GetTaxi", "note": "прошлая компания фаундера"})
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    assert client.get("/api/clients/co/mentioned-companies").json()[0]["name"] == "GetTaxi"

    client.patch(f"/api/mentioned-companies/{mid}", json={"logo": "https://x/logo.png"})
    assert client.get("/api/clients/co/mentioned-companies").json()[0]["logo"] == "https://x/logo.png"

    client.delete(f"/api/mentioned-companies/{mid}")
    assert client.get("/api/clients/co/mentioned-companies").json() == []
