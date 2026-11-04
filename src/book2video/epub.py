"""EPUB parsing for narration and illustration timing.

The parser turns an EPUB spine into a flat sequence of :class:`Block` objects.
A block is the smallest unit we need for the video: a heading, a paragraph, a
sidebar, an image with its caption, or an HTML table.  Inline footnote markers
are dropped (endnotes are not narrated), while external links are preserved so
the timeline can add a spoken URL and a QR frame.

No third-party EPUB library is required: an EPUB is a ZIP with an OPF package
document, and ``beautifulsoup4`` + ``lxml`` are enough for the XHTML.
"""

from __future__ import annotations

import posixpath
import re
import warnings
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning
from PIL import Image

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

_WHITESPACE_RE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?…])")
_EXTERNAL_RE = re.compile(r"^https?://", re.I)
_IMAGE_EXT_RE = re.compile(r"\.(?:png|jpe?g|gif|webp|svg)$", re.I)

BOX_CLASS_RE = re.compile(r"(?:vrez|vstavka)", re.I)
CAPTION_CLASSES = {"podris", "tablpodp"}
HEADING_CLASSES = {
    "podzag1",
    "podzag2",
    "podzag3",
    "podzag3_0",
    "podzag2_0",
}
CHAPTER_NUMBER_RE = re.compile(r"^\s*Глава\s+(\d+)", re.I)
CHAPTER_WORD_RE = re.compile(r"^\s*Глава\s+([а-яё]+)", re.I)
CHAPTER_HEADING_RE = re.compile(
    r"^\s*(?:Глава\s+(?:\d+|[а-яё]+)|Часть\s+\d+)\s*$", re.I
)
_ORDINAL_STEMS = {
    "перв": 1,
    "втор": 2,
    "трет": 3,
    "четверт": 4,
    "пят": 5,
    "шест": 6,
    "седьм": 7,
    "восьм": 8,
    "девят": 9,
    "десят": 10,
    "одиннадцат": 11,
    "двенадцат": 12,
}
_DECOR_IMAGE_RE = re.compile(r"(logo|icon|cover|emblem|qr)", re.I)


@dataclass
class Link:
    text: str
    href: str


@dataclass
class Block:
    """A single narration / illustration unit."""

    kind: str  # heading | paragraph | sidebar | caption | image | table | html_table
    text: str = ""
    level: int = 0
    image: str | None = None
    caption: str = ""
    links: list[Link] = field(default_factory=list)
    box: bool = False
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class Chapter:
    index: int
    href: str
    title: str
    blocks: list[Block]
    number: int | None = None

    @property
    def text(self) -> str:
        return " ".join(b.text for b in self.blocks if b.text)


@dataclass
class Book:
    path: Path
    title: str
    author: str
    chapters: list[Chapter]
    _zip: zipfile.ZipFile = field(repr=False)

    def read(self, resource: str) -> bytes:
        """Read a resource by archive path."""
        return self._zip.read(resource)

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> "Book":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Package document


def _local(name: str) -> str:
    return name.split(":")[-1].lower()


def _find_first(node: Tag, local_name: str) -> Tag | None:
    for tag in node.find_all(True):
        if _local(tag.name) == local_name:
            return tag
    return None


def _resolve(base_dir: str, href: str) -> str:
    href = href.split("#", 1)[0]
    return posixpath.normpath(posixpath.join(base_dir, href))


def _load_package(zf: zipfile.ZipFile) -> tuple[str, str, str, list[tuple[str, str]]]:
    container = BeautifulSoup(zf.read("META-INF/container.xml"), "xml")
    rootfile = container.find("rootfile")
    if rootfile is None:
        raise ValueError("EPUB container.xml has no rootfile")
    opf_path = rootfile["full-path"]
    opf_dir = posixpath.dirname(opf_path)

    package = BeautifulSoup(zf.read(opf_path), "xml")
    title_tag = _find_first(package, "title")
    creator_tag = _find_first(package, "creator")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""
    author = creator_tag.get_text(" ", strip=True) if creator_tag else ""

    manifest: dict[str, tuple[str, str]] = {}
    manifest_tag = _find_first(package, "manifest")
    if manifest_tag is not None:
        for item in manifest_tag.find_all("item"):
            item_id = item.get("id") or ""
            href = item.get("href") or ""
            media_type = item.get("media-type") or ""
            if item_id and href:
                manifest[item_id] = (_resolve(opf_dir, href), media_type)

    spine: list[tuple[str, str]] = []
    spine_tag = _find_first(package, "spine")
    if spine_tag is not None:
        for itemref in spine_tag.find_all("itemref"):
            item_id = itemref.get("idref") or ""
            if item_id in manifest:
                spine.append(manifest[item_id])
    return title, author, opf_dir, spine


