"""Deliver matrix export: texts only, star/card colors, company card, active-only."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir_storyboard import db, matrix, deliver


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "deliver.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "co", "Co", sector="fintech", one_liner="платежи")
    matrix.ensure_full_grid(c, "co")
    return c


def test_export_shape_and_colors(conn):
    a = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Раунд A $46M", flag="green")
    matrix.set_fact_title(conn, a, "Раунд A")
    matrix.set_fact_must_have(conn, a, source="client")          # синяя звезда
    b = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Риск оттока", flag="red", rationale="нет данных")
    matrix.set_fact_must_have(conn, b, source="expert")          # фиолетовая звезда
    matrix.add_fact(conn, client_id="co", subsection_id="2.2", text="Обычный факт", flag="grey", rationale="gap")

    out = deliver.build_matrix_export(conn, "co")

    assert out["export"]["client_name"] == "Co"
    assert out["export"]["card_count"] == 3
    assert "card_color" in out["export"]["legend"] and "star_color" in out["export"]["legend"]

    by_text = {c["text"]: c for c in out["cards"]}
    assert by_text["Раунд A $46M"]["title"] == "Раунд A"
    assert by_text["Раунд A $46M"]["star"] == "blue"
    assert by_text["Раунд A $46M"]["card_color"] == "green"
    assert by_text["Раунд A $46M"]["matrix_no"] == "2.1"
    assert by_text["Риск оттока"]["star"] == "purple"
    assert by_text["Обычный факт"]["star"] is None

    # no source/link fields leak into cards
    assert all("source_url" not in c and "source" not in c for c in out["cards"])


def test_export_excludes_rejected(conn):
    keep = matrix.add_fact(conn, client_id="co", subsection_id="3.1", text="keep", flag="green")
    drop = matrix.add_fact(conn, client_id="co", subsection_id="3.1", text="drop", flag="green")
    matrix.set_fact_state(conn, drop, "rejected")
    texts = [c["text"] for c in deliver.build_matrix_export(conn, "co")["cards"]]
    assert "keep" in texts and "drop" not in texts


def test_company_card(conn):
    eid = matrix.add_entity(conn, client_id="co", kind="company", name="Co Inc", role="платёжная компания")
    matrix.add_entity_fact(conn, entity_id=eid, key="founded", value="2019", section="profile")
    out = deliver.build_matrix_export(conn, "co")
    assert out["company_card"]["name"] == "Co Inc"
    facts = out["company_card"]["facts"]
    assert {"section": "profile", "key": "founded", "value": "2019"} in facts
    # no source links in company card facts
    assert all(set(f.keys()) == {"section", "key", "value"} for f in facts)
