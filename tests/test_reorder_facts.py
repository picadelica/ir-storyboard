"""Ручная сортировка карточек в ячейке: matrix.reorder_facts выставляет sort_order,
facts_for_cell отдаёт в заданном порядке; чужие id игнорируются. Offline."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir_storyboard import db, matrix


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "reorder.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "co", "Co")
    matrix.ensure_full_grid(c, "co")
    return c


def test_reorder_sets_order(conn):
    ids = [matrix.add_fact(conn, client_id="co", subsection_id="2.1",
                           text=f"f{i}", flag="green") for i in range(3)]
    # переставим: последний наверх
    new_order = [ids[2], ids[0], ids[1]]
    n = matrix.reorder_facts(conn, "co", "2.1", new_order)
    assert n == 3
    got = [r["id"] for r in matrix.facts_for_cell(conn, "co", "2.1")]
    assert got == new_order


def test_reorder_ignores_foreign_ids(conn):
    a = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="a", flag="green")
    other = matrix.add_fact(conn, client_id="co", subsection_id="3.1", text="x", flag="green")
    n = matrix.reorder_facts(conn, "co", "2.1", [999999, other, a])
    assert n == 1   # только a реально в 2.1
