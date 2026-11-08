"""Frame preparation and ffmpeg rendering."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .epub import Book
from .gpu import encoder_args, resolve_encoder
from .images.qr import make_qr_frame, make_qr_image
from .links import LinkPreview, compact_url
from .timeline import ChapterPlan

WIDTH = 1920
HEIGHT = 1080
BACKGROUND = (255, 255, 255)
FIGURE_MARGIN = 0.94
TABLE_MARGIN = 0.985

CONTENT_BACKGROUND = (16, 18, 22)
CONTENT_MARGIN = 24
CONTENT_FOOTER_H = 144
CONTENT_RULE = (58, 64, 74)
CONTENT_TEXT = (240, 240, 240)
CONTENT_MUTED = (154, 160, 170)
CONTENT_QR_SIZE = 112
CONTENT_QR_PAD = 8

# Every still image passed to the concat filter keeps a decoder and a frame
# buffer alive.  A book with hundreds of illustrations can exhaust a 14 GiB
# container before encoding starts: 96 inputs at 1920x1080 measured 8.2 GiB
# RSS and were killed by the OOM killer.  Render in bounded chunks and join the
# encoded parts with the concat demuxer; 32 inputs stay below ~3 GiB.
MAX_RENDER_INPUTS = 32

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _flatten(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        image = image.convert("RGBA")
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, image)
    return image.convert("RGB")


def _fit(
    image: Image.Image,
    max_width: int,
    max_height: int,
    *,
    upscale: bool = True,
) -> Image.Image:
    scale = min(max_width / image.width, max_height / image.height)
    if not upscale:
        scale = min(scale, 1.0)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    if size == image.size:
        return image
    return image.resize(size, Image.Resampling.LANCZOS)


def _center_on_frame(image: Image.Image) -> Image.Image:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    x = (WIDTH - image.width) // 2
    y = (HEIGHT - image.height) // 2
    canvas.paste(image, (x, y))
    return canvas


def _prepare_figure(data: bytes, out_path: Path, *, table: bool = False) -> Path:
    image = Image.open(BytesIO(data))
    image.load()
    image = _flatten(image)
    margin = TABLE_MARGIN if table else FIGURE_MARGIN
    image = _fit(image, int(WIDTH * margin), int(HEIGHT * margin))
    _center_on_frame(image).save(out_path, "PNG")
    return out_path


def _render_html_table(rows: list[list[str]], out_path: Path) -> Path:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    if not rows:
        canvas.save(out_path, "PNG")
        return out_path

    font = _font(28)
    columns = max(len(row) for row in rows)
    padding = 18
    cell_width = int((WIDTH * 0.94) / columns)
    line_height = 38
    row_heights: list[int] = []
    wrapped: list[list[list[str]]] = []
    for row in rows:
        cell_lines: list[list[str]] = []
        max_lines = 1
        for cell in row:
            lines = _wrap_text(draw, cell, font, cell_width - 2 * padding)
            cell_lines.append(lines)
            max_lines = max(max_lines, len(lines))
        wrapped.append(cell_lines)
        row_heights.append(max_lines * line_height + 2 * padding)

    total_height = sum(row_heights)
    scale = min(1.0, (HEIGHT * 0.94) / total_height)
    if scale < 1.0:
        font = _font(max(14, int(28 * scale)))
        line_height = int(line_height * scale)
        padding = int(padding * scale)

    x0 = (WIDTH - cell_width * columns) // 2
    y = (HEIGHT - sum(row_heights)) // 2
    for row_index, row in enumerate(wrapped):
        x = x0
        for col_index in range(columns):
            lines = row[col_index] if col_index < len(row) else []
            draw.rectangle(
                [x, y, x + cell_width, y + row_heights[row_index]],
                outline=(160, 160, 160),
                width=1,
            )
            text_y = y + padding
            for line in lines:
                draw.text((x + padding, text_y), line, font=font, fill=(20, 20, 20))
                text_y += line_height
            x += cell_width
        y += row_heights[row_index]
    canvas.save(out_path, "PNG")
    return out_path


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            while draw.textlength(word, font=font) > max_width and len(word) > 1:
                cut = len(word) // 2
                lines.append(word[:cut])
                word = word[cut:]
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _render_blank(out_path: Path) -> Path:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (248, 246, 242))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([80, 80, WIDTH - 80, HEIGHT - 80], outline=(226, 222, 214), width=2)
    canvas.save(out_path, "PNG")
    return out_path


def _ellipsize(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    max_width: int,
) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    # Prefer a middle ellipsis: keep the host at the start and the file name
    # at the end, which is more recognisable than a truncated tail.
    for keep in range(len(text) - 1, 0, -1):
        head = keep * 3 // 5
        tail = keep - head
        candidate = f"{text[:head]}…{text[-tail:]}"
        if draw.textlength(candidate, font=font) <= max_width:
            return candidate
    return "…"


def _render_content(
    preview: LinkPreview,
    url: str,
    out_path: Path,
) -> Path:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), CONTENT_BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    footer_top = HEIGHT - CONTENT_FOOTER_H
    draw.line([(0, footer_top), (WIDTH, footer_top)], fill=CONTENT_RULE, width=1)

    image = Image.open(preview.image_path)
    image.load()
    image = _flatten(image)
    max_width = WIDTH - 2 * CONTENT_MARGIN
    max_height = footer_top - 2 * CONTENT_MARGIN
    image = _fit(image, max_width, max_height, upscale=False)
    x = (WIDTH - image.width) // 2
    y = CONTENT_MARGIN + (max_height - image.height) // 2
    canvas.paste(image, (x, y))
    draw.rectangle(
        [x - 1, y - 1, x + image.width, y + image.height],
        outline=(44, 48, 56),
        width=1,
    )

    card = CONTENT_QR_SIZE + 2 * CONTENT_QR_PAD
    card_x = WIDTH - CONTENT_MARGIN - card
    card_y = footer_top + (CONTENT_FOOTER_H - card) // 2
    draw.rounded_rectangle(
        [card_x, card_y, card_x + card, card_y + card],
        radius=14,
        fill=(255, 255, 255),
    )
    qr_image = make_qr_image(url, CONTENT_QR_SIZE)
    canvas.paste(qr_image, (card_x + CONTENT_QR_PAD, card_y + CONTENT_QR_PAD))

    text_x = CONTENT_MARGIN
    text_width = card_x - CONTENT_MARGIN - 24
    url_font = _font(28)
    compact = compact_url(url, 140)
    url_text = _ellipsize(draw, compact, url_font, text_width)
    status = preview.status
    if status:
        draw.text(
            (text_x, footer_top + 40),
            url_text,
            font=url_font,
            fill=CONTENT_TEXT,
        )
        draw.text(
            (text_x, footer_top + 84),
            status,
            font=_font(22),
            fill=CONTENT_MUTED,
        )
    else:
        draw.text(
            (text_x, footer_top + (CONTENT_FOOTER_H - 32) // 2),
            url_text,
            font=url_font,
            fill=CONTENT_TEXT,
        )

    canvas.save(out_path, "PNG")
    return out_path


def prepare_frames(
    book: Book,
    plans: list[ChapterPlan],
    work_dir: str | Path,
) -> dict[int, str]:
    frames_dir = Path(work_dir) / "frames"
    # Frame indices shift when the plan changes. Rebuild the directory so stale
    # files from an earlier plan can never be picked up.
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[int, str] = {}
    for plan in plans:
        for index, frame in enumerate(plan.frames):
            out_path = frames_dir / f"ch{plan.chapter.index:02d}_{index:03d}.png"
            if frame.kind == "qr":
                make_qr_frame(frame.url or "", out_path, caption=frame.url or "")
            elif frame.kind == "content":
                if frame.preview is None:
                    raise ValueError(f"Frame {index} has no content preview")
                _render_content(
                    frame.preview,
                    frame.url or frame.preview.url,
                    out_path,
                )
            elif frame.kind == "html_table":
                _render_html_table(frame.rows, out_path)
            elif frame.kind == "blank":
                _render_blank(out_path)
            else:
                if frame.source is None:
                    raise ValueError(f"Frame {index} has no image source")
                _prepare_figure(
                    book.read(frame.source),
                    out_path,
                    table=frame.kind == "table",
                )
            mapping[id(frame)] = str(out_path)
    return mapping


def _collect_entries(
    plans: list[ChapterPlan],
    mapping: dict[int, str],
) -> list[tuple[str, float, float]]:
    entries: list[tuple[str, float, float]] = []
    for plan in plans:
        for frame in plan.frames:
            duration = frame.end - frame.start
            if duration <= 0.04:
                continue
            entries.append((mapping[id(frame)], frame.start, frame.end))
    entries.sort(key=lambda item: item[1])

    # Close gaps so the screen is never blank, including the pause between
    # chapters.  The last frame is held until the end of the book.
    closed: list[tuple[str, float, float]] = []
    for entry in entries:
        if closed and entry[1] > closed[-1][2] + 0.001:
            previous = closed[-1]
            closed[-1] = (previous[0], previous[1], entry[1])
        closed.append(entry)
    if closed and plans:
        last = closed[-1]
        end = plans[-1].end
        if last[2] < end:
            closed[-1] = (last[0], last[1], end)
    return closed


def _write_metadata(
    path: Path,
    *,
    title: str,
    author: str,
    chapters: list[tuple[str, float, float]],
    comment: str,
) -> None:
    lines = [
        ";FFMETADATA1",
        f"title={title}",
        f"artist={author}",
        f"album={title}",
        f"comment={comment}",
        "genre=Audiobook",
    ]
    for chapter_title, start, end in chapters:
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={int(round(start * 1000))}",
            f"END={int(round(end * 1000))}",
            f"title={chapter_title}",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render(
    plans: list[ChapterPlan],
    mapping: dict[int, str],
    audio_path: str | Path,
    out_path: str | Path,
    *,
    book_title: str,
    author: str,
    chapter_titles: list[str],
    work_dir: str | Path,
    crf: int = 20,
    preset: str = "medium",
    encoder: str = "auto",
) -> Path:
    work = Path(work_dir)
    encoder = resolve_encoder(encoder)
    entries = _collect_entries(plans, mapping)
    if not entries:
        raise ValueError("No frames to render")

    # Human-readable trace of the frame plan (not used by ffmpeg).
    debug_lines: list[str] = []
    for image, start, end in entries:
        debug_lines.append(f"# {start:.3f} -> {end:.3f}")
        debug_lines.append(f"file '{Path(image).resolve()}'")
        debug_lines.append(f"duration {max(0.04, end - start):.3f}")
    (work / "frames.txt").write_text(
        "\n".join(debug_lines) + "\n", encoding="utf-8"
    )

    metadata_path = work / "metadata.txt"
    chapters = []
    for plan, title in zip(plans, chapter_titles):
        chapters.append((title, plan.start, plan.end))
    _write_metadata(
        metadata_path,
        title=book_title,
        author=author,
        chapters=chapters,
        comment="Озвучка book2video, TeraTTSv2",
    )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import soundfile as sf

    audio_duration = sf.info(str(audio_path)).duration

    if len(entries) <= MAX_RENDER_INPUTS:
        _render_single(
            entries,
            audio_path=audio_path,
            metadata_path=metadata_path,
            out_path=out_path,
            audio_duration=audio_duration,
            crf=crf,
            preset=preset,
            encoder=encoder,
        )
    else:
        _render_chunked(
            entries,
            audio_path=audio_path,
            metadata_path=metadata_path,
            out_path=out_path,
            audio_duration=audio_duration,
            work=work,
            crf=crf,
            preset=preset,
            encoder=encoder,
        )
    return out_path


def _frame_inputs(entries: list[tuple[str, float, float]]) -> list[str]:
    # The concat demuxer ignores per-image durations for still images in
    # ffmpeg 7.  Loop each frame for its exact duration and join the streams
    # with the concat filter instead: this keeps cuts frame-accurate.
    inputs: list[str] = []
    for image, start, end in entries:
        duration = max(0.04, end - start)
        inputs += [
            "-framerate",
            "30",
            "-loop",
            "1",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(Path(image).resolve()),
        ]
    return inputs


def _concat_filter(count: int) -> list[str]:
    if count == 1:
        return ["-map", "0:v:0"]
    chains = "".join(f"[{index}:v]" for index in range(count))
    return [
        "-filter_complex",
        f"{chains}concat=n={count}:v=1:a=0[v]",
        "-map",
        "[v]",
    ]


def _render_single(
    entries: list[tuple[str, float, float]],
    *,
    audio_path: str | Path,
    metadata_path: Path,
    out_path: Path,
    audio_duration: float,
    crf: int,
    preset: str,
    encoder: str,
) -> None:
    inputs = _frame_inputs(entries)
    audio_index = len(entries)
    metadata_index = audio_index + 1
    inputs += ["-i", str(audio_path), "-i", str(metadata_path)]

    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        *inputs,
        *_concat_filter(len(entries)),
        "-map",
        f"{audio_index}:a:0",
        "-map_metadata",
        str(metadata_index),
        *encoder_args(encoder, crf, preset),
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "44100",
        "-ac",
        "1",
        "-movflags",
        "+faststart",
        "-t",
        f"{audio_duration:.3f}",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(command, check=True)


def _part_is_complete(path: Path, duration: float) -> bool:
    """Return True when ``path`` is a finished part of the expected length.

    A killed ffmpeg leaves a truncated MP4 without a usable ``moov`` atom, so
    ffprobe fails or reports a shorter duration.  Reuse is deliberately strict:
    the duration must match within 100 ms.
    """
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    try:
        actual = float(result.stdout.strip())
    except ValueError:
        return False
    return abs(actual - duration) <= 0.1


def _chunk_signature(
    chunk: list[tuple[str, float, float]],
    encoder: str,
    crf: int,
    preset: str,
) -> str:
    """Identify the exact inputs and settings that produce one rendered part."""
    payload = [
        [str(Path(image).resolve()), f"{max(0.04, end - start):.3f}"]
        for image, start, end in chunk
    ]
    payload.append([encoder, crf, preset])
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _render_chunked(
    entries: list[tuple[str, float, float]],
    *,
    audio_path: str | Path,
    metadata_path: Path,
    out_path: Path,
    audio_duration: float,
    work: Path,
    crf: int,
    preset: str,
    encoder: str,
) -> None:
    parts_dir = work / "render-parts"
    chunks = [
        entries[offset : offset + MAX_RENDER_INPUTS]
        for offset in range(0, len(entries), MAX_RENDER_INPUTS)
    ]
    signatures = [
        _chunk_signature(chunk, encoder, crf, preset) for chunk in chunks
    ]

    # Resume a previous run only when every chunk describes the same frames and
    # encoder settings.  Otherwise stale parts could be spliced into a
    # different plan, so start clean.
    reuse_parts = False
    if parts_dir.exists():
        try:
            reuse_parts = json.loads(
                (parts_dir / "manifest.json").read_text(encoding="utf-8")
            ) == signatures
        except (OSError, ValueError):
            reuse_parts = False
        if not reuse_parts:
            shutil.rmtree(parts_dir)
    parts_dir.mkdir(parents=True, exist_ok=True)
    (parts_dir / "manifest.json").write_text(
        json.dumps(signatures), encoding="utf-8"
    )

    parts: list[Path] = []
    for index, chunk in enumerate(chunks):
        duration = sum(max(0.04, end - start) for _, start, end in chunk)
        part = parts_dir / f"part_{index:03d}.mp4"
        if reuse_parts and _part_is_complete(part, duration):
            parts.append(part)
            continue
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            *_frame_inputs(chunk),
            *_concat_filter(len(chunk)),
            "-an",
            *encoder_args(encoder, crf, preset),
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-t",
            f"{duration:.3f}",
            str(part),
        ]
        subprocess.run(command, check=True)
        parts.append(part)

    concat_list = parts_dir / "parts.txt"
    concat_list.write_text(
        "".join(f"file '{part.resolve()}'\n" for part in parts),
        encoding="utf-8",
    )
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-i",
        str(audio_path),
        "-i",
        str(metadata_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-map_metadata",
        "2",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "44100",
        "-ac",
        "1",
        "-movflags",
        "+faststart",
        "-t",
        f"{audio_duration:.3f}",
        "-shortest",
        str(out_path),
    ]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError:
        # Keep the encoded parts: the expensive pass can be inspected or
        # reused while diagnosing the mux step.
        raise
    shutil.rmtree(parts_dir)


def write_timeline(
    plans: list[ChapterPlan],
    path: str | Path,
    mapping: dict[int, str],
) -> None:
    data = []
    for plan in plans:
        data.append(
            {
                "chapter": plan.chapter.index,
                "title": plan.chapter.title,
                "start": plan.start,
                "end": plan.end,
                "segments": [
                    {
                        "kind": s.kind,
                        "voice": s.voice,
                        "start": s.start,
                        "end": s.end,
                        "text": s.text,
                    }
                    for s in plan.segments
                ],
                "frames": [
                    {
                        "kind": f.kind,
                        "start": f.start,
                        "end": f.end,
                        "caption": f.caption,
                        "source": f.source,
                        "url": f.url,
                        "preview": f.preview.as_dict() if f.preview else None,
                        "file": mapping.get(id(f)),
                    }
                    for f in plan.frames
                ],
            }
        )
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
