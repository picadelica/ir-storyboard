"""Section heading → subsection_id mapper.

Uses a canonical synonym dict. Case-insensitive substring match.
If no match → returns None (fact will be skipped with a warning).
"""
from __future__ import annotations

SECTION_HINTS: dict[str, list[str]] = {
    "2.1": [
        "history", "history & timeline", "история", "хронология",
        "path to expertise", "background", "journalism", "journalism background",
        "журналистика", "карьерный путь", "история и хронология",
        "история основателей", "основатели — история",
    ],
    "2.2": [
        "founder role", "motivation", "роль основателя", "мотивация",
        "why they built", "founder motivation",
    ],
    "2.3": [
        "founders", "founder", "ownership", "основатели", "основатели и",
        "co-founders", "team", "команда", "founders & ownership",
        "основатели и структура", "founder structure",
    ],
    "3.3": [
        "investments", "investors", "funding", "raise", "round",
        "инвесторы", "инвестиции", "финансирование",
        "investments & financing", "инвестиции и финансирование",
    ],
    "4.1": [
        "expertise", "diversity", "team expertise", "экспертиза",
        "team composition",
    ],
    "4.2": [
        "growth", "scale", "transformation", "рост", "масштаб",
    ],
    "4.3": [
        "failure", "failure memory", "провалы", "ошибки",
    ],
    "5.1": [
        "clients", "customer", "pain", "challenge", "клиенты",
        "client stories", "кейсы",
    ],
    "5.2": [
        "trust", "choice", "moment of choice", "доверие", "выбор",
    ],
    "5.3": [
        "conflict", "honesty", "конфликт", "честность",
    ],
    "6.1": [
        "technology", "architecture", "архитектура", "технология",
        "consensus", "protocol", "what is", "обзор", "overview",
        "технология и продукт", "technology & product",
    ],
    "6.2": [
        "philosophy", "tokenomics", "governance", "principles",
        "философия", "управление", "product philosophy",
        "philosophy of product",
    ],
    "6.3": [
        "roadmap", "plans", "future", "evolution", "планы",
        "дорожная карта", "planы и дорожная карта",
        "plans & roadmap", "планы и",
    ],
    "7.1": [
        "mission", "vision", "social impact", "миссия", "видение",
        "social", "social impact vision",
    ],
    "7.2": [
        "risks", "criticism", "cost", "contradictions", "критика",
        "риски", "contradictions & cost",
    ],
    "7.3": [
        "legacy", "наследие", "будущее",
    ],
    "8.1": [
        "historical moment", "macro", "context", "контекст",
        "исторический момент",
    ],
    "8.2": [
        "market", "competitive landscape", "competitors", "конкуренты",
        "конкурентная среда", "market & technology",
        "конкурентная среда и рынок", "competitive environment",
    ],
    "8.3": [
        "regulation", "policy", "legal", "compliance",
        "регулирование", "политика", "policy & regulation",
        "регуляторный", "regulatory", "regulatory & social",
        "регуляторный и социальный", "social context",
        "regulatory and social", "регуляторный контекст",
    ],
}

# Sections that should always be skipped (meta / editorial)
SKIP_SECTION_HINTS: list[str] = [
    "выводы", "conclusions", "заключение", "conclusion",
    "summary", "итог", "implications", "what this means",
    "recommendations", "рекомендации",
    "open questions", "вопросы для интервью", "interview questions",
]


def suggest_subsection(heading: str) -> str | None:
    """Return the best-matching subsection_id for a section heading, or None.

    Case-insensitive substring match; the longest matching hint wins.
    Returns None for meta/editorial sections (Conclusions, Open Questions, …).
    """
    norm = heading.lower().strip()

    # Check skip list first
    if any(skip in norm for skip in SKIP_SECTION_HINTS):
        return None

    # Match against synonym lists. The most specific (longest) matching hint
    # wins — otherwise a generic hint like "контекст" (8.1) would shadow a
    # specific one like "регуляторный и социальный" (8.3) just by dict order.
    best_sid: str | None = None
    best_len = 0
    for sid, hints in SECTION_HINTS.items():
        for hint in hints:
            if hint in norm and len(hint) > best_len:
                best_sid = sid
                best_len = len(hint)

    return best_sid
