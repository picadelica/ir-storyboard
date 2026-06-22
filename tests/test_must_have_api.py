"""Backend smoke for the must-have / client-facts feature (Proposal #4):
- POST /facts/{id}/must-have toggles the blue overlay flag
- POST /clients/{id}/ingest/client-facts inserts client-provided facts as must-have
- cell_summary exposes n_must (count of blue facts in a cell)
Offline, no network."""
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
    db_path = tmp_path / "musthave_api.db"

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
                          text="Ordinary web fact.", flag="green")
    init.close()
    client = TestClient(app)
    yield client, fid
    app.dependency_overrides.clear()


def test_toggle_must_have(ctx):
    client, fid = ctx
    r = client.post(f"/api/facts/{fid}/must-have", json={"must_have": True})
    assert r.status_code == 200, r.text
    assert r.json()["must_have"] is True

    r = client.post(f"/api/facts/{fid}/must-have", json={"must_have": False})
    assert r.status_code == 200, r.text
    assert r.json()["must_have"] is False


def test_ingest_client_facts_are_must_have(ctx):
    client, _ = ctx
    body = {
        "source_title": "От клиента",
        "facts": [
            {"text": "Клиент: мы закрыли раунд A.", "subsection_id": "4.1", "flag": "green"},
            {"text": "Клиент: основатель — серийный предприниматель.", "subsection_id": "1.1", "flag": "green"},
            {"text": "", "subsection_id": "4.1", "flag": "green"},  # skipped (empty)
        ],
    }
    r = client.post("/api/clients/co/ingest/client-facts", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert len(out["written"]) == 2
    assert out["skipped"] == 1

    # the L1 fact lands despite offline_interview channel (title-only provenance)
    facts = client.get("/api/clients/co/cells/1.1/facts").json()
    assert any(f["must_have"] and "серийный" in f["text"] for f in facts)


def test_cell_summary_reports_n_must(ctx):
    client, _ = ctx
    client.post("/api/clients/co/ingest/client-facts", json={
        "source_title": "От клиента",
        "facts": [{"text": "Клиент-факт.", "subsection_id": "4.1", "flag": "green"}],
    })
    cells = client.get("/api/clients/co/matrix").json()
    cell = next(c for c in cells if c["subsection_id"] == "4.1")
    assert cell.get("n_must") == 1
