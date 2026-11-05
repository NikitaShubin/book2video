"""ffmpeg atempo is the only time-stretch path."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import numpy as np
import soundfile as sf

from book2video.speed import _atempo_filter, _part_path, apply_speed


def _write_tone(path: Path, seconds: float = 1.0) -> None:
    rate = 44_100
    time = np.arange(int(rate * seconds), dtype=np.float32) / rate
    tone = 0.3 * np.sin(2 * np.pi * 440.0 * time)
    sf.write(path, tone, rate, subtype="PCM_16")


class AtempoFilterTests(unittest.TestCase):
    def test_normal_speed_is_a_single_pass(self) -> None:
        self.assertEqual(_atempo_filter(1.2), "atempo=1.200000")
        self.assertEqual(_atempo_filter(3.6), "atempo=3.600000")

    def test_below_half_speed_is_chained(self) -> None:
        self.assertEqual(_atempo_filter(0.3), "atempo=0.5,atempo=0.600000")

    def test_invalid_speeds_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _atempo_filter(0)
        with self.assertRaises(ValueError):
            _atempo_filter(101)


class ApplySpeedTests(unittest.TestCase):
    def test_output_is_float32_at_the_expected_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.wav"
            dst = Path(tmp) / "dst.wav"
            _write_tone(src, 1.2)
            apply_speed(src, dst, 1.2)

            info = sf.info(dst)
            self.assertEqual(info.samplerate, 44_100)
            self.assertEqual(info.channels, 1)
            self.assertEqual(info.subtype, "FLOAT")
            self.assertAlmostEqual(info.duration, 1.0, delta=0.05)

    def test_identity_does_not_require_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.wav"
            dst = Path(tmp) / "dst.wav"
            _write_tone(src, 0.2)
            apply_speed(src, dst, 1.0)
            self.assertTrue(dst.exists())
            self.assertAlmostEqual(sf.info(dst).duration, 0.2, delta=0.001)
            self.assertFalse(_part_path(dst).exists())

    def test_successful_encode_leaves_no_part_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.wav"
            dst = Path(tmp) / "dst.wav"
            _write_tone(src, 0.2)

            def fake_run(command, **kwargs):
                Path(command[-1]).write_bytes(b"encoded")
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch("book2video.speed.subprocess.run", fake_run):
                apply_speed(src, dst, 2.0)

            self.assertEqual(dst.read_bytes(), b"encoded")
            self.assertFalse(_part_path(dst).exists())

    def test_failed_encode_removes_the_part_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.wav"
            dst = Path(tmp) / "dst.wav"
            _write_tone(src, 0.2)

            def fake_run(command, **kwargs):
                Path(command[-1]).write_bytes(b"truncated")
                return subprocess.CompletedProcess(command, 1, "", "boom")

            with mock.patch("book2video.speed.subprocess.run", fake_run):
                with self.assertRaises(RuntimeError):
                    apply_speed(src, dst, 2.0)

            self.assertFalse(dst.exists())
            self.assertFalse(_part_path(dst).exists())


if __name__ == "__main__":
    unittest.main()
