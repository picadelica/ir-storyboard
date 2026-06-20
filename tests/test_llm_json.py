"""Universal LLM structured-output primitives: extract_json / generate_json.

These back every place that asks the model for JSON, so the chatty-model
failure modes (prose preamble, fenced block, truncation) are handled once."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import llm


def test_extract_json_bare_object_and_array():
    assert llm.extract_json('{"a": 1}') == {"a": 1}
    assert llm.extract_json('[1, 2, 3]') == [1, 2, 3]


def test_extract_json_fenced_anywhere():
    assert llm.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.extract_json('prefix text\n```\n{"a": 1}\n```\nsuffix') == {"a": 1}


def test_extract_json_prose_preamble():
    chatty = ('I need to analyze these facts.\n\nKey observations:\n'
              '1. **Facts** look conflated.\n\n```json\n'
              '{"canonical": {"company": "Gonka"}, "facts": [{"id": 1}]}\n```')
    out = llm.extract_json(chatty)
    assert out["canonical"]["company"] == "Gonka"
    # unfenced object after prose
    assert llm.extract_json('Here it is: {"facts": []}') == {"facts": []}


def test_extract_json_empty_or_garbage():
    assert llm.extract_json("") is None
    assert llm.extract_json(None) is None
    assert llm.extract_json("no json here") is None


def test_extract_json_repairs_truncation():
    truncated = '{"facts": [{"text": "a"}, {"text": "b"}, {"text": "c'
    assert llm.extract_json(truncated) is None              # off by default
    repaired = llm.extract_json(truncated, repair=True)
    assert repaired is not None
    assert [f["text"] for f in repaired["facts"]] == ["a", "b"]


def test_generate_json_retries_on_empty(monkeypatch):
    calls = {"n": 0}

    def flaky(system, user, **k):
        calls["n"] += 1
        return "" if calls["n"] == 1 else 'prose then {"ok": true}'

    monkeypatch.setattr(llm, "generate", flaky)
    assert llm.generate_json("s", "u", attempts=2) == {"ok": True}
    assert calls["n"] == 2


def test_generate_json_gives_up_in_stub(monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda *a, **k: "")
    assert llm.generate_json("s", "u", attempts=3) is None
