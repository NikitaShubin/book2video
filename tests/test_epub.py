"""EPUB parsing, content filtering and chapter selection."""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image

from book2video.epub import load_book, select_chapter

_LONG = (
    "Это достаточно длинный абзац, чтобы документ считался содержательной "
    "главой, а не титульной страницей или рекламной вставкой. "
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
    <dc:title>Тестовая книга</dc:title>
    <dc:creator>Тестовый Автор</dc:creator>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
    <item id="about" href="about.xhtml" media-type="application/xhtml+xml"/>
    <item id="toc" href="toc.xhtml" media-type="application/xhtml+xml"/>
    <item id="img1" href="img1.png" media-type="image/png"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
    <itemref idref="ch2"/>
    <itemref idref="about"/>
    <itemref idref="toc"/>
  </spine>
</package>
"""

_CH1 = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
  <h1>Глава 1. Начало</h1>
  <p>{_LONG}</p>
  <div class="full_img">
    <img src="img1.png" alt=""/>
    <p class="podris">рисунок 1. Схема процесса</p>
  </div>
  <p>Текст после рисунка.</p>
</body></html>
"""

_CH2 = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
  <h1>Глава 2. Продолжение</h1>
  <p>{_LONG}</p>
</body></html>
"""

_ABOUT = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
  <h1>Об авторе</h1>
  <p>{_LONG}</p>
</body></html>
"""

_TOC = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
  <h1>Содержание</h1>
  <p>Глава 1. Начало</p>
  <p>Глава 2. Продолжение</p>
</body></html>
"""


def _png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (120, 80), (40, 80, 160)).save(buffer, "PNG")
    return buffer.getvalue()


def _write_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", _CONTAINER)
        archive.writestr("OEBPS/content.opf", _PACKAGE)
        archive.writestr("OEBPS/ch1.xhtml", _CH1)
        archive.writestr("OEBPS/ch2.xhtml", _CH2)
        archive.writestr("OEBPS/about.xhtml", _ABOUT)
        archive.writestr("OEBPS/toc.xhtml", _TOC)
        archive.writestr("OEBPS/img1.png", _png())


class EpubTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "book.epub"
        _write_epub(self.path)
        self.book = load_book(self.path)
        self.addCleanup(self.book.close)

    def test_metadata_is_read(self) -> None:
        self.assertEqual(self.book.title, "Тестовая книга")
        self.assertEqual(self.book.author, "Тестовый Автор")

    def test_front_and_back_matter_are_dropped(self) -> None:
        titles = [chapter.title for chapter in self.book.chapters]
        self.assertEqual(titles, ["Глава 1. Начало", "Глава 2. Продолжение"])

    def test_image_and_caption_become_blocks(self) -> None:
        chapter = self.book.chapters[0]
        images = [block for block in chapter.blocks if block.kind == "image"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].image, "OEBPS/img1.png")
        self.assertEqual(images[0].caption, "рисунок 1. Схема процесса")

    def test_select_chapter_by_number_and_title(self) -> None:
        self.assertEqual(select_chapter(self.book, "2").title, "Глава 2. Продолжение")
        self.assertEqual(
            select_chapter(self.book, "Продолжение").number,
            2,
        )


if __name__ == "__main__":
    unittest.main()
