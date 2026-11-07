"""Voice catalogue and default selection."""

from __future__ import annotations

import unittest

from book2video.voices import (
    DEFAULT_MAIN_VOICE,
    DEFAULT_SIDEBAR_VOICE,
    TERA_VOICES,
    VOICE_IDS,
    get_voice,
    opposite_gender,
)


class VoiceTests(unittest.TestCase):
    def test_catalogue_has_unique_ids(self) -> None:
        self.assertEqual(len(VOICE_IDS), len(set(VOICE_IDS)))
        self.assertEqual(len(TERA_VOICES), 10)

    def test_defaults_exist(self) -> None:
        self.assertEqual(get_voice(DEFAULT_MAIN_VOICE).language, "ru")
        self.assertEqual(get_voice(DEFAULT_SIDEBAR_VOICE).language, "ru")

    def test_default_sidebar_voice_is_never_whisper(self) -> None:
        for voice_id in VOICE_IDS:
            self.assertNotIn("whisper", opposite_gender(voice_id))

    def test_opposite_gender_prefers_native_russian(self) -> None:
        self.assertEqual(opposite_gender("ru_m5"), "ru_f2")
        self.assertEqual(opposite_gender("ru_f2"), "ru_m5")

    def test_default_sidebar_is_the_lower_female_voice(self) -> None:
        self.assertEqual(DEFAULT_SIDEBAR_VOICE, "ru_f2")
        self.assertEqual(opposite_gender(DEFAULT_MAIN_VOICE), "ru_f2")

    def test_unknown_voice_is_rejected(self) -> None:
        with self.assertRaises(KeyError):
            get_voice("not_a_voice")


if __name__ == "__main__":
    unittest.main()
