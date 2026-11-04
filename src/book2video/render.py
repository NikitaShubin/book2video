"""Frame preparation and ffmpeg rendering."""

from __future__ import annotations

import json
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .epub import Book
from .images.qr import make_qr_frame
from .timeline import ChapterPlan

WIDTH = 1920
HEIGHT = 1080
BACKGROUND = (255, 255, 255)
FIGURE_MARGIN = 0.94
TABLE_MARGIN = 0.985

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


def _fit(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    scale = min(max_width / image.width, max_height / image.height)
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
) -> Path:
    work = Path(work_dir)
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
    audio_index = len(entries)
    metadata_index = audio_index + 1
    inputs += ["-i", str(audio_path), "-i", str(metadata_path)]

    if len(entries) == 1:
        filter_args = ["-map", "0:v:0"]
    else:
        chains = "".join(f"[{index}:v]" for index in range(len(entries)))
        filter_args = [
            "-filter_complex",
            f"{chains}concat=n={len(entries)}:v=1:a=0[v]",
            "-map",
            "[v]",
        ]

    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        *inputs,
        *filter_args,
        "-map",
        f"{audio_index}:a:0",
        "-map_metadata",
        str(metadata_index),
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
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
    return out_path


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
                        "file": mapping.get(id(f)),
                    }
                    for f in plan.frames
                ],
            }
        )
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
