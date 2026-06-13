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


def classify_with_reason(text: str, llm_flag: str) -> tuple[str, str]:
    """Return (final_flag, reason), applying safety-net heuristics.

    If grey triggers found → grey (overrides green or red).
    If red triggers found and llm says green → red.
    Otherwise → keep llm_flag.

    ``reason`` is non-empty ONLY when the heuristic CHANGED the flag — it
    carries the first matched trigger keyword so a red/grey fact promoted by
    the keyword classifier never lands without an explanation. When the flag is
    unchanged (LLM already produced it), ``reason`` is "" and the caller keeps
    the LLM-supplied rationale.
    """
    norm = text.lower()

    grey_kw = next((t for t in _GREY_TRIGGERS if t in norm), None)
    if grey_kw is not None:
        if llm_flag != "grey":
            return "grey", f"авто-классификатор: ключевое слово «{grey_kw}» (пробел/неизвестно)"
        return "grey", ""

    if llm_flag == "green":
        red_kw = next((t for t in _RED_TRIGGERS if t in norm), None)
        if red_kw is not None:
            return "red", f"авто-классификатор: ключевое слово «{red_kw}» (риск/споры/негатив)"

    return llm_flag, ""


def apply_heuristics(text: str, llm_flag: str) -> str:
    """Return the final flag, applying safety-net heuristics.

    Thin wrapper over :func:`classify_with_reason` kept for existing callers
    and tests that only need the flag.
    """
    return classify_with_reason(text, llm_flag)[0]
