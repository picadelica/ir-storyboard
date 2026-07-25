"""Раскладка по методологии: ручной перенос ЛОЧИТ факт (placement_locked) → авто-реклассификация
его не берёт; reclassify-перенос ставит reclassified_at; оба пишут в fact_placement_history."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir_storyboard import db, matrix


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "lock.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "co", "Co")
    matrix.ensure_full_grid(c, "co")
    return c


def test_manual_move_locks_and_excludes_from_reclassify(conn):
    a = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="a", flag="green")
    b = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="b", flag="green")
    # ручной перенос a → 3.1
    matrix.move_fact_to_subsection(conn, a, "co", "3.1", method="manual", moved_by="Эксперт", moved_by_tid=7)
    assert conn.execute("SELECT placement_locked FROM facts WHERE id=?", (a,)).fetchone()[0] == 1
    # a исключён из кандидатов на реклассификацию, b остаётся
    ids = {r["id"] for r in matrix.active_facts_for_reclassify(conn, "co")}
    assert a not in ids and b in ids
    # история записана
    h = matrix.fact_placement_history(conn, "co")
    assert h and h[0]["fact_id"] == a and h[0]["method"] == "manual"
    assert h[0]["from_sid"] == "2.1" and h[0]["to_sid"] == "3.1" and h[0]["moved_by"] == "Эксперт"


def test_reclassify_move_marks_not_locks(conn):
    b = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="b", flag="green")
    matrix.move_fact_to_subsection(conn, b, "co", "1.1", method="reclassify", moved_by="Дмитрий")
    row = conn.execute("SELECT placement_locked, reclassified_at FROM facts WHERE id=?", (b,)).fetchone()
    assert row[0] == 0                    # НЕ залочен — при новой методологии можно двигать
    assert row[1] is not None             # помечен как размещённый прогоном
    # b всё ещё в кандидатах (не залочен)
    assert b in {r["id"] for r in matrix.active_facts_for_reclassify(conn, "co")}
    h = matrix.fact_placement_history(conn, "co")
    assert h[0]["method"] == "reclassify" and h[0]["to_sid"] == "1.1"
