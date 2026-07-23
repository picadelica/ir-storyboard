"""Кросс-компанийный фаундер: founders_by_name находит того же человека в других
компаниях; import_founder_profile вливает ссылки/роль/note без перетирания. Offline."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir_storyboard import db, matrix


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "cross.db")
    db.init_schema(c)
    for cid, nm in [("a", "Alpha"), ("b", "Beta")]:
        matrix.upsert_client(c, cid, nm)
    return c


def test_founders_by_name_excludes_self(conn):
    matrix.add_entity(conn, client_id="a", kind="founder", name="Dave Waiser",
                      role="CEO", links={"linkedin": "u/dave"}, note="серийный")
    matrix.add_entity(conn, client_id="b", kind="founder", name="dave waiser ")  # регистр/пробел
    m = matrix.founders_by_name(conn, "Dave Waiser", exclude_client="b")
    assert len(m) == 1 and m[0]["client_id"] == "a"
    assert m[0]["links"] == {"linkedin": "u/dave"}
    # без exclude — обе
    assert len(matrix.founders_by_name(conn, "DAVE WAISER")) == 2


def test_import_profile_merges(conn):
    src = matrix.add_entity(conn, client_id="a", kind="founder", name="Dave",
                            role="CEO", canonical_url="https://d.com",
                            links={"linkedin": "u/dave", "x": "@dave"}, note="серийный")
    tgt = matrix.add_entity(conn, client_id="b", kind="founder", name="Dave",
                            links={"x": "@dave_b"})   # свой x — не перетирать
    out = matrix.import_founder_profile(conn, tgt, src)
    import json
    links = json.loads(out["links"])
    assert links["linkedin"] == "u/dave"        # долит
    assert links["x"] == "@dave_b"              # target-значение сохранено
    assert out["role"] == "CEO" and out["note"] == "серийный"  # заполнено из src
    assert out["canonical_url"] == "https://d.com"
