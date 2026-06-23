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


def test_parse_json_tolerates_preamble_and_fences():
    # Bare object
    assert verification._parse_json('{"a": 1}') == {"a": 1}
    # Fenced block with a ```json hint
    assert verification._parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    # The real-world failure: prose preamble, then a fenced JSON block (sonnet)
    chatty = ('I need to analyze these facts.\n\nKey observations:\n'
              '1. **Facts 324-327** look conflated.\n\n```json\n'
              '{"canonical": {"company": "Gonka"}, "facts": [{"id": 1, "verdict": "refuted"}]}\n```')
    parsed = verification._parse_json(chatty)
    assert parsed is not None
    assert parsed["canonical"]["company"] == "Gonka"
    assert parsed["facts"][0]["id"] == 1
    # Prose then a bare (unfenced) object
    assert verification._parse_json('Here is the result:\n{"facts": []}')["facts"] == []
    # Genuinely empty / non-JSON stays None
    assert verification._parse_json("") is None
    assert verification._parse_json("no json here at all") is None


def test_generate_json_retries_on_empty(monkeypatch):
    calls = {"n": 0}

    def flaky(system, user, **k):
        calls["n"] += 1
        return "" if calls["n"] == 1 else '{"ok": true}'

    monkeypatch.setattr(llm, "generate", flaky)
    out = verification._generate_json("s", "u", max_tokens=100, model="m", attempts=2)
    assert out == {"ok": True}
    assert calls["n"] == 2  # first empty reply retried


def test_audit_recovers_from_transient_empty(conn, monkeypatch):
    f_research, _f_clean, _ = _seed_facts(conn)
    seq = ["", json.dumps({"canonical": {"company": "RealCo"}, "summary": "",
                           "facts": [{"id": f_research, "verdict": "suspect", "entity": "x", "reason": "y"}]})]
    monkeypatch.setattr(llm, "generate", lambda *a, **k: seq.pop(0) if seq else "")
    res = verification.audit_client(conn, "co")
    assert res["available"] is True
    assert res["canonical"]["company"] == "RealCo"


def test_audit_parses_chatty_model_reply(conn, monkeypatch):
    f_research, _f_clean, _ = _seed_facts(conn)
    reply = (f'Let me check.\n\n```json\n{{"canonical": {{"company": "RealCo"}}, '
             f'"summary": "ok", "facts": [{{"id": {f_research}, "verdict": "refuted", '
             f'"entity": "Khachuyan", "reason": "иное лицо"}}]}}\n```')
    monkeypatch.setattr(llm, "generate", lambda *a, **k: reply)
    res = verification.audit_client(conn, "co")
    assert res["available"] is True
    assert res["canonical"]["company"] == "RealCo"
    assert any(f["id"] == f_research and f["verdict"] == "refuted" for f in res["facts"])


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


def test_find_duplicate_groups(conn, monkeypatch):
    a = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Raised $50M from Bitfury.", flag="green")
    b = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Bitfury invested $50M.", flag="green")
    d = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="HQ in UAE.", flag="green")
    canned = {"groups": [
        {"subsection_id": "2.1", "keep": a, "ids": [a, b], "reason": "тот же раунд"},
        {"subsection_id": "2.1", "keep": a, "ids": [a]},          # <2 → dropped
        {"subsection_id": "2.1", "keep": a, "ids": [a, 999999]},  # unknown id collapses to <2 → dropped
    ]}
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(canned, ensure_ascii=False))
    res = verification.find_duplicate_groups(conn, "co")
    assert res["available"] and len(res["groups"]) == 1
    g = res["groups"][0]
    assert set(g["ids"]) == {a, b} and g["keep"] == a and d not in g["ids"]


