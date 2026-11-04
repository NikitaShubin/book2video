"""Narration normalisation and link/QR decisions."""

from __future__ import annotations

import unittest

from book2video.normalize import (
    is_domain_anchor,
    link_narration,
    needs_qr,
    normalize_for_speech,
    spoken_url,
)


class NormalizeTests(unittest.TestCase):
    def test_year_takes_prepositional_case(self) -> None:
        result = normalize_for_speech("в 2024 году")
        self.assertNotIn("2024", result)
        self.assertTrue(result.endswith("году"))
        self.assertIn("двадцать", result)

    def test_percent_agreement(self) -> None:
        self.assertEqual(normalize_for_speech("21 %"), "21 процент")
        self.assertEqual(normalize_for_speech("3 %"), "3 процента")
        self.assertEqual(normalize_for_speech("5 %"), "5 процентов")
        self.assertEqual(normalize_for_speech("15,5 %"), "15,5 процента")

    def test_units_are_expanded(self) -> None:
        self.assertEqual(normalize_for_speech("2 млн"), "2 миллиона")
        self.assertEqual(normalize_for_speech("5 тыс."), "5 тысяч")
        self.assertEqual(normalize_for_speech("3 км"), "3 километра")

    def test_dashes_and_symbols(self) -> None:
        self.assertEqual(normalize_for_speech("— Привет – мир"), "Привет - мир")
        self.assertEqual(normalize_for_speech("A+B"), "A плюс B")
        self.assertEqual(normalize_for_speech("№ 4"), "номер 4")

    def test_number_before_sentence_period_is_expanded(self) -> None:
        # Tera's own number regex deliberately skips digits before a dot.
        self.assertEqual(
            normalize_for_speech("рисунок 6. Далее"),
            "рисунок шесть. Далее",
        )

    def test_whitespace_and_punctuation_are_tidied(self) -> None:
        self.assertEqual(normalize_for_speech("  Привет ,  мир  "), "Привет, мир")


class UrlTests(unittest.TestCase):
    def test_spoken_url_drops_query(self) -> None:
        self.assertEqual(
            spoken_url("https://docs.yandex.ru/abc-def?utm=1#top"),
            "docs точка yandex точка ru, abc дефис def",
        )

    def test_link_narration_is_a_sentence(self) -> None:
        self.assertEqual(
            link_narration("https://example.com/a"),
            "Ссылка: example точка com, a.",
        )

    def test_domain_anchor_is_not_read_as_a_link(self) -> None:
        self.assertTrue(is_domain_anchor("Mail.ru"))
        self.assertFalse(needs_qr("Mail.ru", "https://mail.ru"))

    def test_deictic_anchor_gets_a_qr(self) -> None:
        self.assertTrue(needs_qr("здесь", "https://example.com/a"))

    def test_short_named_link_does_not_get_a_qr(self) -> None:
        self.assertFalse(needs_qr("статья", "https://example.com/a"))
        self.assertTrue(needs_qr("статья", "https://example.com/" + "a" * 90))


if __name__ == "__main__":
    unittest.main()
