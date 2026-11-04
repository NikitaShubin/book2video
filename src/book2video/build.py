"""End-to-end build: EPUB -> narration plan -> audio -> frames -> MP4."""

from __future__ import annotations

from pathlib import Path

from .audio import assemble_audio, synthesize_plans
from .epub import Book, Chapter, load_book, select_chapter
from .render import prepare_frames, render, write_timeline
from .timeline import (
    CHAPTER_GAP_SEC,
    ChapterPlan,
    assign_audio_times,
    carry_frames,
    plan_chapters,
)
from .tts.tera import TeraBackend
from .voices import DEFAULT_MAIN_VOICE, get_voice, opposite_gender


def _select_chapters(
    book: Book,
    *,
    chapter: str | int | None,
    all_chapters: bool,
) -> list[Chapter]:
    if all_chapters:
        if not book.chapters:
            raise ValueError("No content chapters found")
        return list(book.chapters)
    return [select_chapter(book, chapter)]


def build(
    epub_path: str | Path,
    out_path: str | Path,
    *,
    chapter: str | int | None = None,
    all_chapters: bool = False,
    voice: str = DEFAULT_MAIN_VOICE,
    sidebar_voice: str | None = None,
    work_dir: str | Path | None = None,
    provider: str = "CPUExecutionProvider",
    threads: int | None = None,
    table_min_hold: float = 8.0,
    speed: float = 1.2,
    crf: int = 20,
    preset: str = "medium",
    backend=None,
    log=print,
) -> Path:
    get_voice(voice)
    sidebar_voice = sidebar_voice or opposite_gender(voice)
    get_voice(sidebar_voice)
    if speed <= 0:
        raise ValueError("speed must be positive")

    epub_path = Path(epub_path)
    out_path = Path(out_path)
    work = Path(work_dir or (out_path.parent / f".{out_path.stem}_work"))
    work.mkdir(parents=True, exist_ok=True)

    book = load_book(epub_path)
    try:
        chapters = _select_chapters(book, chapter=chapter, all_chapters=all_chapters)
        log(
            f"Book: {book.title} — {book.author}\n"
            f"Chapters: {', '.join(str(c.number or c.title) for c in chapters)}"
        )

        plans: list[ChapterPlan] = plan_chapters(
            chapters,
            voice,
            sidebar_voice,
            table_min_hold=table_min_hold,
        )
        carry_frames(plans)
        total_segments = sum(len(p.segments) for p in plans)
        total_frames = sum(len(p.frames) for p in plans)
        log(f"Plan: {total_segments} segments, {total_frames} frames")

        # The backend is an adapter at the synthesis seam.  Production passes
        # Tera; tests pass a fake that writes tones, so the whole pipeline can
        # be exercised without the model.
        backend = backend or TeraBackend(provider=provider, threads=threads)
        synthesize_plans(
            backend,
            plans,
            work,
            speed=speed,
            log=log,
        )

        start = 0.0
        for index, plan in enumerate(plans):
            if index:
                start = plans[index - 1].end + CHAPTER_GAP_SEC
            assign_audio_times(plan, start)
        total_duration = plans[-1].end if plans else 0.0
        log(f"Audio duration: {total_duration/60:.1f} min")

        audio_path = work / "narration.wav"
        duration = assemble_audio(plans, audio_path)
        log(f"WAV duration: {duration/60:.1f} min -> {audio_path}")

        mapping = prepare_frames(book, plans, work)
        log(f"Frames ready: {len(mapping)}")

        write_timeline(plans, work / "timeline.json", mapping)
        result = render(
            plans,
            mapping,
            audio_path,
            out_path,
            book_title=book.title,
            author=book.author,
            chapter_titles=[c.title for c in chapters],
            work_dir=work,
            crf=crf,
            preset=preset,
        )
        log(f"Video: {result}")
        return result
    finally:
        book.close()
