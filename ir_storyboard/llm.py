"""LLM/search abstraction.

The prototype works without API keys via deterministic stubs.
Plug in real providers by replacing the `classify_fact` and `web_search`
callables with implementations that call your model of choice.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, List, Optional

from .models import LAYERS, SubsectionSpec


@dataclass
class FactCandidate:
    text: str
    suggested_subsection_id: Optional[str]   # None if classifier can't decide
    suggested_flag: str                      # green / red / grey
    confidence: float = 0.5
    rationale: str = ""


# ---------- classifier ----------

# Tiny keyword-driven classifier so the prototype is deterministic
# and does not require API keys. Real implementation should replace
# `classify_fact` with an LLM call that returns the same shape.

KEYWORDS_BY_SUBSECTION = {
    "1.1": ["родил", "детств", "школ", "семья", "отец", "мать", "born", "childhood"],
    "1.2": ["верит", "ценност", "убежд", "believe", "values"],
    "1.3": ["страх", "потер", "уязвим", "fear", "loss", "vulnerab"],
    "1.4": ["мечт", "видение", "идентичн", "dream", "identity", "vision"],
    "2.1": ["опыт", "построил", "запустил", "founded", "built", "experience", "expertise"],
    "2.2": ["роль", "мотив", "role", "motivation", "ceo", "founder"],
    "2.3": ["сооснователь", "партнёр", "co-founder", "cofounder", "partner"],
    "3.1": ["отбор", "приглаш", "invite", "selection", "exclusive"],
    "3.2": ["сообществ", "событ", "встреч", "community", "event", "forum"],
    "3.3": ["инвестор", "партнёр", "investor", "partner"],
    "4.1": ["экспертиз", "разнообраз", "diversity", "expertise"],
    "4.2": ["рост", "масштаб", "growth", "scale", "transformation"],
    "4.3": ["провал", "ошибк", "потер", "failure", "lost", "mistake"],
    "5.1": ["клиент", "проблема", "контекст", "challenge", "customer", "pain"],
    "5.2": ["выбор", "довер", "choice", "trust", "decision"],
    "5.3": ["конфликт", "честн", "признан", "conflict", "honest"],
    "6.1": ["архитектур", "продукт", "решение", "architecture", "product", "solution"],
    "6.2": ["философ", "принцип", "philosophy", "principle"],
    "6.3": ["эволюц", "развит", "evolution", "iteration"],
    "7.1": ["изменен", "трансформ", "change", "vision"],
    "7.2": ["противоречи", "цена", "contradiction", "cost", "trade-off"],
    "7.3": ["наследи", "будущ", "legacy", "future"],
    "8.1": ["исторический", "момент", "historical", "moment"],
    "8.2": ["рынок", "технолог", "market", "technology"],
    "8.3": ["регулир", "политик", "регуляц", "regulation", "policy", "law"],
}

POSITIVE_HINTS = ["зелёный", "green", "сильн", "strong", "уже", "достиг", "успех"]
NEGATIVE_HINTS = ["красный", "red", "риск", "risk", "проблем", "concern", "weakness"]
GREY_HINTS = ["неизвестн", "нет данных", "не упомин", "unknown", "no info", "missing", "серый"]


def _normalize(text: str) -> str:
    return text.lower()


def stub_classify(text: str) -> FactCandidate:
    """Deterministic keyword classifier. Decent baseline; replace with LLM for production."""
    norm = _normalize(text)

    # subsection: pick the one with most matching keywords
    best_sid, best_score = None, 0
    for sid, kws in KEYWORDS_BY_SUBSECTION.items():
        score = sum(1 for kw in kws if kw in norm)
        if score > best_score:
            best_sid, best_score = sid, score

    # flag
    if any(h in norm for h in GREY_HINTS):
        flag = "grey"
    elif any(h in norm for h in NEGATIVE_HINTS):
        flag = "red"
    elif any(h in norm for h in POSITIVE_HINTS):
        flag = "green"
    else:
        flag = "green"  # default optimistic; analyst can correct

    return FactCandidate(
        text=text,
        suggested_subsection_id=best_sid,
        suggested_flag=flag,
        confidence=min(1.0, 0.3 + 0.15 * best_score),
        rationale=f"matched {best_score} keyword(s) for subsection {best_sid}",
    )


# Replace this callable with a real LLM-backed classifier in production.
classify_fact: Callable[[str], FactCandidate] = stub_classify


# ---------- web search ----------

@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


def stub_web_search(query: str, max_hits: int = 5) -> List[SearchHit]:
    """Returns nothing — pure stub. Plug a real search provider here."""
    return []


web_search: Callable[[str, int], List[SearchHit]] = stub_web_search


# ---------- summarization (for cycle outputs) ----------

def stub_summarize(text: str, max_chars: int = 280) -> str:
    """Trivial summarizer: first sentence, capped."""
    s = text.strip().replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    # cut at first sentence boundary if reasonable
    m = re.search(r"^(.{40,}?[\.!?])\s", s)
    if m:
        s = m.group(1)
    if len(s) > max_chars:
        s = s[: max_chars - 1] + "…"
    return s


summarize: Callable[[str, int], str] = stub_summarize
