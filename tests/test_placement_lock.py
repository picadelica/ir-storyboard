"""Раскладка по методологии — версионирование (вместо жёсткого лока):
- перенос ставит assigned_methodology_version=текущая + assigned_by (expert/system);
- reclassify не показывает факты, уже отнесённые к ТЕКУЩЕЙ версии; смена версии → переоценка;
- гард: факт про другую компанию (about_company) не опускается ниже L2;
- всё пишется в fact_placement_history."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir_storyboard import db, matrix


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "ver.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "co", "Co")
    matrix.ensure_full_grid(c, "co")
    return c


def _cand_ids(conn):
    return {r["id"] for r in matrix.active_facts_for_reclassify(conn, "co")}


def test_move_assigns_version_and_author(conn):
    a = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="a", flag="green")
    b = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="b", flag="green")
    matrix.move_fact_to_subsection(conn, a, "co", "3.1", method="manual", moved_by="Эксперт", moved_by_tid=7)
    row = conn.execute("SELECT assigned_methodology_version, assigned_by FROM facts WHERE id=?", (a,)).fetchone()
    assert row[0] == 1 and row[1] == "expert"          # отнесён к текущей версии экспертом
    # a исключён (отнесён к текущей версии), b — нет
    assert a not in _cand_ids(conn) and b in _cand_ids(conn)
    h = matrix.fact_placement_history(conn, "co")
    assert h[0]["fact_id"] == a and h[0]["method"] == "manual" and h[0]["moved_by"] == "Эксперт"


def test_version_bump_reopens_facts(conn):
    a = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="a", flag="green")
    matrix.move_fact_to_subsection(conn, a, "co", "3.1", method="reclassify", moved_by="система")
    assert conn.execute("SELECT assigned_by FROM facts WHERE id=?", (a,)).fetchone()[0] == "system"
    assert a not in _cand_ids(conn)                    # отнесён к v1 → не показываем
    matrix.bump_methodology_version(conn)              # методология изменилась → v2
    assert a in _cand_ids(conn)                        # снова кандидат (v1 != v2)


def test_about_company_never_below_l2():
    clamp = matrix.clamp_about_company_to_l2
    # про другую компанию + предложено L4 → клампим (текущая L1-2 сохраняется, иначе 2.1)
    assert clamp("Gett", "4.2", "2.1") == "2.1"        # держим текущую L2
    assert clamp("Gett", "6.3", "5.1") == "2.1"        # текущая не L1-2 → 2.1
    assert clamp("Gett", "1.3", "2.1") == "1.3"        # предложено L1 → ок
    # без тега — не трогаем
    assert clamp("", "4.2", "2.1") == "4.2"


def test_clamp_company_tag_two_way():
    clamp = matrix.clamp_company_tag
    # ДРУГАЯ компания (is_current=False) → не ниже L2
    assert clamp("Gett", False, "4.2", "6.1") == "2.1"
    assert clamp("Gett", False, "1.3", "2.1") == "1.3"
    # ТЕКУЩАЯ компания (is_current=True) → НЕ в L1/L2: L3-8 пропускаем, L1/L2 → держим текущую
    assert clamp("Acc", True, "4.2", "5.1") == "4.2"   # L4 — ок
    assert clamp("Acc", True, "2.1", "5.1") == "5.1"   # LLM тянет в L2 → остаёмся в 5.1
    assert clamp("Acc", True, "1.1", "6.3") == "6.3"
    # пустой тег — не трогаем ни в ту, ни в другую сторону
    assert clamp("", True, "1.1", "6.3") == "1.1"
    assert clamp("", False, "4.2", "2.1") == "4.2"
