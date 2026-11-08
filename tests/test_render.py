"""Resumable render parts: reuse only complete, matching chunks."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import book2video.render as render_module


class PartResumeTests(unittest.TestCase):
    def _write_part(self, path: Path, duration: float) -> None:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s=64x64:r=30:d={duration}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
        )

    def test_finished_part_matches_its_expected_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            part = Path(tmp) / "part_000.mp4"
            self._write_part(part, 1.0)
            self.assertTrue(render_module._part_is_complete(part, 1.0))
            self.assertFalse(render_module._part_is_complete(part, 5.0))

    def test_truncated_or_missing_part_is_not_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            part = Path(tmp) / "part_000.mp4"
            self.assertFalse(render_module._part_is_complete(part, 1.0))
            part.write_bytes(b"not an mp4")
            self.assertFalse(render_module._part_is_complete(part, 1.0))

    def test_signature_covers_frames_and_encoder_settings(self) -> None:
        chunk = [("frame.png", 0.0, 1.0)]
        signature = render_module._chunk_signature(chunk, "libx264", 20, "medium")
        self.assertEqual(
            signature,
            render_module._chunk_signature(chunk, "libx264", 20, "medium"),
        )
        self.assertNotEqual(
            signature,
            render_module._chunk_signature(chunk, "h264_nvenc", 20, "medium"),
        )
        self.assertNotEqual(
            signature,
            render_module._chunk_signature(chunk, "libx264", 21, "medium"),
        )
        self.assertNotEqual(
            signature,
            render_module._chunk_signature(
                [("frame.png", 0.0, 2.0)], "libx264", 20, "medium"
            ),
        )


if __name__ == "__main__":
    unittest.main()
