"""Фаза 1 прав экспертов: users-таблица, владелец компании, скрытие.
Offline, auth выключен (в тестах env не задан) — проверяем модель и эндпоинты."""
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
    db_path = tmp_path / "roles.db"

    def _override():
        conn = db.connect(db_path)
        db.init_schema(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = _override
    init = db.connect(db_path)
    db.init_schema(init)
    matrix.seed_layers(init)
    init.close()
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def test_users_list_empty_initially(client):
    r = client.get("/api/users")
    assert r.status_code == 200 and r.json() == []


def test_owner_default_and_reassign(client):
    client.post("/api/clients", json={"id": "acme", "name": "Acme"})
    # без auth создатель-tid неизвестен → владельца нет
    got = next(c for c in client.get("/api/clients").json() if c["id"] == "acme")
    assert got["owner_tid"] is None and got["hidden"] is False

    # назначить владельца (без auth эндпоинт открыт)
    r = client.put("/api/clients/acme/owner", json={"tid": 555})
    assert r.status_code == 200 and r.json()["owner_tid"] == 555
    r = client.put("/api/clients/zzz/owner", json={"tid": 1})
    assert r.status_code == 404


def test_hidden_excluded_from_list(client):
    client.post("/api/clients", json={"id": "a", "name": "A"})
    client.post("/api/clients", json={"id": "b", "name": "B"})
    r = client.put("/api/clients/b/hidden", json={"hidden": True})
    assert r.status_code == 200 and r.json()["hidden"] is True

    ids = [c["id"] for c in client.get("/api/clients").json()]
    assert "a" in ids and "b" not in ids                    # скрытая вне списка
    ids_all = [c["id"] for c in client.get("/api/clients?include_hidden=true").json()]
    assert "b" in ids_all                                   # но видна с include_hidden

    # portfolio тоже исключает скрытую
    pf = [r["id"] for r in client.get("/api/clients/portfolio").json()]
    assert "a" in pf and "b" not in pf

    # вернуть из скрытия
    client.put("/api/clients/b/hidden", json={"hidden": False})
    assert "b" in [c["id"] for c in client.get("/api/clients").json()]


def test_users_upsert_direct(tmp_path):
    conn = db.connect(tmp_path / "u.db")
    db.init_schema(conn)
    matrix.upsert_user(conn, 42, "Ада", "ada")
    matrix.upsert_user(conn, 42, "Ада Лавлейс")            # имя обновилось, username сохранён
    u = matrix.get_user(conn, 42)
    assert u["name"] == "Ада Лавлейс" and u["username"] == "ada"
    assert [x["tid"] for x in matrix.list_users(conn)] == [42]
    conn.close()
