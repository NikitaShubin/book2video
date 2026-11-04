"""Sentence chunking for the Tera backend."""

from __future__ import annotations

import unittest

from book2video.tts.tera import split_sentences


class SplitSentencesTests(unittest.TestCase):
    def test_short_sentences_are_grouped(self) -> None:
        chunks = split_sentences("Первое. Второе. Третье.", max_chars=350)
        self.assertEqual(chunks, ["Первое. Второе. Третье."])

    def test_long_text_is_split_below_the_limit(self) -> None:
        text = " ".join(["Очень длинное предложение с продолжением."] * 20)
        chunks = split_sentences(text, max_chars=120)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 120 for chunk in chunks))

    def test_very_long_sentence_falls_back_to_clauses(self) -> None:
        sentence = "Первая часть, " + "слово " * 80 + "конец."
        chunks = split_sentences(sentence, max_chars=100)
        self.assertTrue(all(len(chunk) <= 100 for chunk in chunks))
        self.assertTrue(chunks)

    def test_empty_text_produces_no_chunks(self) -> None:
        self.assertEqual(split_sentences("   "), [])


if __name__ == "__main__":
    unittest.main()
