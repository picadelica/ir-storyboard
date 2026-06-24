"""Card titles: LLM batch generation (fills empty only) + analyst edit."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir_storyboard import db, matrix, llm, verification


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "titles.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "co", "Co")
    matrix.ensure_full_grid(c, "co")
    return c


def test_generate_titles_fills_empty_only(conn, monkeypatch):
    a = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Раунд A на $46M от профильных фондов.", flag="green")
    b = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Штаб-квартира в Майами.", flag="green")
    matrix.set_fact_title(conn, b, "Ручной заголовок")   # manual — must be preserved

    def _gen(system, user, *a, **k):
        import re
        ids = [int(x) for x in re.findall(r"\[(\d+)\]", user)]
        return json.dumps({"titles": [{"id": i, "title": "Авто заголовок"} for i in ids]}, ensure_ascii=False)
    monkeypatch.setattr(llm, "generate", _gen)

    res = verification.generate_fact_titles(conn, "co")
    assert res["available"] and res["titled"] == 1     # only the empty one (a)
    assert matrix.get_fact(conn, a)["title"] == "Авто заголовок"
    assert matrix.get_fact(conn, b)["title"] == "Ручной заголовок"   # untouched


def test_set_fact_title(conn):
    f = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="x", flag="green")
    matrix.set_fact_title(conn, f, "  Мой заголовок  ")
    assert matrix.get_fact(conn, f)["title"] == "Мой заголовок"
