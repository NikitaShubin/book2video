"""Sentence chunking and provider selection for the Tera backend."""

from __future__ import annotations

import unittest
from unittest import mock

from book2video.tts.tera import resolve_provider, split_sentences


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


class ProviderTests(unittest.TestCase):
    def test_auto_uses_cpu_without_visible_devices(self) -> None:
        with mock.patch(
            "book2video.tts.tera.nvidia_devices_visible", return_value=False
        ), mock.patch(
            "book2video.tts.tera.available_providers",
            return_value=("CPUExecutionProvider", "CUDAExecutionProvider"),
        ):
            self.assertEqual(resolve_provider("auto"), "CPUExecutionProvider")

    def test_auto_uses_cuda_when_devices_and_provider_exist(self) -> None:
        with mock.patch(
            "book2video.tts.tera.nvidia_devices_visible", return_value=True
        ), mock.patch(
            "book2video.tts.tera.available_providers",
            return_value=("CPUExecutionProvider", "CUDAExecutionProvider"),
        ):
            self.assertEqual(resolve_provider("auto"), "CUDAExecutionProvider")

    def test_cpu_alias_is_always_cpu(self) -> None:
        with mock.patch(
            "book2video.tts.tera.nvidia_devices_visible", return_value=True
        ), mock.patch(
            "book2video.tts.tera.available_providers",
            return_value=("CPUExecutionProvider", "CUDAExecutionProvider"),
        ):
            self.assertEqual(resolve_provider("cpu"), "CPUExecutionProvider")

    def test_explicit_cuda_requires_a_device(self) -> None:
        with mock.patch(
            "book2video.tts.tera.nvidia_devices_visible", return_value=False
        ), mock.patch(
            "book2video.tts.tera.available_providers",
            return_value=("CPUExecutionProvider", "CUDAExecutionProvider"),
        ):
            with self.assertRaises(RuntimeError):
                resolve_provider("cuda")

    def test_explicit_cuda_requires_a_cuda_build(self) -> None:
        with mock.patch(
            "book2video.tts.tera.nvidia_devices_visible", return_value=True
        ), mock.patch(
            "book2video.tts.tera.available_providers",
            return_value=("CPUExecutionProvider",),
        ):
            with self.assertRaises(RuntimeError):
                resolve_provider("cuda")

    def test_unknown_provider_is_rejected(self) -> None:
        with mock.patch(
            "book2video.tts.tera.available_providers",
            return_value=("CPUExecutionProvider",),
        ):
            with self.assertRaises(ValueError):
                resolve_provider("magic")


if __name__ == "__main__":
    unittest.main()
