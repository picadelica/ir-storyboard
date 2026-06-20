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

    def green_count():
        mx = client.get("/api/clients/co/matrix").json()
        return next(c["n_green"] for c in mx if c["subsection_id"] == "2.1")

    assert green_count() == 2  # both facts green & active

    # reject → still shown in the drawer (struck, restorable) but dropped from aggregates
    assert client.post(f"/api/facts/{fid}/reject").json()["state"] == "rejected"
    drawer = client.get("/api/clients/co/cells/2.1/facts").json()
    assert next(f for f in drawer if f["id"] == fid)["state"] == "rejected"
    assert green_count() == 1  # rejected fact no longer counted

    # restore brings it back into the matrix
    assert client.post(f"/api/facts/{fid}/restore").json()["state"] == "active"
    assert green_count() == 2


def test_audit_async_job_flow(ctx, tmp_path, monkeypatch):
    """Async start → poll /jobs/{id} → done with the same result shape."""
    import time
    client, fid, _clean = ctx
    canned = {"canonical": {"company": "RealCo", "founders": ["Liberman"]},
              "summary": "x", "facts": [
                  {"id": fid, "verdict": "suspect", "entity": "Khachuyan", "reason": "иное лицо"}]}
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(canned, ensure_ascii=False))
    # the background thread opens its own connection from DEFAULT_DB_PATH — point
    # it at the same db the fixture seeded
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", tmp_path / "verif_api.db")

    start = client.post("/api/clients/co/audit/start")
    assert start.status_code == 200, start.text
    job_id = start.json()["job_id"]
    assert start.json()["status"] == "processing"

    result = None
    for _ in range(100):  # ~5s budget
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] == "done":
            result = j["result"]
            break
        assert j["status"] != "error", j.get("error")
        time.sleep(0.05)
    assert result is not None, "job did not finish"
    assert result["available"] and result["applied"] == 1
    assert result["facts"][0]["id"] == fid

    assert client.get("/api/jobs/does-not-exist").status_code == 404


def test_entity_fact_bare_year_as_of(ctx):
    """A bare-year as_of ('2024') survives SQLite DATE affinity (stored int) and
    still reads back as a string — no 500 from the entities endpoint."""
    client, _, _ = ctx
    e = client.post("/api/clients/co/entities", json={"kind": "company", "name": "Co"}).json()
    f = client.post(f"/api/entities/{e['id']}/facts",
                    json={"value": "Founded", "as_of": "2024", "section": "profile"}).json()
    assert f["as_of"] == "2024"
    got = client.get("/api/clients/co/entities")
    assert got.status_code == 200
    fact = next(x for x in got.json() if x["id"] == e["id"])["facts"][0]
    assert fact["as_of"] == "2024"


def test_company_autofill_commit(ctx):
    """Accepted proposals land on the company card (created on the fly), verified
    because source-linked, grouped by section."""
    client, _, _ = ctx
    r = client.post("/api/clients/co/company/autofill/commit", json={"proposals": [
        {"section": "funding", "key": "Seed", "value": "$10M (2024)", "source_url": "https://tc.com/x", "source_title": "TC"},
        {"section": "profile", "key": "", "value": "no source fact", "source_url": ""},
    ]})
    assert r.status_code == 200 and r.json()["committed"] == 2
    comp = next(e for e in client.get("/api/clients/co/entities").json() if e["kind"] == "company")
    facts = {f["value"]: f for f in comp["facts"]}
    assert facts["$10M (2024)"]["section"] == "funding" and facts["$10M (2024)"]["verified"]
    assert facts["no source fact"]["verified"] is False  # no source → not verified

    start = client.post("/api/clients/co/company/autofill/start")
    assert start.status_code == 200 and start.json()["job_id"]


def test_set_verification_manual(ctx):
    client, fid, _ = ctx
    r = client.post(f"/api/facts/{fid}/verification",
                    json={"verification": "verified", "note": "ok by analyst"})
    assert r.status_code == 200 and r.json()["verification"] == "verified"


