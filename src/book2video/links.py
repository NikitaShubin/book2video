"""External link previews.

Every external link in a content block is attempted.  A preview replaces the
QR frame only when an adapter can produce a still image; every failure stays a
normal QR frame.  There is no captcha or login heuristic: whatever the adapter
captured is shown, and the QR remains on the frame so the viewer can decide.

The adapters are deliberately narrow:

* Google Docs / Sheets / Slides -> PDF export;
* ``disk.yandex.ru`` -> the public-resources API;
* ``docs.yandex.ru`` -> an embedded PDF when one can be found, otherwise a
  screenshot of the viewer;
* a generic PDF -> the first page via poppler;
* a generic image -> the image itself;
* HTML -> the first viewport via Playwright;
* anything else (docx, zip, video, ...) -> no preview, QR only.

A preview is cached per book under ``<work>/links/<sha256(url)>/``.  The cache
is read and populated on every run.  In ``--offline-links`` mode it is the only
source: a cache miss is a QR, never a network request.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable, Mapping
from urllib.parse import parse_qs, unquote, urlparse

import requests
from PIL import Image

from .epub import Chapter

MAX_BYTES = 50 * 1024 * 1024
HTTP_TIMEOUT = (10.0, 20.0)
PLAYWRIGHT_TIMEOUT_MS = 20_000
PLAYWRIGHT_SETTLE_MS = 3_000
VIEWPORT = {"width": 1440, "height": 900}
DEVICE_SCALE = 2
PDF_DPI = 150

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 book2video"
)

_GOOGLE_RE = re.compile(
    r"^/(document|spreadsheets|presentation)/(?:u/\d+/)?d/(.+?)(?:/|$)"
)
_DRIVE_FILE_RE = re.compile(r"^/file/d/([^/]+)")
_YANDEX_DOCS_DISK_RE = re.compile(r"^ya-disk-public://(.+)$", re.I)
_PDF_LINK_RE = re.compile(r"https?://[^\s\"'<>]+\.pdf(?:\?[^\s\"'<>]*)?", re.I)

_UNSUPPORTED_EXT = {
    ".doc",
    ".docx",
    ".rtf",
    ".odt",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".mp3",
    ".wav",
    ".ogg",
    ".flac",
    ".exe",
    ".dmg",
    ".apk",
    ".epub",
    ".fb2",
    ".txt",
    ".csv",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
}

_DEICTIC_ANCHORS = {
    "здесь",
    "тут",
    "ссылка",
    "по ссылке",
    "подробнее",
    "скачать",
    "смотреть",
    "посмотреть",
    "открыть",
}

_KIND_LABELS = {
    "document": "документ",
    "slides": "презентация",
    "site": "сайт",
    "image": "изображение",
}


class PreviewError(RuntimeError):
    """A preview could not be produced; the caller falls back to a QR frame."""


@dataclass(frozen=True)
class LinkPreview:
    """A still image that can replace a QR frame for one URL."""

    url: str
    kind: str  # document | slides | site | image
    title: str
    page_count: int
    full: bool
    image_path: Path

    @property
    def status(self) -> str | None:
        """Footer status; ``None`` when the whole item is on screen."""
        if self.full:
            return None
        if self.kind == "site":
            return "первый экран · остальное по ссылке"
        if self.kind == "slides":
            return f"слайд 1 из {self.page_count} · остальное по ссылке"
        return f"стр. 1 из {self.page_count} · остальное по ссылке"

    @property
    def annotation(self) -> str:
        """The sentence read by the annotation voice after the URL."""
        if self.kind == "image":
            return "На экране изображение"
        if self.kind == "site":
            return "На экране первый экран сайта, остальное по ссылке"
        label = _KIND_LABELS.get(self.kind, "документ")
        title = f" „{self.title}“" if self.title else ""
        if self.full:
            return f"На экране {label}{title}"
        page = "слайд" if self.kind == "slides" else "страница"
        return (
            f"На экране {label}{title}, {page} 1 из {self.page_count}, "
            "остальное по ссылке"
        )

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "kind": self.kind,
            "title": self.title,
            "page_count": self.page_count,
            "full": self.full,
            "status": self.status,
            "annotation": self.annotation,
            "image": str(self.image_path),
        }


# ---------------------------------------------------------------------------
# Link collection and spoken form


def is_http_url(url: str) -> bool:
    return url.lower().startswith(("http://", "https://"))


def yandex_docs_target(inner: str) -> str:
    """Map a docs.yandex.ru ``url=`` value to a resolvable target.

    The viewer wraps a Disk public key as
    ``ya-disk-public://<key>:/<file name>``.  Only ``<key>`` belongs to the
    API; keeping the file name makes the lookup 404.
    """
    disk = _YANDEX_DOCS_DISK_RE.match(inner)
    if not disk:
        return inner
    key = disk.group(1).split(":/", 1)[0].rstrip("/")
    return f"https://disk.yandex.ru/i/{key}"


def collect_links(chapters: Iterable[Chapter]) -> dict[str, str]:
    """Return ``{url: best anchor text}`` in first-seen order.

    Footnote blocks are skipped completely: their links are reference
    apparatus, not part of the narration.  A later descriptive anchor wins
    over an earlier deictic one ("здесь", "скачать").
    """
    result: dict[str, str] = {}
    for chapter in chapters:
        for block in chapter.blocks:
            if block.kind == "footnote":
                continue
            for link in block.links:
                url = link.href.strip()
                if not is_http_url(url):
                    continue
                anchor = link.text.strip()
                if not result.get(url) or _anchor_score(anchor) > _anchor_score(result[url]):
                    result[url] = anchor
    return result


def _anchor_score(text: str) -> int:
    text = text.strip()
    if not text or text.lower() in _DEICTIC_ANCHORS:
        return 0
    if len(text) > 120:
        return 1
    return 2


def compact_url(url: str, max_chars: int = 120) -> str:
    """A readable URL for the footer: no scheme, no query, middle ellipsis."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = unquote(parsed.path).rstrip("/")
    text = f"{host}{path}"
    if not text:
        return url
    if len(text) > max_chars:
        keep = max(1, max_chars - 1)
        head = keep * 3 // 5
        tail = keep - head
        text = f"{text[:head]}…{text[-tail:]}"
    return text


