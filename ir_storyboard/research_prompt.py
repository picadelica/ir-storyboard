"""Build a deep-research prompt for an external LLM (ChatGPT/Claude/Perplexity/
Gemini) from the client's identity, mirroring LLM_REPORT_PROMPT_TEMPLATES.md.

The analyst copies the generated prompt into their agent, runs deep research, and
pastes the text answer back into the LLM-report ingest — the same parser that
handles uploaded .docx/.pdf reports then extracts facts.
"""
from __future__ import annotations

from .models import LAYERS


def _intro() -> str:
    """§0 — universal preamble: the matrix layers + the L1–L3-not-from-web rule.
    Built from the layer model so it stays in sync with the matrix."""
    lines = ["Ты помогаешь подготовить материал для нарративной IR-матрицы (ir-storyboard).",
             "Матрица — 8 концентрических слоёв, по 3 подсекции в каждом:", ""]
    for L in LAYERS:
        subs = " / ".join(f"{s.id} {s.name}" for s in L.subsections)
        lines.append(f"  L{L.id} {L.name} ({subs})")
    lines += [
        "",
        "ВАЖНО: ты НЕ заполняешь L1–L3 из веб-источников — их закрывают только живые",
        "интервью. Если факт явно тянет в L1–L3 (детство, ценности, страхи, мотивация",
        "фаундера) — выноси его в раздел «Open Questions for Interview», не сворачивай",
        "его веб-цитатой.",
    ]
    return "\n".join(lines)


# per-agent body; {subject} is filled with the client subject line
_BODIES = {
    "chatgpt": """ЗАДАЧА. Подготовь deep-research отчёт по {subject}. Покрой секции — РОВНО в этом порядке и с этими заголовками первого уровня:

  Обзор
  История и хронология
  Основатели и структура собственности
  Инвестиции и финансирование
  Технология и продукт
  Планы и дорожная карта
  Конкурентная среда
  Регуляторный и социальный контекст
  Open Questions for Interview

Правила цитирования:
  • после каждого утверждения ставь [N] — номерную сноску
  • один [N] = один URL; нужно несколько источников — пиши [3][7]
  • в конце — раздел «Источники»: для каждого [N] укажи `[N] <Title> — <Publisher> — <full URL>`
  • не дублируй URL под разными [N]; давай только реальные полные URL (без t.co/bit.ly)

Не пиши секции «Выводы»/«Мнение»/«Что это значит». Без превосходных степеней без цифры. Не сочиняй цитаты — нет прямой речи, давай парафраз. Личностные темы фаундера — только в Open Questions.

Длина: 1500–3500 слов + список источников; Open Questions — 5–10 bullet-вопросов.""",

    "claude": """Подготовь исследование по {subject}, используя web search. Структура — РОВНО эти секции по порядку:

  Overview
  History & Timeline
  Founders & Ownership Structure
  Investments & Financing
  Technology & Product
  Roadmap
  Competitive Landscape
  Regulatory & Social Context
  Open Questions for Interview

Формат цитат — ОБЯЗАТЕЛЬНО `[N]` (квадратные скобки, число): после каждого утверждения `[N]`; в конце раздел «Sources» вида `[N] Title — Publisher — https://full.url`. НЕ используй (Source 1), не пиши URL inline, не делай footnote-ы в скобках.

Не пиши «Conclusions»/«What this means» — только факты с источниками. Нельзя подтвердить веб-источником — выноси в Open Questions. Длина: 1500–3500 слов.""",

    "perplexity": """Создай Perplexity Page по теме {subject}. Секции строго по порядку (H2):

  Overview
  History & Timeline
  Founders & Ownership
  Investments & Financing
  Technology & Product
  Roadmap
  Competitive Landscape
  Regulatory & Social Context
  Open Questions for Interview

В каждом абзаце — минимум одна сноска. В «Sources» — все ссылки с заголовком и URL. Без «Conclusions»/«Recommendations». При экспорте в Markdown оставь номерной формат `[N]`, не footnote-style. Длина: 2–4 страницы.""",

    "gemini": """Запусти Deep Research по теме {subject}. Структура:

  Overview
  History & Timeline
  Founders
  Investments & Financing
  Technology & Product
  Roadmap
  Competitive Landscape
  Regulatory & Social Context
  Open Questions for Interview

Каждое утверждение — со сноской; в конце раздел «Sources» с пронумерованным списком URL. Без «Conclusions»/«Implications» — только атомарные факты. Факт только из подкаста/интервью — указывай URL подкаста (audio-источник). Длина: 1500–3500 слов.""",
}

AGENTS = list(_BODIES.keys())


def _subject(name: str, founder: str = "", sector: str = "") -> str:
    parts = [name.strip() or "компания"]
    if founder.strip():
        parts.append(f"фаундер {founder.strip()}")
    if sector.strip():
        parts.append(f"сектор {sector.strip()}")
    return ", ".join(parts)


def build_prompt(*, name: str, founder: str = "", sector: str = "", agent: str = "chatgpt") -> str:
    body = _BODIES.get(agent, _BODIES["chatgpt"]).format(subject=_subject(name, founder, sector))
    return f"{_intro()}\n\n---\n\n{body}\n"