# ---------------------------------------------------------------------------
# Inline text


def _class_set(tag: Tag) -> set[str]:
    return {c.lower() for c in (tag.get("class") or [])}


def _is_footnote_marker(tag: Tag) -> bool:
    classes = _class_set(tag)
    if "super" in classes:
        return True
    if tag.name.lower() == "sup":
        return True
    href = tag.get("href") or ""
    return tag.name.lower() == "a" and (
        "footnote" in href.lower() or href.lower().startswith("#fn")
    )


def inline_text(node: Tag | NavigableString) -> tuple[str, list[Link]]:
    """Return visible text and external links, dropping footnote markers."""
    parts: list[str] = []
    links: list[Link] = []

    def walk(current: Tag | NavigableString) -> None:
        if isinstance(current, NavigableString):
            parts.append(str(current))
            return
        if not isinstance(current, Tag):
            return
        name = current.name.lower()
        if name in {"script", "style"}:
            return
        if _is_footnote_marker(current):
            return
        if name == "br":
            parts.append(" ")
            return
        if name == "a":
            href = (current.get("href") or "").strip()
            text = _plain_text(current)
            if _EXTERNAL_RE.match(href) and text:
                links.append(Link(text=text, href=href))
            # Keep walking: the anchor text is part of the sentence.
        for child in current.children:
            walk(child)

    walk(node)
    text = "".join(parts).replace("\u00ad", "").replace("\u200b", "")
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    return text, links


def _plain_text(node: Tag) -> str:
    parts: list[str] = []

    def walk(current: Tag | NavigableString) -> None:
        if isinstance(current, NavigableString):
            parts.append(str(current))
            return
        if not isinstance(current, Tag):
            return
        if _is_footnote_marker(current) or current.name.lower() in {"script", "style"}:
            return
        for child in current.children:
            walk(child)

    walk(node)
    return _WHITESPACE_RE.sub(" ", "".join(parts)).strip()


# ---------------------------------------------------------------------------
# Document parsing


def _caption_of(node: Tag) -> str:
    for paragraph in node.find_all("p"):
        if _class_set(paragraph) & CAPTION_CLASSES:
            return inline_text(paragraph)[0]
    caption = node.find("caption")
    if caption is not None:
        return inline_text(caption)[0]
    return ""


def _looks_like_table(caption: str, src: str) -> bool:
    if caption.lower().startswith("таблица"):
        return True
    return "table" in Path(src).stem.lower()


def _image_is_usable(book: Book, src: str) -> bool:
    """Drop covers, logos, icons and images that are too small to read."""
    if _DECOR_IMAGE_RE.search(posixpath.basename(src)):
        return False
    try:
        data = book.read(src)
    except KeyError:
        return False
    if src.lower().endswith(".svg"):
        return True
    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
    except Exception:
        return True
    return width >= 64 and height >= 64


