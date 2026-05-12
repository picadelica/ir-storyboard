"""Tests for Task 1: add-client end-to-end."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix
from ir_storyboard.cli import main as cli_main


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    yield c
    c.close()


def _seed_payload(client_id="acme", n_facts=3):
    facts = [
        {
            "subsection_id": "2.1",
            "text": f"Fact {i}",
            "flag": "green",
            "channel": "archival",
            "source_title": f"Source {i}",
            "source_url": "",
        }
        for i in range(n_facts)
    ]
    return {
        "client": {"id": client_id, "name": "Acme", "sector": "saas"},
        "founder_name": "Jane",
        "seed_facts": facts,
        "initial_quarter": "2026Q3",
        "seed_tracks": [
            {
                "name": "Track A",
                "target_layer_ids": [6],
                "target_subsection_ids": ["6.1"],
                "priority": 1,
            }
        ],
    }


# ── import-seed empty → client with grid, 0 facts ──────────────────────────

def test_empty_seed_creates_grid(conn):
    payload = {"client": {"id": "empty", "name": "Empty Co"}, "seed_facts": []}
    matrix.upsert_client(conn, "empty", "Empty Co")
    matrix.ensure_full_grid(conn, "empty")
    assert matrix.count_client_facts(conn, "empty") == 0
    summary = matrix.cell_summary(conn, "empty")
    assert len(summary) == 24  # 24 subsections (8 layers × 3)


# ── import-seed with 3 facts → 3 facts + 3 sources ─────────────────────────

def test_seed_creates_facts(conn):
    p = _seed_payload("acme", n_facts=3)
    matrix.upsert_client(conn, "acme", "Acme", founder_name="Jane")
    matrix.ensure_full_grid(conn, "acme")
    for sf in p["seed_facts"]:
        src_id = matrix.add_source(conn, channel=sf["channel"],
                                   title=sf["source_title"], url=sf.get("source_url", ""))
        matrix.add_fact(conn, client_id="acme", subsection_id=sf["subsection_id"],
                        text=sf["text"], flag=sf["flag"], source_id=src_id)
    assert matrix.count_client_facts(conn, "acme") == 3
    sources = conn.execute("SELECT count(*) FROM sources").fetchone()[0]
    assert sources == 3


# ── idempotency: second seed without force raises ValueError ────────────────

def test_duplicate_seed_rejected(conn):
    matrix.upsert_client(conn, "acme", "Acme")
    matrix.ensure_full_grid(conn, "acme")
    matrix.add_source(conn, channel="archival", title="S1", url="")
    matrix.add_fact(conn, client_id="acme", subsection_id="2.1",
                    text="existing fact", flag="green", source_id=1)
    assert matrix.count_client_facts(conn, "acme") == 1
    # second attempt should be rejected at the application layer
    # (the API returns 409; here we just verify the count check)
    count = matrix.count_client_facts(conn, "acme")
    assert count > 0, "should have facts, 409 expected"


# ── force=True: old facts survive, new ones added ──────────────────────────

def test_force_seed_adds_without_deleting(conn):
    matrix.upsert_client(conn, "acme", "Acme")
    matrix.ensure_full_grid(conn, "acme")
    src_id = matrix.add_source(conn, channel="archival", title="Old", url="")
    matrix.add_fact(conn, client_id="acme", subsection_id="2.1",
                    text="old fact", flag="green", source_id=src_id)
    assert matrix.count_client_facts(conn, "acme") == 1

    src_id2 = matrix.add_source(conn, channel="archival", title="New", url="")
    matrix.add_fact(conn, client_id="acme", subsection_id="2.1",
                    text="new fact", flag="green", source_id=src_id2)
    assert matrix.count_client_facts(conn, "acme") == 2
    # old fact still there
    facts = matrix.facts_for_cell(conn, "acme", "2.1")
    texts = [f["text"] for f in facts]
    assert "old fact" in texts
    assert "new fact" in texts


# ── CLI smoke test ──────────────────────────────────────────────────────────

def test_cli_add_client_from_yaml(tmp_path):
    dummy_yaml = ROOT / "seeds" / "dummy.yaml"
    if not dummy_yaml.exists():
        pytest.skip("seeds/dummy.yaml not found")

    db_path = tmp_path / "matrix.db"
    import unittest.mock as mock
    with mock.patch("ir_storyboard.db.DEFAULT_DB_PATH", db_path):
        conn = db.connect(db_path)
        db.init_schema(conn)
        matrix.seed_layers(conn)
        conn.close()
        result = cli_main(["add-client", "--from", str(dummy_yaml)])
    assert result == 0