def test_merge_with_curated_text_creates_new_fact(conn):
    """merged_text → a NEW fact carries the analyst wording; all originals (incl.
    the old keep) are rejected; sources fold onto the new fact (immutability)."""
    a = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Raised $50M.", flag="green")
    b = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Bitfury put in $50M.", flag="green")
    c = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Round led by Bitfury.", flag="green")

    new_id = matrix.merge_facts(conn, a, [b, c], "Привлекли $50M в раунде под лид Bitfury.")
    assert new_id not in (a, b, c)

    new = matrix.get_fact(conn, new_id)
    assert new["state"] == "active"
    assert "под лид Bitfury" in new["text"]
    for oid in (a, b, c):
        assert matrix.get_fact(conn, oid)["state"] == "rejected"
    # the merged fact carries corroboration from the originals
    assert matrix.fact_corroboration(conn, new_id) >= 2


def test_merge_without_text_keeps_original(conn):
    """No merged_text → legacy behavior: keep stays active, dupes rejected."""
    a = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Raised $50M.", flag="green")
    b = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Bitfury put in $50M.", flag="green")
    res = matrix.merge_facts(conn, a, [b])
    assert res == a
    assert matrix.get_fact(conn, a)["state"] == "active"
    assert matrix.get_fact(conn, b)["state"] == "rejected"


def test_find_unattributed_single_founder_autofills(conn, monkeypatch):
    """One founder on the card → proposed_text names them automatically; an L1 fact
    is flagged must_be_concrete."""
    matrix.add_entity(conn, client_id="co", kind="founder", name="Давид Вайсман")
    f = matrix.add_fact(conn, client_id="co", subsection_id="1.2",
                        text="Фаундер считает, что прозрачность — ключевая ценность.", flag="green")
    canned = {"items": [
        {"id": f, "generic": "Фаундер считает",
         "rewrite": "[ИМЯ] считает, что прозрачность — ключевая ценность."},
    ]}
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(canned, ensure_ascii=False))
    res = verification.find_unattributed_facts(conn, "co")
    assert res["available"] and len(res["items"]) == 1
    it = res["items"][0]
    assert it["needs_choice"] is False
    assert it["proposed_text"] == "Давид Вайсман считает, что прозрачность — ключевая ценность."
    assert it["must_be_concrete"] is True   # L1.2


def test_find_unattributed_multi_founder_needs_choice(conn, monkeypatch):
    matrix.add_entity(conn, client_id="co", kind="founder", name="Алексей Либерман")
    matrix.add_entity(conn, client_id="co", kind="founder", name="Дмитрий Либерман")
    f = matrix.add_fact(conn, client_id="co", subsection_id="2.2",
                        text="Основатель предложил сменить модель монетизации.", flag="green")
    canned = {"items": [{"id": f, "generic": "Основатель предложил",
                         "rewrite": "[ИМЯ] предложил сменить модель монетизации."}]}
    monkeypatch.setattr(llm, "generate", lambda *a, **k: json.dumps(canned, ensure_ascii=False))
    res = verification.find_unattributed_facts(conn, "co")
    it = res["items"][0]
    assert it["needs_choice"] is True
    assert "[ИМЯ]" in it["proposed_text"]   # not auto-filled — analyst must pick


def test_attribute_fact_creates_named_fact(conn):
    eid = matrix.add_entity(conn, client_id="co", kind="founder", name="Давид Вайсман")
    f = matrix.add_fact(conn, client_id="co", subsection_id="1.2",
                        text="Фаундер считает X.", flag="green")
    new_id = matrix.attribute_fact(conn, f, eid, "Давид Вайсман считает X.")
    assert new_id != f
    new = matrix.get_fact(conn, new_id)
    assert new["state"] == "active" and new["speaker_entity_id"] == eid
    assert new["text"] == "Давид Вайсман считает X."
    assert matrix.get_fact(conn, f)["state"] == "rejected"


def test_find_duplicates_stub(conn, monkeypatch):
    matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="x", flag="green")
    matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="y", flag="green")
    monkeypatch.setattr(llm, "generate", lambda *a, **k: "")
    assert verification.find_duplicate_groups(conn, "co")["available"] is False