def parse_document(book: Book, href: str) -> list[Block]:
    # EPUB bodies are XHTML but not always well-formed XML.  The HTML parser
    # is deliberately tolerant; the warning about "XML parsed as HTML" is
    # expected noise for this input.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(book.read(href), "lxml")
    body = soup.body or soup
    blocks: list[Block] = []
    skip: set[int] = set()

    def emit(block: Block) -> None:
        blocks.append(block)

    def last_image() -> Block | None:
        for block in reversed(blocks):
            if block.kind in {"image", "table"}:
                return block
            if block.kind != "caption":
                return None
        return None

    def handle_paragraph(paragraph: Tag, box: bool) -> None:
        classes = _class_set(paragraph)
        text, links = inline_text(paragraph)
        if not text and not links:
            return
        if "snoska" in classes:
            emit(Block("footnote", text, links=links, box=box))
            return
        if "glava_num" in classes:
            emit(Block("heading", text, level=1, links=links, box=box))
            return
        if classes & HEADING_CLASSES:
            emit(Block("heading", text, level=2, links=links, box=box))
            return
        if classes & CAPTION_CLASSES:
            image = last_image()
            if image is not None and not image.caption:
                image.caption = text
                image.text = text
                image.links.extend(links)
                return
            if image is not None and image.caption == text:
                return
            emit(Block("caption", text, links=links, box=box))
            return
        in_box = box or any(BOX_CLASS_RE.search(cls) for cls in classes)
        kind = "sidebar" if in_box else "paragraph"
        emit(Block(kind, text, links=links, box=in_box))

    def handle_image_container(container: Tag, box: bool) -> None:
        image_tag = container.find("img")
        if image_tag is None:
            for child in container.children:
                handle_node(child, box=box)
            return
        src = _resolve(posixpath.dirname(href), image_tag.get("src") or "")
        if not src or not _IMAGE_EXT_RE.search(src):
            return
        if not _image_is_usable(book, src):
            # Decorative image: keep any narration that sits next to it.
            for child in container.children:
                if not isinstance(child, Tag):
                    continue
                if child.name.lower() == "img":
                    continue
                if child.name.lower() == "p" and (_class_set(child) & CAPTION_CLASSES):
                    continue
                handle_node(child, box=box)
            return
        caption = _caption_of(container)
        is_table = _looks_like_table(caption, src)
        image = Block(
            "table" if is_table else "image",
            text=caption,
            image=src,
            caption=caption,
            box=box,
        )
        emit(image)

        # Everything else inside the container (a sidebar comment, an external
        # link) follows the caption in narration order.
        for child in container.children:
            if not isinstance(child, Tag):
                continue
            if child.name.lower() == "img":
                continue
            if child.name.lower() == "p" and (_class_set(child) & CAPTION_CLASSES):
                continue
            handle_node(child, box=box)

    def handle_list(list_tag: Tag, box: bool) -> None:
        ordered = list_tag.name.lower() == "ol"
        for index, item in enumerate(list_tag.find_all("li", recursive=False), 1):
            text, links = inline_text(item)
            if not text:
                continue
            if ordered and not re.match(r"^\s*\d", text):
                text = f"{index}. {text}"
            emit(Block("paragraph", text, links=links, box=box))

    def handle_html_table(table: Tag, box: bool) -> None:
        caption = _caption_of(table)
        rows: list[list[str]] = []
        for row in table.find_all("tr"):
            cells = [inline_text(cell)[0] for cell in row.find_all(["td", "th"])]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(cells)
        text = caption
        emit(
            Block(
                "html_table",
                text=text,
                caption=caption,
                rows=rows,
                box=box,
            )
        )

    def handle_node(node: Tag | NavigableString, box: bool) -> None:
        if not isinstance(node, Tag):
            return
        if id(node) in skip:
            return
        name = node.name.lower()
        if name in {"script", "style", "nav", "head"}:
            return
        if name == "div":
            classes = _class_set(node)
            if any(c.startswith("title") for c in classes):
                level = 1 if classes & {"title", "title1", "title2"} else 2
                for child in node.children:
                    if isinstance(child, Tag) and child.name.lower() in {
                        "p",
                        "h1",
                        "h2",
                        "h3",
                    }:
                        text, links = inline_text(child)
                        if text:
                            emit(
                                Block(
                                    "heading",
                                    text,
                                    level=level,
                                    links=links,
                                    box=box,
                                )
                            )
                    else:
                        handle_node(child, box=box)
                return
            if any("full_img" in c for c in classes):
                handle_image_container(node, box)
                return
            if any(c.startswith("boxvrez") for c in classes):
                for child in node.children:
                    handle_node(child, box=True)
                return
            for child in node.children:
                handle_node(child, box=box)
            return
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            text, links = inline_text(node)
            if text:
                emit(Block("heading", text, level=int(name[1]), links=links, box=box))
            return
        if name == "p":
            handle_paragraph(node, box)
            return
        if name in {"ul", "ol"}:
            handle_list(node, box)
            return
        if name == "table":
            handle_html_table(node, box)
            return
        if name == "img":
            src = _resolve(posixpath.dirname(href), node.get("src") or "")
            if src and _IMAGE_EXT_RE.search(src) and _image_is_usable(book, src):
                emit(Block("image", image=src, box=box))
            return
        if name in {"hr", "br"}:
            return
        for child in node.children:
            handle_node(child, box=box)

    for child in body.children:
        handle_node(child, box=False)

    # A caption paragraph that follows a caption-less image belongs to it.
    for index, block in enumerate(blocks):
        if block.kind != "caption":
            continue
        for previous in reversed(blocks[:index]):
            if previous.kind in {"image", "table"}:
                if not previous.caption:
                    previous.caption = block.text
                    previous.text = block.text
                    previous.links.extend(block.links)
                    block.kind = "merged_caption"
                break
            if previous.kind not in {"caption", "merged_caption"}:
                break

    return [b for b in blocks if b.kind != "merged_caption"]


