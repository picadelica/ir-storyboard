"""Grounded interview guide — structure, verified-only grounding, stub-safety. Offline."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix, llm, interview


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "iv.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "co", "Co")
    matrix.ensure_full_grid(c, "co")
    return c


def test_build_guide_structure(conn, monkeypatch):
    matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Sold to Snap 2016.", flag="green")
    matrix.add_fact(conn, client_id="co", subsection_id="1.3", text="Fears AI future.", flag="red",
                    rationale="личный страх — эмоциональное ядро")
    canned = {
        "dossier": "Founder X builds decentralized AI.",
        "diagnosis": {"covered": "product", "gaps": "childhood", "priorities": ["1.1 пусто", "1.3 раскрыть"]},
        "arcs": [{"title": "Человек", "questions": [
            {"question": "Расскажи про детство?", "targets": ["1.1"], "know": "мало",
             "close": "1.1", "followups": ["а потом?"]},
            {"question": "no targets ok", "targets": []},
            {"targets": ["1.1"]},  # no question → dropped
        ]}],
    }
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(canned, ensure_ascii=False))
    g = interview.build_guide(conn, "co")
    assert g["available"] and g["dossier"].startswith("Founder X")
    assert g["diagnosis"]["priorities"] == ["1.1 пусто", "1.3 раскрыть"]
    qs = g["arcs"][0]["questions"]
    assert len(qs) == 2  # the question-less one dropped
    assert qs[0]["targets"] == ["1.1"] and qs[0]["followups"] == ["а потом?"]


def test_build_guide_excludes_flagged_facts(conn, monkeypatch):
    matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Clean grounded fact.", flag="green")
    fid = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Khachuyan is CEO.", flag="green")
    matrix.set_fact_verification(conn, fid, verification="suspect")  # flagged → must not ground
    captured = {}
    monkeypatch.setattr(llm, "generate", lambda system, user, **k: (captured.update(user=user), "{}")[1])
    interview.build_guide(conn, "co")
    assert "Clean grounded fact" in captured["user"]
    assert "Khachuyan" not in captured["user"]


def test_build_guide_stub_unavailable(conn, monkeypatch):
    matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="x", flag="green")
    monkeypatch.setattr(llm, "generate", lambda *a, **k: "")
    assert interview.build_guide(conn, "co")["available"] is False
