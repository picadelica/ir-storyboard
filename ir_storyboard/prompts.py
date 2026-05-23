"""Tone presets injected into LLM extractor prompts.

Each preset shapes HOW facts are phrased — same evidence, different register.
Selected per-client via clients.tone_preset (defaults to 'business').
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class TonePreset:
    id: str                  # stored in clients.tone_preset
    label: str               # display name in UI
    description: str         # one-line summary for the UI
    instruction: str         # injected near the top of the extractor system prompt
    sample: str              # short example of the resulting fact phrasing


TONE_PRESETS: List[TonePreset] = [
    TonePreset(
        id="academic",
        label="Academic",
        description="Сдержанная нейтральная формулировка, без оценок и эпитетов.",
        instruction=(
            "Phrase each fact in a sober, academic register: neutral verbs, "
            "no superlatives, no rhetorical questions, no business jargon. "
            "Prefer passive or impersonal constructions where natural. "
            "Cite numbers exactly as stated; do not round or qualify them."
        ),
        sample="Компания зарегистрировала юридическое лицо в Делавэре в марте 2022 года.",
    ),
    TonePreset(
        id="business",
        label="Business",
        description="Деловой регистр IR-материалов: конкретно, по делу, без воды.",
        instruction=(
            "Phrase each fact in a business register suitable for IR briefings: "
            "concrete nouns, active voice, no marketing fluff, no adjectives that "
            "imply judgement (\"impressive\", \"strong\"). Keep each fact to one "
            "claim. Use the numbers and dates as stated in the source."
        ),
        sample="В Q2 2022 компания закрыла seed-раунд на $3.4M, лид-инвестор — Sequoia.",
    ),
    TonePreset(
        id="narrative",
        label="Narrative",
        description="Сторителлинговый регистр для нарратива фаундера.",
        instruction=(
            "Phrase each fact in a narrative register that fits a founder story: "
            "first-person/active subject (\"the founder\", \"the team\"), concrete "
            "scene details where the source provides them, but no invented detail. "
            "Avoid corporate boilerplate. Stay strictly within what the source says."
        ),
        sample="Фаундер запустил первый прототип на кухне в Тель-Авиве, оплачивая разработку из своих сбережений.",
    ),
    TonePreset(
        id="punchy",
        label="Punchy / Journalistic",
        description="Короткие резкие формулировки в стиле инвестиционных обзоров.",
        instruction=(
            "Phrase each fact as a short, punchy headline-style sentence — the "
            "kind a financial journalist would write. Lead with the verb or the "
            "number. Keep under 25 words. No hedging, no \"the company believes\". "
            "Stick strictly to evidence in the source."
        ),
        sample="$3.4M seed закрыт за 6 недель — Sequoia взяла лид без term sheet от других фондов.",
    ),
]

_PRESET_BY_ID: Dict[str, TonePreset] = {p.id: p for p in TONE_PRESETS}

DEFAULT_TONE_PRESET = "business"


def get_tone_preset(preset_id: str) -> TonePreset:
    """Return the preset by id, falling back to the default if unknown."""
    return _PRESET_BY_ID.get(preset_id) or _PRESET_BY_ID[DEFAULT_TONE_PRESET]


def get_tone_instruction(preset_id: str) -> str:
    """Convenience: return just the instruction string for prompt injection."""
    return get_tone_preset(preset_id).instruction
