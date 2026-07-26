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


def test_about_base_company_ignored(conn, monkeypatch):
    """Тег «про компанию» == БАЗОВАЯ компания → нормализуется в пустой: НЕ клампится в L1/L2
    (в отличие от тега про ДРУГУЮ компанию), и в промпт уходит без ложной подсказки."""
    matrix.upsert_client(conn, "co", "Accumulator")
    base = matrix.add_fact(conn, client_id="co", subsection_id="6.3", text="про базовую", flag="green")
    matrix.set_fact_about_company(conn, base, "Accumulator")        # = базовая
    other = matrix.add_fact(conn, client_id="co", subsection_id="6.3", text="про Gett", flag="green")
    matrix.set_fact_about_company(conn, other, "Gett")              # ДРУГАЯ

    seen = {}
    def fake_reclassify(texts, descriptions=None, client_notes=None, about_companies=None, **kw):
        seen["about"] = list(about_companies or [])
        return [FactCandidate(text=t, suggested_subsection_id="4.2",   # LLM предлагает L4
                              suggested_flag="green", confidence=0.9, rationale="t") for t in texts]
    monkeypatch.setattr(main, "reclassify_facts", fake_reclassify)
    res = main._compute_methodology_moves(conn, "co")
    to = {m["fact_id"]: m["to_sid"] for m in res["moves"]}
    assert to.get(base) == "4.2"          # базовый тег проигнорирован → НЕ клампится, остаётся L4
    assert to.get(other) == "2.1"         # другой компании → гард увёл в L2
    # в reclassify базовый тег ушёл пустым, другой — как есть
    assert seen["about"] == ["", "Gett"]


def test_reclassify_facts_no_key_fallback(conn):
    # без ANTHROPIC_API_KEY generate_json → None → keyword-стаб, без падения
    out = reclassify_facts(["some fact text about revenue growth"], {}, {})
    assert len(out) == 1
    assert isinstance(out[0], FactCandidate)


def test_reclassify_chunks_large_batch(monkeypatch):
    """Большой батч бьётся на чанки (иначе вывод обрезается по max_tokens → стаб на всё).
    Каждый чанк — отдельный generate_json; все факты возвращаются в порядке."""
    from ir_storyboard import llm
    calls = {"n": 0, "sizes": []}

    def fake_gen(system, user, **kw):
        calls["n"] += 1
        n = user.count("\n") + 1  # строк = фактов в чанке
        calls["sizes"].append(n)
        return {"results": [{"sid": "2.1", "conf": 0.9, "rationale": "ok"} for _ in range(n)]}

    monkeypatch.setattr(llm, "generate_json", fake_gen)
    monkeypatch.setenv("LLM_RECLASSIFY_CHUNK", "25")
    texts = [f"fact {i}" for i in range(60)]
    out = llm.reclassify_facts(texts, {}, {})
    assert len(out) == 60
    assert calls["n"] == 3          # 25 + 25 + 10
    assert calls["sizes"] == [25, 25, 10]
    assert all(c.suggested_subsection_id == "2.1" for c in out)