# ---------------------------------------------------------------------------
# Cache


def resolve_links(
    urls: Iterable[str],
    cache_dir: str | Path,
    *,
    offline: bool = False,
    anchors: Mapping[str, str] | None = None,
    fetch: Callable[[str, str], LinkPreview | None] | None = None,
    log=print,
) -> dict[str, LinkPreview]:
    """Resolve every unique URL to a preview, using the per-book cache.

    ``fetch`` is the network seam; tests inject a fake.  A ``None`` result is
    not cached: the site may come back next run.
    """
    cache_root = Path(cache_dir)
    cache_root.mkdir(parents=True, exist_ok=True)
    anchors = anchors or {}

    unique = [url for url in dict.fromkeys(urls) if is_http_url(url)]
    total = len(unique)
    result: dict[str, LinkPreview] = {}

    with tempfile.TemporaryDirectory(prefix="book2video-links-") as tmp:
        if fetch is None:
            fetcher = _Fetcher(Path(tmp), anchors, log)
            fetch = fetcher.preview

        for index, url in enumerate(unique, 1):
            entry = cache_root / _cache_key(url)
            cached = _load_cached(entry, url)
            if cached is not None:
                result[url] = cached
                log(f"[links {index:3d}/{total}] cached {cached.kind}: {url}")
                continue

            if offline:
                log(f"[links {index:3d}/{total}] QR (offline, no cache): {url}")
                continue

            try:
                preview = fetch(url, anchors.get(url, ""))
            except Exception as exc:  # the fetcher normally catches its own errors
                log(f"[links {index:3d}/{total}] QR ({exc}): {url}")
                continue
            if preview is None:
                log(f"[links {index:3d}/{total}] QR (not renderable): {url}")
                continue

            preview = replace(preview, url=url)
            stored = _store_cached(entry, preview)
            result[url] = stored
            log(
                f"[links {index:3d}/{total}] content {stored.kind}"
                f"{f' ({stored.page_count} p.)' if stored.page_count > 1 else ''}: {url}"
            )

    return result


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _load_cached(entry: Path, url: str) -> LinkPreview | None:
    meta_path = entry / "meta.json"
    image_path = entry / "preview.png"
    if not meta_path.exists() or not image_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("url") != url:
            return None
        kind = meta["kind"]
        page_count = int(meta["page_count"])
        full = bool(meta["full"])
        title = str(meta.get("title") or "")
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if kind not in _KIND_LABELS:
        return None
    return LinkPreview(
        url=url,
        kind=kind,
        title=title,
        page_count=page_count,
        full=full,
        image_path=image_path,
    )


