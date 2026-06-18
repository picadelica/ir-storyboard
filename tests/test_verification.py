"""Fact verification: entity-conflation audit + web verify. Offline — the LLM and
web-search calls are monkeypatched, so this runs under `-m "not network"`."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix, llm, verification


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "verif.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "co", "Co")
    matrix.ensure_full_grid(c, "co")
    return c


def _seed_facts(conn):
    f_research = matrix.add_fact(conn, client_id="co", subsection_id="2.1",
                                 text="Khachuyan is CEO of the company.", flag="green")
    f_clean = matrix.add_fact(conn, client_id="co", subsection_id="2.1",
                              text="Company was founded by the Liberman siblings.", flag="green")
    f_transcript = matrix.add_fact(conn, client_id="co", subsection_id="1.2",
                                   text="Said in a podcast that values matter.", flag="green")
    # mark one fact as transcript-grounded (youtube/audio) → must be skipped by verifier
    conn.execute("UPDATE facts SET snippet_start_sec=12.0 WHERE id=?", (f_transcript,))
    conn.commit()
    return f_research, f_clean, f_transcript


def test_verifiable_facts_skips_transcript(conn):
    f_research, f_clean, f_transcript = _seed_facts(conn)
    ids = {f["id"] for f in verification.verifiable_facts(conn, "co")}
    assert f_research in ids and f_clean in ids
    assert f_transcript not in ids  # grounded by timecode → trusted, not audited


def test_audit_maps_verdicts_and_filters_unknown_ids(conn, monkeypatch):
    f_research, f_clean, _ = _seed_facts(conn)
    canned = {
        "canonical": {"company": "RealCo", "founders": ["Liberman"], "decoys": ["Khachuyan"]},
        "summary": "Three founders conflated into one.",
        "facts": [
            {"id": f_research, "verdict": "refuted", "entity": "Khachuyan — иное лицо", "reason": "OSINT профиль не стыкуется"},
            {"id": 999999, "verdict": "suspect", "entity": "x", "reason": "не существует — должен отфильтроваться"},
        ],
    }
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(canned, ensure_ascii=False))
    res = verification.audit_client(conn, "co")
    assert res["available"] is True
    assert res["canonical"]["company"] == "RealCo"
    ids = {f["id"]: f for f in res["facts"]}
    assert f_research in ids and ids[f_research]["verdict"] == "refuted"
    assert 999999 not in ids  # unknown fact id dropped
    assert f_clean not in ids  # clean fact not flagged


def test_audit_stub_unavailable(conn, monkeypatch):
    _seed_facts(conn)
    monkeypatch.setattr(llm, "generate", lambda *a, **k: "")  # stub mode
    res = verification.audit_client(conn, "co")
    assert res["available"] is False and res["facts"] == []


def test_verify_claims_web(monkeypatch):
    monkeypatch.setattr(llm, "web_search",
                        lambda q, n=6: [llm.SearchHit("TechCrunch", "https://tc.com/x", "Product Science raised $18M")])
    canned = {"results": [
        {"id": "C1", "verdict": "refuted", "attribution": "Product Science", "reason": "TechCrunch attributes the round to Product Science"}]}
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(canned, ensure_ascii=False))
    out = verification.verify_claims([{"id": "C1", "claim": "$18M round is the company's", "query": "Product Science 18M"}])
    assert out["available"] is True
    r = out["results"][0]
    assert r["verdict"] == "refuted" and r["attribution"] == "Product Science"
    assert r["sources"][0]["url"] == "https://tc.com/x"


def test_verify_claims_no_hits_unavailable(monkeypatch):
    monkeypatch.setattr(llm, "web_search", lambda q, n=6: [])
    out = verification.verify_claims([{"id": "C1", "claim": "x", "query": "x"}])
    assert out["available"] is False


def test_gate_no_anchor_passes_all():
    out = verification.verify_candidates([{"text": "x", "subsection_id": "2.1"}], {})
    assert out == [{"verdict": "ok", "entity": "", "reason": ""}]


def test_gate_stub_passes_all(monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda *a, **k: "")
    out = verification.verify_candidates([{"text": "x", "subsection_id": "2.1"}], {"company": "C"})
    assert out[0]["verdict"] == "ok"  # degrade open — don't block ingest


def test_gate_flags_decoy_against_anchor(monkeypatch):
    canned = {"facts": [{"i": 0, "verdict": "refuted", "entity": "Khachuyan", "reason": "двойник"}]}
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(canned, ensure_ascii=False))
    out = verification.verify_candidates(
        [{"text": "Khachuyan is CEO", "subsection_id": "2.1"},
         {"text": "Founded by Liberman", "subsection_id": "2.1"}],
        {"company": "Gonka", "founders": ["Liberman"], "decoys": ["Khachuyan"]})
    assert out[0]["verdict"] == "refuted" and out[0]["entity"] == "Khachuyan"
    assert out[1]["verdict"] == "ok"  # clean candidate passes the gate
