"""Link classification, PDF rasterisation and the per-book preview cache."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from PIL import Image

from book2video.epub import Block, Chapter, Link
from book2video.links import (
    LinkPreview,
    PreviewError,
    _Fetcher,
    collect_links,
    compact_url,
    preferred_title,
    preview_from_image,
    preview_from_pdf,
    resolve_links,
    yandex_docs_target,
)


def _pdf(pages: int) -> bytes:
    images = [Image.new("RGB", (600, 800), (255, 255, 255)) for _ in range(pages)]
    buffer = BytesIO()
    images[0].save(
        buffer,
        "PDF",
        save_all=True,
        append_images=images[1:],
        resolution=150,
    )
    return buffer.getvalue()


def _preview(kind: str, pages: int, *, full: bool, title: str = "Итоги встречи") -> LinkPreview:
    return LinkPreview(
        url="https://example.com/report",
        kind=kind,
        title=title,
        page_count=pages,
        full=full,
        image_path=Path("preview.png"),
    )


class PreviewTextTests(unittest.TestCase):
    def test_full_document_has_no_status(self) -> None:
        preview = _preview("document", 1, full=True)
        self.assertIsNone(preview.status)
        self.assertEqual(preview.annotation, "На экране документ „Итоги встречи“")

    def test_partial_document_reports_page_count(self) -> None:
        preview = _preview("document", 3, full=False)
        self.assertEqual(preview.status, "стр. 1 из 3 · остальное по ссылке")
        self.assertEqual(
            preview.annotation,
            "На экране документ „Итоги встречи“, страница 1 из 3, "
            "остальное по ссылке",
        )

    def test_full_presentation_has_no_status(self) -> None:
        preview = _preview("slides", 1, full=True)
        self.assertIsNone(preview.status)
        self.assertEqual(
            preview.annotation, "На экране презентация „Итоги встречи“"
        )

    def test_partial_presentation_uses_slides(self) -> None:
        preview = _preview("slides", 25, full=False)
        self.assertEqual(preview.status, "слайд 1 из 25 · остальное по ссылке")
        self.assertIn("слайд 1 из 25", preview.annotation)

    def test_site_is_always_partial(self) -> None:
        preview = _preview("site", 1, full=False, title="Блог")
        self.assertEqual(preview.status, "первый экран · остальное по ссылке")
        self.assertEqual(
            preview.annotation,
            "На экране первый экран сайта, остальное по ссылке",
        )

    def test_image_is_full_and_has_no_title(self) -> None:
        preview = _preview("image", 1, full=True, title="")
        self.assertIsNone(preview.status)
        self.assertEqual(preview.annotation, "На экране изображение")


class YandexDocsTests(unittest.TestCase):
    def test_file_name_is_stripped_from_the_public_key(self) -> None:
        inner = (
            "ya-disk-public://abc/def==:/Таб. 2. Карта метрик.pdf"
        )
        self.assertEqual(
            yandex_docs_target(inner),
            "https://disk.yandex.ru/i/abc/def==",
        )

    def test_plain_url_is_passed_through(self) -> None:
        url = "https://disk.yandex.ru/i/abc"
        self.assertEqual(yandex_docs_target(url), url)

    def test_stale_public_key_falls_back_to_the_viewer(self) -> None:
        sentinel = LinkPreview(
            url="https://docs.yandex.ru/docs/view?x=1",
            kind="site",
            title="Просмотр",
            page_count=1,
            full=False,
            image_path=Path("preview.png"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _Fetcher(Path(tmp), {}, lambda *_: None)
            with mock.patch.object(
                fetcher, "_preview", side_effect=PreviewError("resource not found")
            ), mock.patch.object(
                fetcher, "_download", return_value=b"<html></html>"
            ), mock.patch.object(
                fetcher, "_site", return_value=sentinel
            ):
                result = fetcher._yandex_docs(
                    "https://docs.yandex.ru/docs/view?url=ya-disk-public%3A%2F%2Fabc"
                    "%3A%2Ffile.pdf&nosw=1",
                    "",
                    0,
                )
        self.assertIs(result, sentinel)

    def test_advertised_pdf_that_is_html_falls_back_to_the_viewer(self) -> None:
        sentinel = LinkPreview(
            url="https://docs.yandex.ru/docs/view?x=2",
            kind="site",
            title="Просмотр",
            page_count=1,
            full=False,
            image_path=Path("preview.png"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _Fetcher(Path(tmp), {}, lambda *_: None)
            with mock.patch.object(
                fetcher, "_preview", side_effect=PreviewError("resource not found")
            ), mock.patch.object(
                fetcher,
                "_download",
                side_effect=[
                    b'<a href="https://example.com/file.pdf">pdf</a>',
                    b"<html>error</html>",
                ],
            ), mock.patch.object(
                fetcher, "_site", return_value=sentinel
            ):
                result = fetcher._yandex_docs(
                    "https://docs.yandex.ru/docs/view?url=ya-disk-public%3A%2F%2Fabc"
                    "%3A%2Ffile.pdf&nosw=1",
                    "",
                    0,
                )
        self.assertIs(result, sentinel)


class TitleTests(unittest.TestCase):
    def test_generator_placeholder_falls_back_to_the_anchor(self) -> None:
        self.assertEqual(
            preferred_title("Creator: Google Sheets", "Шаблон квартала"),
            "Шаблон квартала",
        )

    def test_real_pdf_title_wins(self) -> None:
        self.assertEqual(
            preferred_title("Итоги встречи", "Ссылка"),
            "Итоги встречи",
        )

    def test_deictic_anchor_becomes_no_title(self) -> None:
        self.assertEqual(preferred_title("Creator: Google Sheets", "здесь"), "")
        self.assertEqual(preferred_title("", "Ссылка"), "")


class CollectLinksTests(unittest.TestCase):
    def test_footnotes_are_ignored_and_a_descriptive_anchor_wins(self) -> None:
        chapter = Chapter(
            index=1,
            href="ch1.xhtml",
            title="Глава 1",
            blocks=[
                Block(
                    "paragraph",
                    "Текст.",
                    links=[
                        Link("здесь", "https://example.com/a"),
                        Link("Итоги встречи", "https://example.com/a"),
                    ],
                ),
                Block(
                    "footnote",
                    "Сноска.",
                    links=[Link("сноска", "https://example.com/ignored")],
                ),
                Block(
                    "paragraph",
                    "Ещё текст.",
                    links=[Link("статья", "https://example.com/b")],
                ),
            ],
        )
        self.assertEqual(
            collect_links([chapter]),
            {
                "https://example.com/a": "Итоги встречи",
                "https://example.com/b": "статья",
            },
        )

    def test_compact_url_drops_scheme_and_query(self) -> None:
        self.assertEqual(
            compact_url("https://www.example.com/a/b/?utm=1#top"),
            "example.com/a/b",
        )


@unittest.skipUnless(
    shutil.which("pdfinfo") and shutil.which("pdftoppm"),
    "poppler-utils is required for PDF previews",
)
class PdfTests(unittest.TestCase):
    def test_one_page_pdf_is_full(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preview = preview_from_pdf(
                _pdf(1),
                url="https://example.com/one.pdf",
                title="Один лист",
                out_dir=tmp,
            )
            self.assertEqual(preview.page_count, 1)
            self.assertTrue(preview.full)
            self.assertIsNone(preview.status)
            self.assertTrue(preview.image_path.exists())
            self.assertGreater(preview.image_path.stat().st_size, 1000)

    def test_multi_page_pdf_is_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preview = preview_from_pdf(
                _pdf(2),
                url="https://example.com/two.pdf",
                title="Два листа",
                out_dir=tmp,
            )
            self.assertEqual(preview.page_count, 2)
            self.assertFalse(preview.full)
            self.assertEqual(preview.status, "стр. 1 из 2 · остальное по ссылке")
            self.assertIn("страница 1 из 2", preview.annotation)


class ImageTests(unittest.TestCase):
    def test_image_preview_is_full(self) -> None:
        buffer = BytesIO()
        Image.new("RGB", (320, 200), (10, 20, 30)).save(buffer, "PNG")
        with tempfile.TemporaryDirectory() as tmp:
            preview = preview_from_image(
                buffer.getvalue(),
                url="https://example.com/image.png",
                out_dir=tmp,
            )
            self.assertEqual(preview.kind, "image")
            self.assertTrue(preview.full)
            self.assertEqual(preview.page_count, 1)
            self.assertEqual(preview.annotation, "На экране изображение")
            self.assertTrue(preview.image_path.exists())


class CacheTests(unittest.TestCase):
    def test_cache_is_reused_and_offline_reads_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "source.png"
            Image.new("RGB", (64, 64), (200, 10, 10)).save(image, "PNG")
            calls: list[str] = []

            def fetch(url: str, anchor: str) -> LinkPreview:
                calls.append(url)
                return LinkPreview(
                    url=url,
                    kind="document",
                    title=anchor or "Документ",
                    page_count=1,
                    full=True,
                    image_path=image,
                )

            cache = root / "links"
            anchors = {"https://example.com/a": "Документ"}
            first = resolve_links(
                anchors,
                cache,
                anchors=anchors,
                fetch=fetch,
                log=lambda *_: None,
            )
            self.assertIn("https://example.com/a", first)
            self.assertEqual(calls, ["https://example.com/a"])
            self.assertTrue((cache / first["https://example.com/a"].image_path.parent.name / "meta.json").exists())

            second = resolve_links(
                anchors,
                cache,
                offline=True,
                anchors=anchors,
                fetch=fetch,
                log=lambda *_: None,
            )
            self.assertIn("https://example.com/a", second)
            self.assertEqual(calls, ["https://example.com/a"])
            self.assertIsNone(second["https://example.com/a"].status)

            missing = resolve_links(
                ["https://example.com/b"],
                cache,
                offline=True,
                fetch=fetch,
                log=lambda *_: None,
            )
            self.assertEqual(missing, {})
            self.assertEqual(calls, ["https://example.com/a"])

    def test_failure_is_not_cached(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []

            def fetch(url: str, anchor: str) -> None:
                calls.append(url)
                return None

            cache = Path(tmp) / "links"
            resolve_links(["https://example.com/a"], cache, fetch=fetch, log=lambda *_: None)
            resolve_links(["https://example.com/a"], cache, fetch=fetch, log=lambda *_: None)
            self.assertEqual(calls, ["https://example.com/a", "https://example.com/a"])
            self.assertEqual(list(cache.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
