"""TeraTTSv2 voice catalogue.

The service exposes every voice the model ships with. Four are native Russian;
six are English voices that read Russian cross-lingually and are useful when a
different timbre is wanted for sidebars or quotations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Voice:
    id: str
    gender: str
    language: str
    description: str


TERA_VOICES: tuple[Voice, ...] = (
    Voice("ru_f1", "f", "ru", "Русский женский, рекомендуется авторами модели"),
    Voice("ru_f2", "f", "ru", "Русский женский"),
    Voice("ru_m1", "m", "ru", "Русский мужской"),
    Voice("ru_m5", "m", "ru", "Русский мужской, рекомендуется авторами модели"),
    Voice("eng_f3", "f", "en", "Английский женский, читает русский кросс-языково"),
    Voice("eng_f4_whisper", "f", "en", "Английский шёпот, читает русский кросс-языково"),
    Voice("eng_f5", "f", "en", "Английский женский, читает русский кросс-языково"),
    Voice("eng_m2_whisper", "m", "en", "Английский шёпот, читает русский кросс-языково"),
    Voice("eng_m3", "m", "en", "Английский мужской, читает русский кросс-языково"),
    Voice("eng_m4", "m", "en", "Английский мужской, читает русский кросс-языково"),
)

VOICE_IDS = tuple(v.id for v in TERA_VOICES)

DEFAULT_MAIN_VOICE = "ru_m5"
DEFAULT_SIDEBAR_VOICE = "ru_f1"


def get_voice(voice_id: str) -> Voice:
    for voice in TERA_VOICES:
        if voice.id == voice_id:
            return voice
    raise KeyError(
        f"Unknown Tera voice {voice_id!r}. Available: {', '.join(VOICE_IDS)}"
    )


def opposite_gender(voice_id: str) -> str:
    """Return a sensible default sidebar voice of the opposite gender."""
    voice = get_voice(voice_id)
    want = "f" if voice.gender == "m" else "m"
    # Prefer native Russian voices, then English cross-lingual ones.
    for candidate in TERA_VOICES:
        if candidate.gender == want and candidate.language == "ru":
            return candidate.id
    for candidate in TERA_VOICES:
        if candidate.gender == want:
            return candidate.id
    return DEFAULT_SIDEBAR_VOICE
