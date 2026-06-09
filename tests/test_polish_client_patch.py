"""Tests for polish-3: PATCH /api/clients/{client_id} + ClientPatch model."""
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

    db_path = tmp_path / "test_client_patch.db"

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
    init.close()

    with TestClient(app) as tc:
        # seed a client to patch
        tc.post(
            "/api/clients",
            json={
                "id": "patch_co",
                "name": "Patch Co",
                "sector": "saas",
                "one_liner": "Original tagline",
                "founder_name": "Jane",
                "aliases": ["PC"],
                "notes": "initial",
                "tone_preset": "business",
            },
        )
        yield tc
    app.dependency_overrides.clear()


def test_patch_updates_one_field(api):
    resp = api.patch("/api/clients/patch_co", json={"notes": "updated note"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["notes"] == "updated note"
    # untouched fields preserved
    assert body["name"] == "Patch Co"
    assert body["one_liner"] == "Original tagline"


def test_patch_unset_fields_untouched(api):
    resp = api.patch("/api/clients/patch_co", json={"sector": "fintech"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sector"] == "fintech"
    assert body["founder_name"] == "Jane"
    assert body["notes"] == "initial"


def test_patch_aliases_round_trips_as_list(api):
    resp = api.patch(
        "/api/clients/patch_co",
        json={"aliases": ["PC", "PatchCo", "P-Co"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["aliases"] == ["PC", "PatchCo", "P-Co"]
    # re-GET to confirm DB serialization round-trips
    body = api.get("/api/clients/patch_co").json()
    assert body["aliases"] == ["PC", "PatchCo", "P-Co"]


def test_patch_aliases_empty_list(api):
    resp = api.patch("/api/clients/patch_co", json={"aliases": []})
    assert resp.status_code == 200, resp.text
    assert resp.json()["aliases"] == []


def test_patch_missing_client_returns_404(api):
    resp = api.patch("/api/clients/does_not_exist", json={"name": "Ghost"})
    assert resp.status_code == 404


def test_patch_empty_body_is_noop(api):
    before = api.get("/api/clients/patch_co").json()
    resp = api.patch("/api/clients/patch_co", json={})
    assert resp.status_code == 200, resp.text
    after = resp.json()
    # Should be effectively unchanged
    assert after["name"] == before["name"]
    assert after["notes"] == before["notes"]


def test_patch_then_get_returns_updated(api):
    api.patch(
        "/api/clients/patch_co",
        json={
            "one_liner": "New tagline",
            "founder_handle": "@jane",
            "tone_preset": "academic",
        },
    )
    body = api.get("/api/clients/patch_co").json()
    assert body["one_liner"] == "New tagline"
    assert body["founder_handle"] == "@jane"
    assert body["tone_preset"] == "academic"


def test_patch_id_field_ignored_extra_keys(api):
    """Body cannot rename the client — path id is authoritative."""
    resp = api.patch(
        "/api/clients/patch_co",
        json={"id": "spoofed_id", "name": "Renamed"},
    )
    # `id` is not declared on ClientPatch, so Pydantic ignores it silently.
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == "patch_co"
    assert resp.json()["name"] == "Renamed"
    # original id still exists
    assert api.get("/api/clients/patch_co").status_code == 200
