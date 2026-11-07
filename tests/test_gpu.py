"""Hardware selection without requiring a GPU in the test environment."""

from __future__ import annotations

import unittest
from unittest import mock

from book2video.gpu import (
    LIBX264,
    NVENC,
    encoder_args,
    nvidia_devices_visible,
    nvenc_available,
    resolve_encoder,
)


class EncoderTests(unittest.TestCase):
    def test_aliases_resolve_to_the_expected_encoder(self) -> None:
        with mock.patch("book2video.gpu.nvenc_available", return_value=True):
            self.assertEqual(resolve_encoder("cpu"), LIBX264)
            self.assertEqual(resolve_encoder("libx264"), LIBX264)
            self.assertEqual(resolve_encoder("nvenc"), NVENC)
            self.assertEqual(resolve_encoder("h264_nvenc"), NVENC)

    def test_auto_prefers_nvenc_when_the_probe_succeeds(self) -> None:
        with mock.patch("book2video.gpu.nvenc_available", return_value=True):
            self.assertEqual(resolve_encoder("auto"), NVENC)

    def test_auto_falls_back_to_x264_without_a_gpu(self) -> None:
        with mock.patch("book2video.gpu.nvenc_available", return_value=False):
            self.assertEqual(resolve_encoder("auto"), LIBX264)

    def test_explicit_nvenc_fails_without_a_usable_device(self) -> None:
        with mock.patch("book2video.gpu.nvenc_available", return_value=False):
            with self.assertRaises(RuntimeError):
                resolve_encoder("h264_nvenc")

    def test_unknown_encoder_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_encoder("hevc_magic")

    def test_x264_uses_crf_and_nvenc_uses_cq(self) -> None:
        x264 = encoder_args(LIBX264, 20, "medium")
        nvenc = encoder_args(NVENC, 20, "medium")
        self.assertIn("-crf", x264)
        self.assertIn("20", x264)
        self.assertIn("-cq", nvenc)
        self.assertIn("20", nvenc)
        self.assertIn("p5", nvenc)

    def test_device_detection_does_not_crash(self) -> None:
        self.assertIsInstance(nvidia_devices_visible(), bool)

    def test_probe_is_safe_without_a_gpu(self) -> None:
        self.assertIsInstance(nvenc_available(), bool)


if __name__ == "__main__":
    unittest.main()
