"""cell_summary splits must-have count by origin (client=blue / expert=purple)."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir_storyboard import db, matrix


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "split.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "co", "Co")
    matrix.ensure_full_grid(c, "co")
    return c


def test_cell_summary_must_split(conn):
    a = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="cl", flag="green")
    matrix.set_fact_must_have(conn, a, source="client")
    b = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="ex", flag="green")
    matrix.set_fact_must_have(conn, b, source="expert")
    c2 = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="plain", flag="green")  # no star

    row = next(r for r in matrix.cell_summary(conn, "co") if r["subsection_id"] == "2.1")
    assert row["n_must"] == 2
    assert row["n_must_client"] == 1
    assert row["n_must_expert"] == 1
