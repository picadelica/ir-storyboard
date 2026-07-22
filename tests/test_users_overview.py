"""«Пользователи системы»: обзор кто-есть-кто (роль/активность) + owner-скоуп контрибьюторов."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir_storyboard import db, matrix


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "users.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "co", "Co")
    matrix.ensure_full_grid(c, "co")
    return c


def test_users_overview_enrichment(conn):
    matrix.upsert_user(conn, 1, "Owner", "own")
    matrix.upsert_user(conn, 2, "Contributor", "contrib")
    matrix.set_client_owner(conn, "co", 1)
    # факт внёс контрибьютор (tid=2)
    matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="f1", flag="green",
                    created_by_tid=2)

    ov = {u["tid"]: u for u in matrix.users_overview(conn)}
    assert ov[1]["owned_clients"] == ["Co"] and ov[1]["facts_created"] == 0
    assert ov[2]["owned_clients"] == [] and ov[2]["facts_created"] == 1


def test_contributor_scope_for_owner(conn):
    matrix.upsert_user(conn, 1, "Owner", "")
    matrix.upsert_user(conn, 2, "Contributor", "")
    matrix.upsert_user(conn, 3, "Stranger", "")  # к этой компании отношения не имеет
    matrix.set_client_owner(conn, "co", 1)
    matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="f", flag="green",
                    created_by_tid=2)

    contributors = matrix.contributor_tids_for_clients(conn, ["co"])
    assert contributors == {2}
    # owner-скоуп обзора: контрибьюторы + сам владелец, без постороннего
    scope = contributors | {1}
    tids = {u["tid"] for u in matrix.users_overview(conn, only_tids=scope)}
    assert tids == {1, 2} and 3 not in tids
