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
# ru_f1 is the model authors' recommended female voice, but its median F0 is
# around 278 Hz and it reads as shrill next to ru_m5.  ru_f2 is native Russian
# and about 25% lower, so it is the default sidebar/annotation voice.
DEFAULT_SIDEBAR_VOICE = "ru_f2"

# Preference order for the implicit opposite-gender voice.  Native Russian
# first, then non-whisper English voices that read Russian cross-lingually.
_OPPOSITE_PREFERENCE = {
    "f": ("ru_f2", "ru_f1", "eng_f3", "eng_f5"),
    "m": ("ru_m5", "ru_m1", "eng_m3", "eng_m4"),
}


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
    for candidate in _OPPOSITE_PREFERENCE[want]:
        if candidate in VOICE_IDS:
            return candidate
    return DEFAULT_SIDEBAR_VOICE
