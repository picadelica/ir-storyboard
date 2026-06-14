"""E2E process test for Task 4: full analyst workflow."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)
DUMMY_YAML = (ROOT / "seeds" / "dummy.yaml").read_text()


def _reset():
    """Delete dummy-test client if it exists to start clean."""
    from ir_storyboard import db
    conn = db.connect()
    db.init_schema(conn)  # self-contained: tables may not exist yet on a fresh DB
    conn.execute("DELETE FROM work_items WHERE client_id='dummy-test'")
    conn.execute("DELETE FROM facts WHERE cell_id IN "
                 "(SELECT id FROM cells WHERE client_id='dummy-test')")
    conn.execute("DELETE FROM cells WHERE client_id='dummy-test'")
    conn.execute("DELETE FROM plans WHERE client_id='dummy-test'")
    conn.execute("DELETE FROM clients WHERE id='dummy-test'")
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def clean_db():
    _reset()
    yield
    _reset()


def test_full_e2e_workflow():
    # ── Step 1: add client from YAML ─────────────────────────────────────
    resp = client.post("/api/clients", json={
        "id": "dummy-test", "name": "Dummy Test Co", "sector": "saas"
    })
    assert resp.status_code == 200

    resp = client.post(
        "/api/clients/dummy-test/import-seed-yaml",
        json={"yaml_content": DUMMY_YAML},
    )
    assert resp.status_code == 200
    seed_result = resp.json()

    # ── Step 2: verify structure ──────────────────────────────────────────
    assert seed_result["client_id"] == "dummy-test"
    assert seed_result["fact_count"] == 3
    assert seed_result["source_count"] == 3
    assert seed_result["track_count"] == 1

    clients = client.get("/api/clients").json()
    assert any(c["id"] == "dummy-test" for c in clients)

    facts = client.get("/api/clients/dummy-test/cells/2.1/facts").json()
    assert len(facts) >= 1

    tracks = client.get("/api/clients/dummy-test/plans/2026Q3/tracks").json()
    assert len(tracks) == 1

    # ── Step 3: work items already synthesized by import-seed-yaml hook ──
    # Explicit call is idempotent (returns 0 new) but total count must be ≥20
    resp = client.post("/api/clients/dummy-test/work-items/synthesize")
    assert resp.status_code == 200

    work_items = client.get("/api/clients/dummy-test/work-items").json()
    assert len(work_items) >= 20, f"Expected ≥20 work items, got {len(work_items)}"

    # ── Step 4: close a fill_gap by adding a green fact ──────────────────
    # find a fill_gap for a cell that has no facts yet (not 2.1, 6.1, 1.1)
    queued_gaps = [
        wi for wi in work_items
        if wi["type"] == "fill_gap"
        and wi["status"] == "queued"
        and wi["subsection_id"] not in ("2.1", "6.1", "1.1")
    ]
    assert queued_gaps, "should have queued fill_gap items"
    target_sid = queued_gaps[0]["subsection_id"]

    # Add a green fact to that cell — for offline_interview no snippet needed
    resp = client.post(
        f"/api/clients/dummy-test/cells/{target_sid}/facts",
        json={
            "text": "New fact that closes the fill_gap.",
            "flag": "green",
            "channel": "offline_interview",
            "source_title": "Interview 2026-05-07",
        },
    )
    assert resp.status_code == 200
    new_fact_id = resp.json()["id"]

    # fill_gap for that cell should now be needs_review
    work_items_after = client.get("/api/clients/dummy-test/work-items").json()
    matching = [wi for wi in work_items_after
                if wi["subsection_id"] == target_sid and wi["type"] == "fill_gap"]
    assert any(wi["status"] == "needs_review" for wi in matching), \
        f"Expected needs_review for {target_sid}, got: {[wi['status'] for wi in matching]}"

    # ── Step 5: PATCH work item → done ───────────────────────────────────
    wi_id = matching[0]["id"]
    resp = client.patch(f"/api/work-items/{wi_id}", json={
        "status": "done",
        "related_fact_id": new_fact_id,
        "notes": "closed via e2e test",
    })
    assert resp.status_code == 200
    wi_done = resp.json()
    assert wi_done["status"] == "done"
    assert wi_done["completed_at"] is not None
    assert wi_done["related_fact_id"] == new_fact_id

    # ── Step 6: weekly cycle runs without error ───────────────────────────
    resp = client.post(
        "/api/clients/dummy-test/cycles/weekly",
        json={"quarter": "2026Q3"},
    )
    assert resp.status_code == 200
    artifact = resp.json()
    assert artifact["cycle"] == "weekly"
    assert artifact["body"]
