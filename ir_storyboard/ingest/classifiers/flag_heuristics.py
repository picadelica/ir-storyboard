"""Post-processing heuristics to validate/correct LLM-proposed flags.

Rule: if heuristic says "more cautious" (grey/red) than LLM said → take heuristic.
If heuristic is neutral → trust LLM.
"""
from __future__ import annotations

_GREY_TRIGGERS = [
    "не покрыт", "не известен", "not covered", "unknown",
    "no information", "no data", "no details", "missing",
    "not disclosed", "не раскрыт", "отсутствует", "не упомяну",
    "нет данных", "нет информации", "серое поле", "open research",
    "не найден", "not found", "unavailable", "n/a",
    "not mentioned", "не указан", "не задокументирован",
]

_RED_TRIGGERS = [
    "отозван", "провал", "убыток", "scandal", "lawsuit", "fraud",
    "sanction", "losing", "down", "failed", "failure",
    "bankruptcy", "bankrupt", "collapsed", "collapse",
    "criminal", "arrested", "indicted", "accused",
    "controversy", "controversial", "риск провала", "скандал",
    "иск", "претензии", "регуляторное давление", "enforcement",
]


def apply_heuristics(text: str, llm_flag: str) -> str:
    """Return the final flag, applying safety-net heuristics.

    If grey triggers found → grey (overrides green or red).
    If red triggers found and llm says green → red.
    Otherwise → keep llm_flag.
    """
    norm = text.lower()

    if any(t in norm for t in _GREY_TRIGGERS):
        return "grey"

    if llm_flag == "green" and any(t in norm for t in _RED_TRIGGERS):
        return "red"

    return llm_flag
