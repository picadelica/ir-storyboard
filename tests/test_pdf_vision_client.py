"""Regression: extract_facts_from_pdf must read the real Anthropic client from the
MODULE global `_client`. _try_init_anthropic once assigned `_client` as a closure
local (not in the `global` decl), so PDF vision saw None and silently returned []
even with a valid API key — both 'Произвольный PDF' and 'От клиента' auto-parse
yielded zero facts. This test fails if `_client` stops being a module global."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir_storyboard import llm


class _Block:
    type = "text"
    def __init__(self, text): self.text = text


class _Resp:
    def __init__(self, text): self.content = [_Block(text)]


class _Messages:
    def __init__(self, payload): self._payload = payload; self.calls = 0
    def create(self, **kw): self.calls += 1; return _Resp(self._payload)


class _FakeClient:
    def __init__(self, payload): self.messages = _Messages(payload)


def test_pdf_vision_uses_module_global_client(monkeypatch):
    payload = '{"facts":[{"text":"Основатель вырос в семье инженеров.",' \
              '"subsection_id":"1.1","flag":"green","confidence":0.9}]}'
    fake = _FakeClient(payload)
    # set the MODULE global exactly as _try_init_anthropic should
    monkeypatch.setattr(llm, "_client", fake, raising=False)

    facts = llm.extract_facts_from_pdf(b"%PDF-1.4 fake", ["1.1", "4.1"])
    assert fake.messages.calls == 1, "vision client was never called — _client not visible"
    assert len(facts) == 1
    assert facts[0].subsection_id == "1.1"
    assert "инженеров" in facts[0].text


def test_pdf_vision_no_client_returns_empty(monkeypatch):
    monkeypatch.setattr(llm, "_client", None, raising=False)
    assert llm.extract_facts_from_pdf(b"%PDF-1.4", ["1.1"]) == []


def test_try_init_promotes_client_to_module_global(monkeypatch):
    """The actual root-cause guard: _try_init_anthropic must assign `_client` as a
    MODULE global (it once declared it only as a closure local). With a key set,
    llm._client must become non-None at module scope."""
    # _try_init_anthropic also rebinds these module-level callables to real impls;
    # pin them so monkeypatch restores the stubs at teardown (no leak to other tests).
    for name in ("generate", "classify_fact", "summarize", "classify_facts_batch"):
        monkeypatch.setattr(llm, name, getattr(llm, name))
    monkeypatch.setattr(llm, "_client", None, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-for-init")
    llm._try_init_anthropic()
    assert llm.__dict__.get("_client") is not None, \
        "_client did not reach module globals — closure-local regression"

