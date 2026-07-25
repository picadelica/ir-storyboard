"""Админка: глобальный журнал действий (все компании, фильтры) + эндпоинт /api/admin/activity.
Offline (auth выключен → локально открыто)."""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix


@pytest.fixture
def ctx(tmp_path):
    from backend.main import app, get_conn
    db_path = tmp_path / "admin.db"

    def _override():
        conn = db.connect(db_path)
        db.init_schema(conn)
        matrix.seed_layers(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = _override
    init = db.connect(db_path); db.init_schema(init); matrix.seed_layers(init)
    for cid, nm in [("a", "Alpha"), ("b", "Beta")]:
        matrix.upsert_client(init, cid, nm)
        matrix.ensure_full_grid(init, cid)
    fa = matrix.add_fact(init, client_id="a", subsection_id="2.1", text="fa", flag="green")
    fb = matrix.add_fact(init, client_id="b", subsection_id="2.1", text="fb", flag="green")
    matrix.move_fact_to_subsection(init, fa, "a", "3.1", method="manual",
                                   moved_by="Эксперт", moved_by_tid=7)
    init.close()
    client = TestClient(app)
    yield client, fa, fb
    app.dependency_overrides.clear()


def test_global_log_and_filters(ctx):
    client, fa, fb = ctx
    r = client.get("/api/admin/activity")
    assert r.status_code == 200, r.text
    acts = r.json()["activity"]
    # created x2 (центрально из add_fact) + moved x1
    assert {(e["action"], e["client_id"]) for e in acts} == {
        ("created", "a"), ("created", "b"), ("moved", "a")}
    moved = next(e for e in acts if e["action"] == "moved")
    assert moved["actor_name"] == "Эксперт" and moved["from_sid"] == "2.1" and moved["to_sid"] == "3.1"
    assert moved["client_name"] == "Alpha" and moved["methodology_version"] == 1
    assert moved["fact_text"].startswith("fa")   # выдержка карточки

    # фильтр по компании
    only_b = client.get("/api/admin/activity", params={"client_id": "b"}).json()["activity"]
    assert len(only_b) == 1 and only_b[0]["fact_id"] == fb
    # фильтр по пользователю
    by7 = client.get("/api/admin/activity", params={"actor_tid": 7}).json()["activity"]
    assert len(by7) == 1 and by7[0]["action"] == "moved"
    # фильтр по действию
    created = client.get("/api/admin/activity", params={"action": "created"}).json()["activity"]
    assert len(created) == 2


def test_act_as_expert_drops_admin_privilege(tmp_path, monkeypatch):
    """Режим «работаю как эксперт»: админ-привилегия отключается (правки → черновик),
    владение своими компаниями сохраняется."""
    from backend import auth as bauth
    from backend.main import _is_owner_or_admin
    monkeypatch.setattr(bauth, "AUTHGW_URL", "http://gw")     # auth.enabled() → True
    monkeypatch.setattr(bauth, "SESSION_SECRET", "s")
    monkeypatch.setenv("IR_ADMIN_TIDS", "42")
    c = db.connect(tmp_path / "role.db"); db.init_schema(c); matrix.seed_layers(c)
    matrix.upsert_client(c, "own", "Own"); matrix.upsert_client(c, "other", "Other")
    matrix.set_client_owner(c, "own", 42)

    admin = {"tid": 42, "name": "Админ"}
    expert = {"tid": 42, "name": "Админ", "act_as_expert": True}
    assert _is_owner_or_admin(c, "other", admin) is True       # админ — везде владелец
    assert _is_owner_or_admin(c, "other", expert) is False     # эксперт-режим → черновик
    assert _is_owner_or_admin(c, "own", expert) is True        # своя компания — владелец остаётся
