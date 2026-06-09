"""Tests for Task 3: work-item layer."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix
from ir_storyboard.workitems import synthesize_work_items


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "acme", "Acme")
    matrix.ensure_full_grid(c, "acme")
    yield c
    c.close()


def _count(conn, client_id, type_=None, status=None):
    q = "SELECT COUNT(*) FROM work_items WHERE client_id=?"
    params = [client_id]
    if type_:
        q += " AND type=?"
        params.append(type_)
    if status:
        q += " AND status=?"
        params.append(status)
    return conn.execute(q, params).fetchone()[0]


# ── empty client → 24 fill_gap + 9 interview ──────────────────────────────

def test_synthesize_empty_client(conn):
    created = synthesize_work_items(conn, "acme")
    assert _count(conn, "acme", "fill_gap") == 24
    # layers 1-3 have 3+3+3=9 subsections (L1 collapsed to 3)
    assert _count(conn, "acme", "interview") == 9
    assert _count(conn, "acme", "deepen") == 0   # empty cells not deepen-eligible


# ── idempotency: second synthesize creates 0 new items ──────────────────────

def test_synthesize_idempotent(conn):
    first = synthesize_work_items(conn, "acme")
    second = synthesize_work_items(conn, "acme")
    assert len(second) == 0
    assert _count(conn, "acme") == len(first)


# ── green fact → fill_gap transitions to needs_review ──────────────────────

def test_green_fact_auto_closes_fill_gap(conn):
    synthesize_work_items(conn, "acme")
    # fill_gap for 1.1 should be queued
    assert _count(conn, "acme", "fill_gap", "queued") == 24

    src_id = matrix.add_source(conn, channel="offline_interview",
                               title="Interview 2026-05-07", url="")
    matrix.add_fact(conn, client_id="acme", subsection_id="1.1",
                    text="founder childhood", flag="green", source_id=src_id)

    assert _count(conn, "acme", "fill_gap", "needs_review") >= 1
    assert _count(conn, "acme", "fill_gap", "queued") == 23


# ── red fact does NOT close fill_gap ───────────────────────────────────────

def test_red_fact_does_not_close(conn):
    synthesize_work_items(conn, "acme")
    src_id = matrix.add_source(conn, channel="offline_interview",
                               title="Interview 2026-05-07", url="")
    matrix.add_fact(conn, client_id="acme", subsection_id="1.1",
                    text="concern", flag="red", source_id=src_id,
                    rationale="Founder declined to discuss the childhood incident.")
    assert _count(conn, "acme", "fill_gap", "needs_review") == 0


# ── deepen: appears after a cell has 1 green and is thin ───────────────────

def test_deepen_created_for_thin_cell(conn):
    # add 1 green fact to 1.1 (making it thin: 1 green < 2)
    src_id = matrix.add_source(conn, channel="offline_interview",
                               title="Interview 2026-05-07", url="")
    matrix.add_fact(conn, client_id="acme", subsection_id="1.1",
                    text="founder childhood", flag="green", source_id=src_id)
    synthesize_work_items(conn, "acme")
    assert _count(conn, "acme", "deepen") >= 1


# ── manual create via API ───────────────────────────────────────────────────

def test_api_create_work_item():
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app)

    client.post("/api/clients/accumulator/seed-accumulator")

    resp = client.post(
        "/api/clients/accumulator/work-items",
        json={
            "type": "adjacent",
            "source_signal": "manual",
            "title": "Research key investor Avishai Abraami",
            "priority": 2,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "adjacent"
    assert data["status"] == "queued"


# ── API synthesize endpoint ─────────────────────────────────────────────────

def test_api_synthesize():
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app)

    client.post("/api/clients/accumulator/seed-accumulator")
    resp = client.post("/api/clients/accumulator/work-items/synthesize")
    assert resp.status_code == 200
    data = resp.json()
    assert "created" in data
    assert "skipped" in data
    # accumulator has some facts so work items will vary, but synthesize runs
    assert isinstance(data["created"], list)
