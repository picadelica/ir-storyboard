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

def classify_with_reason(text: str, llm_flag: str) -> tuple[str, str]:
    """Return (final_flag, reason), applying the safety-net gap heuristic.

    If grey triggers found → grey (overrides anything — it's an explicit gap).
    Otherwise → keep llm_flag unchanged.

    Авто-красный убран как слишком грубый: негатив-но-известный факт остаётся тем,
    чем его назвал LLM (обычно green). Красный остаётся РУЧНЫМ флагом аналитика.

    ``reason`` is non-empty ONLY when the heuristic CHANGED the flag (a grey
    promotion), carrying the matched keyword. Unchanged flag → "" (caller keeps
    the LLM rationale).
    """
    norm = text.lower()

    grey_kw = next((t for t in _GREY_TRIGGERS if t in norm), None)
    if grey_kw is not None:
        if llm_flag != "grey":
            return "grey", f"авто-классификатор: ключевое слово «{grey_kw}» (пробел/неизвестно)"
        return "grey", ""

    return llm_flag, ""


def apply_heuristics(text: str, llm_flag: str) -> str:
    """Return the final flag, applying safety-net heuristics.

    Thin wrapper over :func:`classify_with_reason` kept for existing callers
    and tests that only need the flag.
    """
    return classify_with_reason(text, llm_flag)[0]