# ---------------------------------------------------------------------------
# Chapter filtering


_BACK_MATTER_TITLE_RE = re.compile(
    r"^\s*(?:"
    r"благодарност|об авторе|примечани|сноск|комментари|"
    r"литератур|библиограф|источник|указател|"
    r"над книгой работали|миф бизнес|эту книгу хорошо дополняют|серия\b|"
    r"реклам|промо"
    r")",
    re.I,
)
_INTRO_TITLE_RE = re.compile(
    r"^\s*(?:введение|предисловие|пролог|от автора|обращение к читателю|"
    r"как читать эту книгу|об этой книге)",
    re.I,
)
_ABOUT_AUTHOR_RE = re.compile(r"^\s*об авторе\b", re.I)
_NOTES_CHAPTER_RE = re.compile(r"^\s*Глава\s+\d+\s*$", re.I)
_REFERENCE_LINE_RE = re.compile(r"^\s*\d+\.\s+\S")
_COPYRIGHT_RE = re.compile(
    r"(все права защищены|isbn|©|подписано в печать|тираж)", re.I
)
_PROMO_RE = re.compile(r"(mif\.to|все книги по бизнесу|купить книгу|qr-код)", re.I)
_DEDICATION_RE = re.compile(r"^\s*Посвящается", re.I)


def _document_text(blocks: list[Block]) -> str:
    return " ".join(b.text for b in blocks if b.text).strip()


def _strip_leading_front_matter(blocks: list[Block]) -> list[Block]:
    """Start the first document at its introduction, dropping title/copyright."""
    for index, block in enumerate(blocks):
        if block.kind == "heading" and _INTRO_TITLE_RE.match(block.text):
            return blocks[index:]
    return blocks


def _strip_about_author(blocks: list[Block]) -> list[Block]:
    for index, block in enumerate(blocks):
        if block.kind == "heading" and _ABOUT_AUTHOR_RE.match(block.text):
            return blocks[:index]
    return blocks


def _is_title_only(blocks: list[Block]) -> bool:
    """A chapter-title page that belongs to the document that follows it."""
    text = _document_text(blocks)
    if not text or len(text) > 300:
        return False
    return not any(
        b.kind in {"paragraph", "sidebar", "image", "table", "html_table", "footnote"}
        for b in blocks
    )


def _is_content_document(blocks: list[Block]) -> bool:
    if not blocks:
        return False
    footnotes = sum(1 for b in blocks if b.kind == "footnote")
    if footnotes >= 5:
        return False
    text = " ".join(b.text for b in blocks if b.text and b.kind != "footnote").strip()
    images = [b for b in blocks if b.kind in {"image", "table"}]
    if len(text) < 120 and images:
        return False
    if len(text) < 40:
        return False
    head = text[:1200]
    if _DEDICATION_RE.match(text):
        return False
    if _PROMO_RE.search(head):
        return False
    if _COPYRIGHT_RE.search(head) and len(text) < 3000:
        return False
    if text.lower().startswith(("содержание", "оглавление")):
        return False

    title_text = _chapter_title(blocks)
    if title_text and _BACK_MATTER_TITLE_RE.match(title_text):
        return False
    if _NOTES_CHAPTER_RE.match(title_text):
        first_paragraph = next(
            (b.text for b in blocks if b.kind == "paragraph" and b.text), ""
        )
        if _REFERENCE_LINE_RE.match(first_paragraph):
            return False
    return True