def _store_cached(entry: Path, preview: LinkPreview) -> LinkPreview:
    entry.parent.mkdir(parents=True, exist_ok=True)
    tmp = entry.with_name(f".{entry.name}.tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    image_path = tmp / "preview.png"
    if preview.image_path.resolve() != image_path.resolve():
        shutil.copyfile(preview.image_path, image_path)
    meta = {
        "url": preview.url,
        "kind": preview.kind,
        "title": preview.title,
        "page_count": preview.page_count,
        "full": preview.full,
    }
    (tmp / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    shutil.rmtree(entry, ignore_errors=True)
    tmp.rename(entry)
    return replace(preview, image_path=entry / "preview.png")


# ---------------------------------------------------------------------------
# Public render helpers (also used by tests)


def preferred_title(meta_title: str, fallback: str) -> str:
    """Keep a real PDF title, but never speak a generator placeholder.

    A deictic anchor such as "здесь" says nothing about the document, so an
    empty title is better than reading it aloud.
    """
    title = meta_title.strip()
    lowered = title.lower()
    if not title or lowered.startswith("creator:") or lowered in {
        "untitled",
        "document",
        "presentation",
        "spreadsheet",
    }:
        fallback = fallback.strip()
        return "" if fallback.lower() in _DEICTIC_ANCHORS else fallback
    return title


def preview_from_pdf(
    data: bytes,
    *,
    url: str = "",
    title: str = "",
    kind: str = "document",
    out_dir: str | Path | None = None,
) -> LinkPreview:
    """Rasterise the first PDF page and read its page count and title."""
    if not data.startswith(b"%PDF"):
        raise PreviewError("not a PDF")
    out = Path(out_dir or tempfile.mkdtemp(prefix="book2video-pdf-"))
    out.mkdir(parents=True, exist_ok=True)
    pdf_path = out / "source.pdf"
    pdf_path.write_bytes(data)

    info = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if info.returncode != 0:
        raise PreviewError(f"pdfinfo failed: {info.stderr.strip()[-300:]}")
    pages = _parse_int_field(info.stdout, "Pages")
    if not pages:
        raise PreviewError("PDF has no page count")
    meta_title = _parse_text_field(info.stdout, "Title")
    title = preferred_title(meta_title, title)

    prefix = out / "preview"
    render = subprocess.run(
        [
            "pdftoppm",
            "-f",
            "1",
            "-l",
            "1",
            "-r",
            str(PDF_DPI),
            "-png",
            "-singlefile",
            str(pdf_path),
            str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if render.returncode != 0:
        raise PreviewError(f"pdftoppm failed: {render.stderr.strip()[-300:]}")
    image_path = prefix.with_suffix(".png")
    if not image_path.exists():
        raise PreviewError("pdftoppm produced no image")

    return LinkPreview(
        url=url,
        kind=kind,
        title=title,
        page_count=pages,
        full=pages == 1,
        image_path=image_path,
    )


def preview_from_image(
    data: bytes,
    *,
    url: str = "",
    title: str = "",
    out_dir: str | Path | None = None,
) -> LinkPreview:
    """Normalise an arbitrary raster image to a PNG preview."""
    out = Path(out_dir or tempfile.mkdtemp(prefix="book2video-image-"))
    out.mkdir(parents=True, exist_ok=True)
    image_path = out / "preview.png"
    try:
        image = Image.open(BytesIO(data))
        image.load()
    except Exception as exc:
        raise PreviewError(f"not an image: {exc}") from exc
    image = _flatten(image)
    if max(image.size) > 4000:
        image.thumbnail((4000, 4000), Image.Resampling.LANCZOS)
    image.save(image_path, "PNG")
    return LinkPreview(
        url=url,
        kind="image",
        title=title,
        page_count=1,
        full=True,
        image_path=image_path,
    )


def _flatten(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        image = image.convert("RGBA")
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, image)
    return image.convert("RGB")


def _parse_int_field(text: str, name: str) -> int | None:
    match = re.search(rf"^{re.escape(name)}:\s*(\d+)\s*$", text, re.M)
    return int(match.group(1)) if match else None


def _parse_text_field(text: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\s*(.*?)\s*$", text, re.M)
    return " ".join(match.group(1).split()) if match else ""


# ---------------------------------------------------------------------------
# Network fetcher


class _Fetcher:
    def __init__(
        self,
        tmp_dir: Path,
        anchors: Mapping[str, str],
        log,
    ) -> None:
        self.tmp_dir = tmp_dir
        self.anchors = anchors
        self.log = log
        self.session = requests.Session()
        self.session.max_redirects = 5
        self.session.headers.update({"User-Agent": USER_AGENT})

    def preview(self, url: str, anchor: str = "") -> LinkPreview | None:
        try:
            return self._preview(url, anchor, depth=0)
        except Exception as exc:
            self.log(f"links: QR {url} ({exc})")
            return None

    # -- dispatch ---------------------------------------------------------

    def _preview(self, url: str, anchor: str, *, depth: int) -> LinkPreview | None:
        if depth > 2:
            raise PreviewError("too many nested document URLs")
        parsed = urlparse(url)
        host = parsed.netloc.lower().split(":", 1)[0]
        if host.startswith("www."):
            host = host[4:]

        if host == "docs.google.com":
            return self._google(url, anchor)
        if host in {"disk.yandex.ru", "yadi.sk"}:
            return self._yandex_disk(url, anchor)
        if host == "docs.yandex.ru":
            return self._yandex_docs(url, anchor, depth)
        if host == "drive.google.com":
            return self._google_drive(url, anchor)
        return self._generic(url, anchor)

    # -- providers --------------------------------------------------------

    def _google(self, url: str, anchor: str) -> LinkPreview | None:
        parsed = urlparse(url)
        match = _GOOGLE_RE.match(parsed.path)
        if not match:
            return self._generic(url, anchor)
        app, doc_id = match.group(1), match.group(2)
        kind = "slides" if app == "presentation" else "document"
        if app == "document":
            export = f"https://docs.google.com/document/d/{doc_id}/export?format=pdf"
        elif app == "spreadsheets":
            export = f"https://docs.google.com/spreadsheets/d/{doc_id}/export?format=pdf"
        else:
            export = f"https://docs.google.com/presentation/d/{doc_id}/export/pdf"
        data = self._download(export)
        return preview_from_pdf(
            data,
            url=url,
            title=anchor,
            kind=kind,
            out_dir=self._out_dir(),
        )

    def _google_drive(self, url: str, anchor: str) -> LinkPreview | None:
        parsed = urlparse(url)
        match = _DRIVE_FILE_RE.match(parsed.path)
        if not match:
            return self._generic(url, anchor)
        download = f"https://drive.google.com/uc?export=download&id={match.group(1)}"
        data = self._download(download)
        return self._preview_bytes(data, url, anchor, content_type="")

    def _yandex_disk(self, url: str, anchor: str) -> LinkPreview | None:
        api = "https://cloud-api.yandex.net/v1/disk/public/resources"
        meta = self._get_json(api, params={"public_key": url})
        if meta.get("type") != "file":
            raise PreviewError("Yandex Disk resource is not a file")
        name = str(meta.get("name") or "")
        mime = str(meta.get("mime_type") or "").split(";")[0].strip().lower()
        href = self._get_json(f"{api}/download", params={"public_key": url}).get("href")
        if not href:
            raise PreviewError("Yandex Disk returned no download URL")
        data = self._download(href)
        title = Path(name).stem if name else anchor
        if mime == "application/pdf" or data.startswith(b"%PDF") or name.lower().endswith(".pdf"):
            return preview_from_pdf(
                data, url=url, title=title, kind="document", out_dir=self._out_dir()
            )
        if mime.startswith("image/"):
            return preview_from_image(
                data, url=url, title=title, out_dir=self._out_dir()
            )
        raise PreviewError(f"unsupported Yandex Disk type {mime or name!r}")

    def _yandex_docs(self, url: str, anchor: str, depth: int) -> LinkPreview | None:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        inner = (params.get("url") or [""])[0]
        if inner:
            inner = yandex_docs_target(inner)
            if is_http_url(inner) and inner != url:
                try:
                    return self._preview(inner, anchor, depth=depth + 1)
                except (PreviewError, requests.RequestException):
                    # A public key can go stale while the viewer still renders
                    # the document.  Fall through to the embedded PDF or the
                    # viewer screenshot instead of discarding the frame.
                    pass

        html = self._download(url).decode("utf-8", "replace")
        match = _PDF_LINK_RE.search(html)
        if match:
            try:
                data = self._download(match.group(0).replace("&amp;", "&"))
                if data.startswith(b"%PDF"):
                    return preview_from_pdf(
                        data,
                        url=url,
                        title=anchor,
                        kind="document",
                        out_dir=self._out_dir(),
                    )
            except (PreviewError, requests.RequestException):
                # The viewer may advertise a .pdf URL that is really an HTML
                # error page.  A screenshot is still worth showing.
                pass
        return self._site(url, anchor)

    # -- generic ----------------------------------------------------------

    def _generic(self, url: str, anchor: str) -> LinkPreview | None:
        parsed = urlparse(url)
        ext = Path(parsed.path).suffix.lower()
        if ext in _UNSUPPORTED_EXT:
            raise PreviewError(f"unsupported file type {ext}")

        response = self._get(url, stream=True)
        try:
            content_type = (
                response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            )
            data = self._read_limited(response)
        finally:
            response.close()

        if content_type == "text/html" or content_type == "application/xhtml+xml":
            return self._site(url, anchor)
        if content_type.startswith("image/svg"):
            return self._site(url, anchor)
        return self._preview_bytes(data, url, anchor, content_type=content_type, ext=ext)

    def _preview_bytes(
        self,
        data: bytes,
        url: str,
        anchor: str,
        *,
        content_type: str,
        ext: str = "",
    ) -> LinkPreview | None:
        if (
            content_type == "application/pdf"
            or data.startswith(b"%PDF")
            or ext == ".pdf"
        ):
            return preview_from_pdf(
                data, url=url, title=anchor, kind="document", out_dir=self._out_dir()
            )
        if content_type.startswith("image/"):
            return preview_from_image(
                data, url=url, title=anchor, out_dir=self._out_dir()
            )
        if content_type in {"text/html", "application/xhtml+xml"}:
            return self._site(url, anchor)
        if data.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html")):
            return self._site(url, anchor)
        raise PreviewError(f"unsupported content type {content_type or 'unknown'!r}")

    def _site(self, url: str, anchor: str) -> LinkPreview:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise PreviewError("playwright is not installed") from exc

        out_path = self._out_dir() / "preview.png"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                page = browser.new_page(
                    viewport=VIEWPORT, device_scale_factor=DEVICE_SCALE
                )
                page.set_default_navigation_timeout(PLAYWRIGHT_TIMEOUT_MS)
                page.set_default_timeout(PLAYWRIGHT_TIMEOUT_MS)
                try:
                    page.goto(url, wait_until="networkidle")
                except PlaywrightTimeoutError:
                    # The 20 s budget is part of the policy.  Keep whatever was
                    # painted instead of granting a second navigation attempt.
                    pass
                page.wait_for_timeout(PLAYWRIGHT_SETTLE_MS)
                page.add_style_tag(
                    content=(
                        "html{scrollbar-width:none}"
                        "::-webkit-scrollbar{display:none}"
                    )
                )
                page.screenshot(path=str(out_path), full_page=False)
                title = " ".join((page.title() or "").split())
            finally:
                browser.close()

        return LinkPreview(
            url=url,
            kind="site",
            title=title or anchor,
            page_count=1,
            full=False,
            image_path=out_path,
        )

    # -- HTTP helpers -----------------------------------------------------

    def _get(self, url: str, *, params=None, stream: bool = False) -> requests.Response:
        response = self.session.get(
            url,
            params=params,
            timeout=HTTP_TIMEOUT,
            stream=stream,
            allow_redirects=True,
        )
        response.raise_for_status()
        return response

    def _get_json(self, url: str, *, params=None) -> dict:
        response = self._get(url, params=params)
        try:
            return response.json()
        finally:
            response.close()

    def _download(self, url: str) -> bytes:
        response = self._get(url, stream=True)
        try:
            return self._read_limited(response)
        finally:
            response.close()

    @staticmethod
    def _read_limited(response: requests.Response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_BYTES:
                raise PreviewError("response exceeds 50 MB")
            chunks.append(chunk)
        return b"".join(chunks)

    def _out_dir(self) -> Path:
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="item-", dir=self.tmp_dir))
