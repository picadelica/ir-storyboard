"""Company About auto-fill: source grounding (only facts with a real supplied
URL survive), dedup vs the card, stub-safety. Offline — LLM/web monkeypatched."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix, llm, company


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "co.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "demo", "Gonka AI")
    matrix.ensure_full_grid(c, "demo")
    sid = matrix.add_source(c, "online_research", title="TechCrunch", url="https://techcrunch.com/gonka")
    matrix.add_fact(c, client_id="demo", subsection_id="2.1", text="Raised $10M seed in 2024.",
                    flag="green", source_id=sid)
    matrix.add_entity(c, client_id="demo", kind="company", name="Gonka AI", confirmed=True)
    return c


def _patch_web(monkeypatch, hits):
    monkeypatch.setattr(llm, "web_search",
                        lambda q, n=5: [llm.SearchHit(title=h[0], url=h[1], snippet=h[2]) for h in hits])


def test_autofill_keeps_only_grounded_facts(conn, monkeypatch):
    _patch_web(monkeypatch, [("Gonka raises seed", "https://techcrunch.com/gonka", "…seed round…")])
    canned = {"proposals": [
        # grounded in the matrix fact's URL → kept
        {"section": "funding", "key": "Seed", "value": "$10M, 2024", "source_url": "https://techcrunch.com/gonka", "source_title": "TechCrunch"},
        # grounded in a web hit URL → kept
        {"section": "profile", "key": "Категория", "value": "Decentralized AI compute", "source_url": "https://techcrunch.com/gonka"},
        # URL not in evidence → fabricated → MUST be dropped
        {"section": "history", "key": "IPO", "value": "IPO 2025", "source_url": "https://made-up.example/ipo"},
        # no source at all → dropped
        {"section": "metrics", "key": "ARR", "value": "$5M", "source_url": ""},
    ]}
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(canned, ensure_ascii=False))
    res = company.build_about_proposals(conn, "demo")
    assert res["available"]
    vals = {p["value"] for p in res["proposals"]}
    assert "$10M, 2024" in vals and "Decentralized AI compute" in vals
    assert "IPO 2025" not in vals          # fabricated URL filtered
    assert "$5M" not in vals               # no source filtered
    assert res["stats"]["dropped_ungrounded"] == 2
    assert all(p["source_url"] for p in res["proposals"])  # every kept fact is source-linked


def test_autofill_dedupes_existing_card_facts(conn, monkeypatch):
    ent = next(e for e in matrix.entities_for_client(conn, "demo") if e["kind"] == "company")
    matrix.add_entity_fact(conn, entity_id=ent["id"], value="$10M, 2024", source_url="https://techcrunch.com/gonka", section="funding")
    _patch_web(monkeypatch, [])
    canned = {"proposals": [{"section": "funding", "value": "$10M, 2024", "source_url": "https://techcrunch.com/gonka"}]}
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(canned, ensure_ascii=False))
    res = company.build_about_proposals(conn, "demo")
    assert res["proposals"] == []          # already on the card → not re-proposed
    assert res["stats"]["duplicates"] == 1


def test_autofill_stub_unavailable(conn, monkeypatch):
    _patch_web(monkeypatch, [("x", "https://techcrunch.com/gonka", "y")])
    monkeypatch.setattr(llm, "generate", lambda *a, **k: "")
    assert company.build_about_proposals(conn, "demo")["available"] is False
