"""Founder auto-discovery: web+LLM proposals, links grounded to evidence URLs."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir_storyboard import db, matrix, company, llm


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "fnd.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "co", "Acme")
    matrix.ensure_full_grid(c, "co")
    return c


def test_founder_discovery_grounds_links(conn, monkeypatch):
    hits = [
        llm.SearchHit("Acme team", "https://acme.com/about", "Jane Roe founder & CEO"),
        llm.SearchHit("Jane on LinkedIn", "https://linkedin.com/in/janeroe", "CEO at Acme"),
    ]
    monkeypatch.setattr(llm, "web_search", lambda q, n=6: hits)

    def _gen(system, user, *a, **k):
        return json.dumps({"founders": [
            {"name": "Jane Roe", "role": "сооснователь, CEO",
             "source_url": "https://acme.com/about",
             "profiles": [
                 {"label": "LinkedIn", "url": "https://linkedin.com/in/janeroe"},   # grounded → kept
                 {"label": "X", "url": "https://x.com/madeup"},                      # not in evidence → dropped
             ]},
        ]}, ensure_ascii=False)
    monkeypatch.setattr(llm, "generate", _gen)

    res = company.build_founder_proposals(conn, "co")
    assert res["available"]
    assert len(res["founders"]) == 1
    f = res["founders"][0]
    assert f["name"] == "Jane Roe"
    assert f["links"] == {"LinkedIn": "https://linkedin.com/in/janeroe"}   # ungrounded X dropped
    assert res["stats"]["dropped_ungrounded"] >= 1


def test_founder_profiles_grounds_links_and_photo(conn, monkeypatch):
    hits = [
        llm.SearchHit("Jane LinkedIn", "https://linkedin.com/in/janeroe", "CEO Acme"),
        llm.SearchHit("Jane X", "https://x.com/janeroe", "founder"),
    ]
    monkeypatch.setattr(llm, "web_search", lambda q, n=6: hits)
    monkeypatch.setattr(llm, "generate", lambda s, u, *a, **k: json.dumps({
        "profiles": [
            {"label": "LinkedIn", "url": "https://linkedin.com/in/janeroe"},   # grounded
            {"label": "X", "url": "https://x.com/janeroe"},                    # grounded
            {"label": "Сайт", "url": "https://made-up.example"},               # ungrounded → dropped
        ],
        "photo": "https://cdn.example/jane.jpg",   # image ext → kept best-effort
    }))
    res = company.build_founder_profiles(conn, "co", "Jane Roe")
    assert res["available"]
    assert res["links"] == {"LinkedIn": "https://linkedin.com/in/janeroe", "X": "https://x.com/janeroe"}
    assert res["photo"].endswith("jane.jpg")
    assert res["stats"]["dropped_ungrounded"] >= 1


def test_founder_discovery_skips_existing(conn, monkeypatch):
    matrix.add_entity(conn, client_id="co", kind="founder", name="Jane Roe", confirmed=True)
    monkeypatch.setattr(llm, "web_search", lambda q, n=6:
                        [llm.SearchHit("t", "https://acme.com/about", "Jane Roe founder")])
    monkeypatch.setattr(llm, "generate", lambda s, u, *a, **k: json.dumps(
        {"founders": [{"name": "Jane Roe", "role": "CEO", "source_url": "https://acme.com/about",
                       "profiles": [{"label": "Сайт", "url": "https://acme.com/about"}]}]}))
    res = company.build_founder_proposals(conn, "co")
    assert res["founders"] == []          # already on the card → not re-proposed
    assert res["stats"]["duplicates"] == 1
