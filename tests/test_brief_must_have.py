"""Brief weighting: client must-have → 'обязательно' block, expert → 'важное' block."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir_storyboard import db, matrix, brief


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "brief.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "co", "Co")
    matrix.ensure_full_grid(c, "co")
    return c


def test_brief_splits_client_and_expert_must_have(conn):
    cf = matrix.add_fact(conn, client_id="co", subsection_id="4.1", text="Клиентский ключевой факт.", flag="green")
    ef = matrix.add_fact(conn, client_id="co", subsection_id="4.2", text="Экспертный важный факт.", flag="green")
    matrix.set_fact_must_have(conn, cf, "client")
    matrix.set_fact_must_have(conn, ef, "expert")

    factology = brief.collect_factology(conn, "co")
    md = brief.render_md({"id": "co", "name": "Co"}, {"name": "T", "body": ""}, "", factology)

    assert "Must-have от клиента (ОБЯЗАТЕЛЬНО" in md
    assert "Важное от эксперта" in md
    # client fact under the client block, expert under the expert block
    client_idx = md.index("Клиентский ключевой факт.")
    expert_idx = md.index("Экспертный важный факт.")
    client_hdr = md.index("Must-have от клиента")
    expert_hdr = md.index("Важное от эксперта")
    assert client_hdr < client_idx < expert_hdr < expert_idx
