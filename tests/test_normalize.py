"""Narration normalisation and spoken URLs."""

from __future__ import annotations

import unittest

from book2video.normalize import (
    link_narration,
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

    def test_comparison_symbols_never_reach_tera_as_tags(self) -> None:
        self.assertEqual(
            normalize_for_speech("1 + 1 > два"),
            "1 плюс 1 больше два",
        )
        self.assertEqual(normalize_for_speech("x < y"), "x меньше y")

    def test_number_before_sentence_period_is_expanded(self) -> None:
        # Tera's own number regex deliberately skips digits before a dot.
        self.assertEqual(
            normalize_for_speech("рисунок 6. Далее"),
            "рисунок шесть. Далее",
        )

    def test_whitespace_and_punctuation_are_tidied(self) -> None:
        self.assertEqual(normalize_for_speech("  Привет ,  мир  "), "Привет, мир")


class UrlTests(unittest.TestCase):
    def test_spoken_url_drops_query_and_reads_short_words(self) -> None:
        self.assertEqual(
            spoken_url("https://docs.yandex.ru/abc-def?utm=1#top"),
            "docs точка yandex точка ru, abc def",
        )

    def test_link_narration_is_a_sentence(self) -> None:
        self.assertEqual(
            link_narration("https://example.com/a"),
            "Ссылка: example точка com.",
        )

    def test_google_docs_id_is_not_spoken(self) -> None:
        self.assertEqual(
            spoken_url(
                "https://docs.google.com/document/d/"
                "1AbCdEfGhIjKlMnOpQrStUvWxYz/edit"
            ),
            "docs точка google точка com",
        )

    def test_meaningful_slug_words_are_spoken(self) -> None:
        self.assertEqual(
            spoken_url(
                "https://marketplace.atlassian.com/apps/1220217/"
                "issue-score-for-jira"
            ),
            "marketplace точка atlassian точка com, issue score for jira",
        )

    def test_dates_and_numeric_segments_are_skipped(self) -> None:
        self.assertEqual(
            spoken_url("https://blog.sibirix.ru/2024/01/15/upravlenie-proektami/"),
            "blog точка sibirix точка ru, upravlenie proektami",
        )

    def test_query_and_fragment_are_dropped(self) -> None:
        self.assertEqual(
            spoken_url("https://example.com/page?x=1#y"),
            "example точка com, page",
        )

    def test_domain_only_link_is_readable(self) -> None:
        self.assertEqual(
            spoken_url("https://agilemanifesto.org/"),
            "agilemanifesto точка org",
        )

    def test_long_opaque_ids_are_skipped(self) -> None:
        self.assertEqual(
            spoken_url("https://disk.yandex.ru/i/AbCdEf1234567890XyZ"),
            "disk точка yandex точка ru",
        )


if __name__ == "__main__":
    unittest.main()
