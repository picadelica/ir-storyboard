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


def test_client_facts_pdf_preview_allows_L1(ctx, monkeypatch):
    """Auto-parse of a client file maps facts across ALL layers (L1 included),
    unlike the web 'other PDF' path which is capped at L2–L8."""
    from ir_storyboard import llm
    client, _ = ctx

    def _fake_extract(pdf_bytes, available_subsections, **kw):
        assert "1.1" in available_subsections  # L1 must be open for client material
        return [
            llm.ExtractedFact(text="Основатель вырос в семье инженеров.", subsection_id="1.1", flag="green"),
            llm.ExtractedFact(text="Закрыли раунд A на $5M.", subsection_id="4.1", flag="green"),
        ]
    monkeypatch.setattr(llm, "extract_facts_from_pdf", _fake_extract)

    files = {"file": ("client.pdf", b"%PDF-1.4 fake", "application/pdf")}
    r = client.post("/api/clients/co/ingest/client-facts/preview", files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["channel"] == "offline_interview"
    sids = {c["suggested_subsection_id"] for c in body["candidates"]}
    assert "1.1" in sids and "4.1" in sids

    # committing the previewed facts → all must_have, L1 included
    facts = [{"text": c["text"], "subsection_id": c["suggested_subsection_id"], "flag": c["suggested_flag"]}
             for c in body["candidates"]]
    r2 = client.post("/api/clients/co/ingest/client-facts",
                     json={"source_title": body["source_title"], "facts": facts})
    assert r2.status_code == 200, r2.text
    assert len(r2.json()["written"]) == 2
    l1 = client.get("/api/clients/co/cells/1.1/facts").json()
    assert any(f["must_have"] and "инженеров" in f["text"] for f in l1)


def test_client_facts_pdf_rejects_non_pdf(ctx):
    client, _ = ctx
    files = {"file": ("notes.txt", b"hello", "text/plain")}
    r = client.post("/api/clients/co/ingest/client-facts/preview", files=files)
    assert r.status_code == 400


def test_client_facts_pdf_corrupt_surfaces_422(ctx, monkeypatch):
    """A PDF the vision API rejects (corrupt/encrypted) must surface as a clear 422,
    not a silent 200 with zero facts."""
    from ir_storyboard import llm
    client, _ = ctx

    def _reject(*a, **k):
        raise llm.PdfRejectedError("Не удалось прочитать PDF: файл повреждён…")
    monkeypatch.setattr(llm, "extract_facts_from_pdf", _reject)

    files = {"file": ("broken.pdf", b"%PDF-1.4 broken", "application/pdf")}
    r = client.post("/api/clients/co/ingest/client-facts/preview", files=files)
    assert r.status_code == 422
    assert "PDF" in r.json()["detail"]
