"""Backend smoke for fact-trust endpoints: audit applies verdicts, reject/restore
move lifecycle state, rejected facts drop out of the cell view. Offline."""
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix, llm


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    from backend.main import app, get_conn
    db_path = tmp_path / "verif_api.db"

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
                          text="Khachuyan is CEO.", flag="green")
    clean = matrix.add_fact(init, client_id="co", subsection_id="2.1",
                            text="Founded by the Libermans.", flag="green")
    init.close()
    client = TestClient(app)
    yield client, fid, clean
    app.dependency_overrides.clear()


def test_audit_apply_then_reject_restore(ctx, monkeypatch):
    client, fid, clean = ctx
    canned = {"canonical": {"company": "RealCo", "founders": ["Liberman"], "decoys": ["Khachuyan"]},
              "summary": "conflation", "facts": [
                  {"id": fid, "verdict": "refuted", "entity": "Khachuyan — иное лицо", "reason": "иное лицо"}]}
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(canned, ensure_ascii=False))

    r = client.post("/api/clients/co/audit")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] and body["applied"] == 1
    assert body["canonical"]["company"] == "RealCo"
    assert body["facts"][0]["id"] == fid and body["facts"][0]["verdict"] == "refuted"

    # verdict is now visible on the fact in the cell
    facts = client.get("/api/clients/co/cells/2.1/facts").json()
    flagged = next(f for f in facts if f["id"] == fid)
    assert flagged["verification"] == "refuted" and "иное лицо" in flagged["entity"]

    # reject → fact drops out of the cell view (excluded from matrix/outputs)
    assert client.post(f"/api/facts/{fid}/reject").json()["state"] == "rejected"
    ids = {f["id"] for f in client.get("/api/clients/co/cells/2.1/facts").json()}
    assert fid not in ids and clean in ids

    # restore brings it back
    assert client.post(f"/api/facts/{fid}/restore").json()["state"] == "active"
    ids = {f["id"] for f in client.get("/api/clients/co/cells/2.1/facts").json()}
    assert fid in ids


def test_set_verification_manual(ctx):
    client, fid, _ = ctx
    r = client.post(f"/api/facts/{fid}/verification",
                    json={"verification": "verified", "note": "ok by analyst"})
    assert r.status_code == 200 and r.json()["verification"] == "verified"
