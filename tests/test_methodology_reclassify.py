"""Переосмысление раскладки при смене методологии: переезд факта, превью переездов, apply."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir_storyboard import db, matrix
from ir_storyboard.llm import FactCandidate, reclassify_facts
from backend import main


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "recl.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "co", "Co")
    matrix.ensure_full_grid(c, "co")
    return c


def test_move_fact_to_subsection(conn):
    fid = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="x", flag="green")
    assert matrix.move_fact_to_subsection(conn, fid, "co", "3.2") is True
    assert any(f["id"] == fid for f in matrix.facts_for_cell(conn, "co", "3.2"))
    assert not any(f["id"] == fid for f in matrix.facts_for_cell(conn, "co", "2.1"))
    # текст не тронут (инвариант неизменности)
    assert matrix.get_fact(conn, fid)["text"] == "x"
    # кросс-клиентский переезд заблокирован
    matrix.upsert_client(conn, "other", "Other")
    assert matrix.move_fact_to_subsection(conn, fid, "other", "1.1") is False


def test_compute_methodology_moves(conn, monkeypatch):
    a = matrix.add_fact(conn, client_id="co", subsection_id="2.1",
                        text="founder childhood in a small town", flag="green")
    matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="stays here", flag="green")

    def fake_reclassify(texts, descriptions=None, client_notes=None, **kwargs):
        return [FactCandidate(
            text=t,
            suggested_subsection_id="1.1" if "childhood" in t else "2.1",
            suggested_flag="green", confidence=0.9, rationale="test",
        ) for t in texts]

    monkeypatch.setattr(main, "reclassify_facts", fake_reclassify)
    result = main._compute_methodology_moves(conn, "co")
    assert result["total"] == 2 and result["moved"] == 1
    mv = result["moves"][0]
    assert mv["fact_id"] == a and mv["from_sid"] == "2.1" and mv["to_sid"] == "1.1"
    assert mv["confidence"] == 0.9

    # apply переезда → факт в новой ячейке
    assert matrix.move_fact_to_subsection(conn, a, "co", mv["to_sid"]) is True
    assert any(f["id"] == a for f in matrix.facts_for_cell(conn, "co", "1.1"))


def test_reclassify_facts_no_key_fallback(conn):
    # без ANTHROPIC_API_KEY generate_json → None → keyword-стаб, без падения
    out = reclassify_facts(["some fact text about revenue growth"], {}, {})
    assert len(out) == 1
    assert isinstance(out[0], FactCandidate)
