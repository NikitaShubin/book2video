"""Narration plan and illustration timeline.

The unit of narration is a :class:`Segment` (a heading, paragraph, sidebar,
caption or link sentence).  Every segment is synthesised separately, so its
measured duration gives an exact start time in the final audio.

Frames (illustrations, tables, QR codes) are anchored to the segment where
they are introduced.  Every frame, including a QR code, cuts in at the
midpoint between its own anchor and the previous anchor (or at the chapter
start for the first one) and stays until the next frame's cut.  A QR frame is
therefore a normal image with its own area of influence; it has no fixed
maximum duration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .epub import Chapter
from .normalize import link_narration, needs_qr, normalize_for_speech

CHAPTER_GAP_SEC = 1.5
TABLE_MIN_HOLD_SEC = 8.0
QR_MIN_HOLD_SEC = 4.0


@dataclass
class Segment:
    text: str
    voice: str
    kind: str
    block_index: int
    min_hold: float = 0.0
    audio_path: str | None = None
    duration: float = 0.0
    start: float = 0.0
    end: float = 0.0
    hold_after: float = 0.0
    pause_before: float = 0.0


@dataclass
class Frame:
    kind: str  # figure | table | qr | html_table
    caption: str
    source: str | None = None
    url: str | None = None
    rows: list[list[str]] = field(default_factory=list)
    anchor_segment: int | None = None
    anchor_after_segment: int | None = None
    min_hold: float = 0.0
    anchor: float = 0.0
    start: float = 0.0
    end: float = 0.0


@dataclass
class ChapterPlan:
    chapter: Chapter
    segments: list[Segment]
    frames: list[Frame]
    start: float = 0.0
    end: float = 0.0


def _pause_before(current: Segment, previous: Segment | None) -> float:
    if previous is None:
        return 0.7
    if current.kind == "heading":
        return 0.9
    if previous.kind == "heading":
        return 0.55
    if current.kind in {"sidebar", "caption", "link"}:
        return 0.5
    if previous.kind in {"sidebar", "caption", "link"}:
        return 0.5
    return 0.35


def plan_chapter(
    chapter: Chapter,
    main_voice: str,
    sidebar_voice: str,
    *,
    table_min_hold: float = TABLE_MIN_HOLD_SEC,
) -> ChapterPlan:
    segments: list[Segment] = []
    frames: list[Frame] = []

    def add_segment(
        text: str,
        voice: str,
        kind: str,
        block_index: int,
        *,
        min_hold: float = 0.0,
    ) -> int:
        segment = Segment(
            text=text,
            voice=voice,
            kind=kind,
            block_index=block_index,
            min_hold=min_hold,
        )
        segments.append(segment)
        return len(segments) - 1

    def add_frame(frame: Frame) -> int:
        frames.append(frame)
        return len(frames) - 1

    for block_index, block in enumerate(chapter.blocks):
        if block.kind == "footnote":
            continue

        voice = sidebar_voice if block.box else main_voice

        if block.kind in {"heading", "paragraph", "sidebar", "caption"}:
            text = normalize_for_speech(block.text)
            if text:
                add_segment(text, voice, block.kind, block_index)
            for link in block.links:
                if not needs_qr(link.text, link.href):
                    continue
                segment_index = add_segment(
                    link_narration(link.href),
                    voice,
                    "link",
                    block_index,
                )
                add_frame(
                    Frame(
                        kind="qr",
                        caption=link.href,
                        url=link.href,
                        anchor_segment=segment_index,
                        min_hold=QR_MIN_HOLD_SEC,
                    )
                )
            continue

        if block.kind in {"image", "table"}:
            caption = normalize_for_speech(block.caption)
            if caption:
                segment_index = add_segment(
                    caption,
                    main_voice,
                    "caption",
                    block_index,
                    min_hold=table_min_hold if block.kind == "table" else 0.0,
                )
                add_frame(
                    Frame(
                        kind="table" if block.kind == "table" else "figure",
                        caption=block.caption,
                        source=block.image,
                        anchor_segment=segment_index,
                        min_hold=table_min_hold if block.kind == "table" else 0.0,
                    )
                )
            else:
                add_frame(
                    Frame(
                        kind="table" if block.kind == "table" else "figure",
                        caption="",
                        source=block.image,
                        anchor_after_segment=len(segments) - 1,
                        min_hold=table_min_hold if block.kind == "table" else 0.0,
                    )
                )
            continue

        if block.kind == "html_table":
            rows = block.rows
            small = bool(rows) and len(rows) <= 8 and max(len(r) for r in rows) <= 4
            caption = normalize_for_speech(block.caption)
            segment_index: int | None = None
            if caption:
                segment_index = add_segment(
                    caption,
                    main_voice,
                    "caption",
                    block_index,
                    min_hold=table_min_hold,
                )
            if small:
                for row in rows:
                    text = normalize_for_speech("; ".join(row))
                    if text:
                        add_segment(text, main_voice, "paragraph", block_index)
            add_frame(
                Frame(
                    kind="html_table",
                    caption=block.caption,
                    rows=rows,
                    anchor_segment=segment_index,
                    anchor_after_segment=None if segment_index is not None else len(segments) - 1,
                    min_hold=table_min_hold,
                )
            )
            continue

    for index, segment in enumerate(segments):
        segment.pause_before = _pause_before(segment, segments[index - 1] if index else None)

    return ChapterPlan(chapter=chapter, segments=segments, frames=frames)


def assign_audio_times(plan: ChapterPlan, start: float) -> float:
    """Compute segment and frame times; return the chapter end time."""
    plan.start = start
    cursor = start
    for segment in plan.segments:
        segment.start = cursor + segment.pause_before
        segment.end = segment.start + segment.duration
        segment.hold_after = max(0.0, segment.min_hold - segment.duration)
        cursor = segment.end + segment.hold_after
    plan.end = cursor

    for frame in plan.frames:
        if frame.anchor_segment is not None:
            frame.anchor = plan.segments[frame.anchor_segment].start
        elif frame.anchor_after_segment is not None and frame.anchor_after_segment >= 0:
            frame.anchor = plan.segments[frame.anchor_after_segment].end
        else:
            frame.anchor = start

    _schedule_frames(plan)
    return plan.end


def _schedule_frames(plan: ChapterPlan) -> None:
    frames = plan.frames
    if not frames:
        return

    previous_anchor: dict[int, float] = {}
    cursor = plan.start
    for frame in frames:
        previous_anchor[id(frame)] = cursor
        cursor = frame.anchor

    for index, frame in enumerate(frames):
        if index == 0:
            frame.start = plan.start
        else:
            frame.start = max(
                plan.start,
                (previous_anchor[id(frame)] + frame.anchor) / 2.0,
            )

    frames.sort(key=lambda f: (f.start, f.anchor))

    # A run of images with no text between them shares one anchor. Spread the
    # run evenly until the next distinct anchor so every image is visible
    # instead of collapsing the whole run into a single frame.
    index = 0
    while index < len(frames):
        end = index + 1
        while (
            end < len(frames)
            and abs(frames[end].anchor - frames[index].anchor) < 0.001
        ):
            end += 1
        if end - index > 1:
            group_start = frames[index].start
            group_end = frames[end].start if end < len(frames) else plan.end
            if group_end <= group_start:
                group_end = min(plan.end, group_start + 1.5 * (end - index))
            span = max(0.0, group_end - group_start)
            count = end - index
            for offset in range(count):
                frames[index + offset].start = group_start + span * offset / count
        index = end

    # If the first frame is a QR code or a late illustration, keep a neutral
    # frame on screen from the chapter start so the video is never blank and
    # the concat timeline starts at zero.
    if frames[0].start > plan.start + 0.001:
        frames.insert(
            0,
            Frame(
                kind="blank",
                caption="",
                anchor=plan.start,
                start=plan.start,
                end=frames[0].start,
            ),
        )

    for index, frame in enumerate(frames):
        if index:
            previous = frames[index - 1]
            earliest = previous.start + max(previous.min_hold, 0.5)
            if frame.start < earliest:
                frame.start = earliest

    for index, frame in enumerate(frames):
        frame.end = frames[index + 1].start if index + 1 < len(frames) else plan.end
        if frame.end < frame.start:
            frame.end = frame.start

    last = frames[-1]
    if last.end < last.start + last.min_hold:
        plan.end = last.start + last.min_hold
        last.end = plan.end


def plan_chapters(
    chapters: list[Chapter],
    main_voice: str,
    sidebar_voice: str,
    *,
    table_min_hold: float = TABLE_MIN_HOLD_SEC,
) -> list[ChapterPlan]:
    return [
        plan_chapter(
            chapter,
            main_voice,
            sidebar_voice,
            table_min_hold=table_min_hold,
        )
        for chapter in chapters
    ]


def carry_frames(plans: list[ChapterPlan]) -> None:
    """Make every chapter covered by a frame.

    If a chapter has no illustration, the previous chapter's last frame stays
    on screen.  Before the first illustration of the book, a neutral paper
    frame is used instead of a black screen.
    """
    previous: Frame | None = None
    for plan in plans:
        if plan.frames:
            previous = plan.frames[-1]
            continue
        if previous is not None:
            clone = Frame(
                kind=previous.kind,
                caption=previous.caption,
                source=previous.source,
                url=previous.url,
                rows=previous.rows,
            )
            plan.frames.append(clone)
            previous = clone
        else:
            blank = Frame(kind="blank", caption="")
            plan.frames.append(blank)
            previous = blank
