"""Backend smoke for manual fact move: POST /facts/{id}/move re-homes a fact
into another subsection (cell_id) without mutating its text. Offline, no network."""
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
    db_path = tmp_path / "factmove_api.db"

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
    matrix.upsert_client(init, "co", "Co")
    matrix.ensure_full_grid(init, "co")
    fid = matrix.add_fact(init, client_id="co", subsection_id="2.1",
                          text="A movable fact.", flag="green")
    init.close()
    client = TestClient(app)
    yield client, fid, db_path
    app.dependency_overrides.clear()


def _subsection_of(db_path, fid):
    c = db.connect(db_path)
    row = c.execute(
        "SELECT s.id FROM facts f JOIN cells ce ON f.cell_id = ce.id "
        "JOIN subsections s ON ce.subsection_id = s.id WHERE f.id = ?", (fid,)
    ).fetchone()
    c.close()
    return row[0] if row else None


def test_move_fact_to_other_subsection(ctx):
    client, fid, db_path = ctx
    r = client.post(f"/api/facts/{fid}/move", json={"to_sid": "3.2"})
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "A movable fact."  # immutable text (invariant #5)
    assert _subsection_of(db_path, fid) == "3.2"


def test_move_fact_unknown_subsection(ctx):
    client, fid, _ = ctx
    r = client.post(f"/api/facts/{fid}/move", json={"to_sid": "9.9"})
    assert r.status_code == 422, r.text


def test_move_missing_fact(ctx):
    client, _, _ = ctx
    r = client.post("/api/facts/999999/move", json={"to_sid": "3.2"})
    assert r.status_code == 404, r.text