def _chapter_title(blocks: list[Block]) -> str:
    headings = [b.text for b in blocks if b.kind == "heading" and b.text]
    if not headings:
        return ""
    first = headings[0].strip()
    if CHAPTER_HEADING_RE.match(first) and len(headings) > 1:
        second = headings[1].strip()
        if second and len(second) < 120 and not CHAPTER_HEADING_RE.match(second):
            return f"{first}. {second}"
    return first


def _chapter_number(title: str) -> int | None:
    match = CHAPTER_NUMBER_RE.match(title)
    if match:
        return int(match.group(1))
    match = CHAPTER_WORD_RE.match(title)
    if match:
        word = match.group(1).lower()
        for stem, number in _ORDINAL_STEMS.items():
            if word.startswith(stem):
                return number
    return None


def load_book(path: str | Path) -> Book:
    path = Path(path)
    zf = zipfile.ZipFile(path)
    title, author, _, spine = _load_package(zf)
    book = Book(path=path, title=title, author=author, chapters=[], _zip=zf)

    parsed: list[tuple[str, list[Block]]] = []
    for href, media_type in spine:
        if "html" not in media_type and not href.lower().endswith((".html", ".xhtml", ".htm")):
            continue
        try:
            blocks = parse_document(book, href)
        except (KeyError, ValueError):
            continue
        if not blocks:
            continue
        blocks = _strip_about_author(blocks)
        if not blocks:
            continue
        parsed.append((href, blocks))

    # The first document often starts with a title page, copyright and a promo
    # page; keep the introduction and everything after it.
    if parsed:
        href, blocks = parsed[0]
        parsed[0] = (href, _strip_leading_front_matter(blocks))

    # A separate XHTML file may hold only the chapter title; attach it to the
    # body that follows so the chapter is not a 5-second title card.
    merged: list[tuple[str, list[Block]]] = []
    pending: list[Block] = []
    for href, blocks in parsed:
        if _is_title_only(blocks):
            pending.extend(blocks)
            continue
        if pending:
            blocks = pending + blocks
            pending = []
        merged.append((href, blocks))

    first_numbered: int | None = None
    for index, (_, blocks) in enumerate(merged):
        if _chapter_number(_chapter_title(blocks)) is not None:
            first_numbered = index
            break

    chapters: list[Chapter] = []
    for index, (href, blocks) in enumerate(merged):
        title_text = _chapter_title(blocks)
        text = _document_text(blocks)
        if first_numbered is not None and index < first_numbered:
            # Short front-matter pages (promo, series, dedication) before the
            # first real chapter. Prefaces and introductions are longer.
            if len(text) < 500 and not _INTRO_TITLE_RE.match(title_text):
                continue
        if not _is_content_document(blocks):
            continue
        chapters.append(
            Chapter(
                index=len(chapters) + 1,
                href=href,
                title=title_text or Path(href).stem,
                blocks=blocks,
                number=_chapter_number(title_text),
            )
        )

    book.chapters = chapters
    return book


def select_chapter(book: Book, selector: str | int | None) -> Chapter:
    if selector is None:
        if not book.chapters:
            raise ValueError("No content chapters found")
        return book.chapters[0]
    text = str(selector).strip()
    if text.isdigit():
        number = int(text)
        for chapter in book.chapters:
            if chapter.number == number:
                return chapter
        if 1 <= number <= len(book.chapters):
            return book.chapters[number - 1]
        raise ValueError(f"Chapter {number} not found")
    lowered = text.lower()
    for chapter in book.chapters:
        if lowered in chapter.title.lower() or lowered in chapter.href.lower():
            return chapter
    raise ValueError(f"Chapter {selector!r} not found")
