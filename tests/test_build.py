"""End-to-end build with a fake TTS backend.

The fake backend sits at the same seam as Tera: it writes a WAV for each
Segment.  This exercises parsing, planning, timing, frame preparation, ffmpeg
rendering and metadata without downloading or running the model.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image

from book2video.build import build

_LONG = (
    "Это достаточно длинный абзац, чтобы документ считался содержательной "
    "главой, а не титульной страницей. "
) * 4

_CONTAINER = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

_PACKAGE = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Мини-книга</dc:title>
    <dc:creator>Тестовый Автор</dc:creator>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="img1" href="img1.png" media-type="image/png"/>
  </manifest>
  <spine><itemref idref="ch1"/></spine>
</package>
"""

_CH1 = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
  <h1>Глава 1. Начало</h1>
  <p>{_LONG}</p>
  <div class="full_img">
    <img src="img1.png" alt=""/>
    <p class="podris">рисунок 1. Схема</p>
  </div>
  <p>Короткий финальный абзац.</p>
</body></html>
"""


class FakeBackend:
    """Minimal synthesis adapter: one short tone per Segment."""

    def __init__(self) -> None:
        self.calls = 0

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        self.calls += 1
        rate = 44_100
        seconds = 0.45
        time = np.arange(int(rate * seconds), dtype=np.float32) / rate
        tone = 0.2 * np.sin(2 * np.pi * 220.0 * time)
        sf.write(out_path, tone, rate, subtype="PCM_16")
        return Path(out_path)


def _write_epub(path: Path) -> None:
    buffer = BytesIO()
    Image.new("RGB", (160, 100), (30, 90, 160)).save(buffer, "PNG")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", _CONTAINER)
        archive.writestr("OEBPS/content.opf", _PACKAGE)
        archive.writestr("OEBPS/ch1.xhtml", _CH1)
        archive.writestr("OEBPS/img1.png", buffer.getvalue())


class BuildIntegrationTests(unittest.TestCase):
    def test_fake_backend_renders_a_synced_mp4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub = root / "book.epub"
            out = root / "book.mp4"
            work = root / "work"
            _write_epub(epub)

            backend = FakeBackend()
            result = build(
                epub,
                out,
                work_dir=work,
                speed=1.0,
                backend=backend,
                log=lambda *_: None,
            )

            self.assertEqual(result, out)
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 10_000)
            self.assertGreater(backend.calls, 0)

            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-show_entries",
                    "stream=codec_type,codec_name",
                    "-show_chapters",
                    "-of",
                    "json",
                    str(out),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            data = json.loads(probe.stdout)
            self.assertGreater(float(data["format"]["duration"]), 2.0)
            codecs = {stream["codec_type"]: stream["codec_name"] for stream in data["streams"]}
            self.assertEqual(codecs["video"], "h264")
            self.assertEqual(codecs["audio"], "aac")
            self.assertEqual(data["chapters"][0]["tags"]["title"], "Глава 1. Начало")


if __name__ == "__main__":
    unittest.main()
