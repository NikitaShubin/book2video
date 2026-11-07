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

import book2video.render as render_module
from book2video.build import build
from book2video.links import LinkPreview

_LINK = "https://example.com/report"

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
  <p>Подробности: <a href="{_LINK}">Итоги встречи</a>.</p>
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
                link_resolver=lambda links: {},
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

    def test_many_frames_are_rendered_in_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub = root / "book.epub"
            out = root / "book.mp4"
            work = root / "work"
            _write_epub(epub)

            original = render_module.MAX_RENDER_INPUTS
            render_module.MAX_RENDER_INPUTS = 1
            try:
                result = build(
                    epub,
                    out,
                    work_dir=work,
                    speed=1.0,
                    backend=FakeBackend(),
                    link_resolver=lambda links: {},
                    log=lambda *_: None,
                )
            finally:
                render_module.MAX_RENDER_INPUTS = original

            self.assertEqual(result, out)
            self.assertTrue(out.exists())
            self.assertFalse((work / "render-parts").exists())

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

    def test_injected_content_preview_reaches_the_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub = root / "book.epub"
            out = root / "book.mp4"
            work = root / "work"
            _write_epub(epub)
            preview_image = root / "preview.png"
            Image.new("RGB", (800, 600), (245, 245, 245)).save(preview_image, "PNG")
            preview = LinkPreview(
                url=_LINK,
                kind="document",
                title="Итоги встречи",
                page_count=3,
                full=False,
                image_path=preview_image,
            )

            def resolver(links):
                self.assertIn(_LINK, links)
                return {_LINK: preview}

            build(
                epub,
                out,
                work_dir=work,
                speed=1.0,
                frame_hold=2.0,
                backend=FakeBackend(),
                link_resolver=resolver,
                log=lambda *_: None,
            )

            data = json.loads((work / "timeline.json").read_text(encoding="utf-8"))
            frames = data[0]["frames"]
            content = next(frame for frame in frames if frame["kind"] == "content")
            self.assertEqual(content["preview"]["kind"], "document")
            self.assertFalse(content["preview"]["full"])
            self.assertTrue(Path(content["file"]).exists())
            self.assertTrue(
                any(segment["kind"] == "annotation" for segment in data[0]["segments"])
            )
            annotation = next(
                segment
                for segment in data[0]["segments"]
                if segment["kind"] == "annotation"
            )
            self.assertEqual(annotation["voice"], "ru_f2")
            self.assertNotIn("whisper", annotation["voice"])

    def test_explicit_whisper_sidebar_voice_is_obeyed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub = root / "book.epub"
            out = root / "book.mp4"
            work = root / "work"
            _write_epub(epub)
            preview_image = root / "preview.png"
            Image.new("RGB", (800, 600), (245, 245, 245)).save(preview_image, "PNG")
            preview = LinkPreview(
                url=_LINK,
                kind="document",
                title="Итоги встречи",
                page_count=3,
                full=False,
                image_path=preview_image,
            )

            build(
                epub,
                out,
                work_dir=work,
                speed=1.0,
                frame_hold=2.0,
                sidebar_voice="eng_m2_whisper",
                backend=FakeBackend(),
                link_resolver=lambda links: {_LINK: preview},
                log=lambda *_: None,
            )

            data = json.loads((work / "timeline.json").read_text(encoding="utf-8"))
            annotation = next(
                segment
                for segment in data[0]["segments"]
                if segment["kind"] == "annotation"
            )
            self.assertEqual(annotation["voice"], "eng_m2_whisper")


if __name__ == "__main__":
    unittest.main()