def test_audit_bootstraps_identity_anchor(ctx, monkeypatch):
    client, fid, _ = ctx
    canned = {"canonical": {"company": "RealCo", "founders": ["Daniil Liberman"], "decoys": ["Khachuyan"]},
              "summary": "", "facts": []}
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(canned, ensure_ascii=False))
    client.post("/api/clients/co/audit")

    ents = client.get("/api/clients/co/entities").json()
    by_kind = {e["kind"]: e for e in ents}
    assert by_kind["company"]["name"] == "RealCo"
    assert by_kind["founder"]["name"] == "Daniil Liberman"
    assert by_kind["decoy"]["name"] == "Khachuyan"
    assert all(not e["confirmed"] for e in ents)  # draft until analyst confirms


def test_review_queue_and_promote(ctx, tmp_path):
    client, fid, clean = ctx
    # quarantine fid the way the ingest gate would (state='review')
    c = db.connect(tmp_path / "verif_api.db")
    matrix.set_fact_verification(c, fid, verification="suspect", note="двойник", entity="Khachuyan")
    matrix.set_fact_state(c, fid, "review")
    c.close()

    # review-queue lists it; matrix aggregate excludes it (held out of the matrix)
    rq = client.get("/api/clients/co/review-queue").json()
    assert any(r["id"] == fid and r["entity"] == "Khachuyan" for r in rq)
    mx = client.get("/api/clients/co/matrix").json()
    assert next(c["n_green"] for c in mx if c["subsection_id"] == "2.1") == 1  # only `clean`

    # promote → enters the matrix as verified
    assert client.post(f"/api/facts/{fid}/promote").json()["verification"] == "verified"
    mx = client.get("/api/clients/co/matrix").json()
    assert next(c["n_green"] for c in mx if c["subsection_id"] == "2.1") == 2
    assert client.get("/api/clients/co/review-queue").json() == []


def test_merge_facts(ctx):
    client, fid, clean = ctx
    # both fid & clean are green in 2.1; merge clean into fid
    r = client.post("/api/facts/merge", json={"keep_id": fid, "merge_ids": [clean]}).json()
    assert r["id"] == fid and r["n_sources"] == 2 and r["state"] == "active"
    # the merged duplicate left the matrix
    mx = client.get("/api/clients/co/matrix").json()
    assert next(c["n_green"] for c in mx if c["subsection_id"] == "2.1") == 1
    keep = next(f for f in client.get("/api/clients/co/cells/2.1/facts").json() if f["id"] == fid)
    assert keep["n_sources"] == 2


def test_entities_crud(ctx):
    client, _, _ = ctx
    e = client.post("/api/clients/co/entities",
                    json={"kind": "founder", "name": "Jane Doe", "role": "CTO",
                          "links": {"x": "https://x.com/jane"}}).json()
    eid = e["id"]
    f = client.post(f"/api/entities/{eid}/facts",
                    json={"key": "prior", "value": "Acme (2019)", "source_url": "https://acme.co",
                          "verified": True, "section": "funding"}).json()
    assert f["section"] == "funding"  # company About groups facts by business section
    got = next(x for x in client.get("/api/clients/co/entities").json() if x["id"] == eid)
    assert got["role"] == "CTO" and got["links"]["x"].endswith("/jane")
    assert got["facts"][0]["value"] == "Acme (2019)" and got["facts"][0]["verified"]
    assert got["facts"][0]["section"] == "funding"
    # the card editor adds/removes links via PATCH links (full replace)
    client.patch(f"/api/entities/{eid}", json={"links": {"x": "https://x.com/jane", "wiki": "https://en.wikipedia.org/Jane"}})
    relinked = next(x for x in client.get("/api/clients/co/entities").json() if x["id"] == eid)
    assert set(relinked["links"]) == {"x", "wiki"}
    client.delete(f"/api/entity-facts/{f['id']}")
    client.delete(f"/api/entities/{eid}")
    assert all(x["id"] != eid for x in client.get("/api/clients/co/entities").json())
