"""Narration plan and illustration timeline.

The unit of narration is a :class:`Segment` (a heading, paragraph, sidebar,
caption, link sentence or link annotation).  Every segment is synthesised
separately, so its measured duration gives an exact start time in the final
audio.

Frames (illustrations, tables, content previews, QR codes) are anchored to the
segment where they are introduced.  Inside one chapter every frame gets a
minimum hold; when the narration is long enough, the surplus fills the frame's
natural area of influence (up to the midpoint between neighbouring anchors).
The scheduler prefers to keep each mention inside its frame and at least half a
hold after the mention starts.  When the chapter is shorter than
``frame_hold * frame_count``, all frames are shortened equally.  Frames never
cross a chapter boundary and the screen is never blank inside a chapter that
has a frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .epub import Chapter
from .links import LinkPreview
from .normalize import link_narration, normalize_for_speech

CHAPTER_GAP_SEC = 1.5
FRAME_MIN_HOLD_SEC = 8.0
MENTION_AFTER_SEC = FRAME_MIN_HOLD_SEC / 2.0


@dataclass
class Segment:
    text: str
    voice: str
    kind: str
    block_index: int
    audio_path: str | None = None
    duration: float = 0.0
    start: float = 0.0
    end: float = 0.0
    pause_before: float = 0.0


@dataclass
class Frame:
    kind: str  # figure | table | qr | content | html_table | blank
    caption: str = ""
    source: str | None = None
    url: str | None = None
    rows: list[list[str]] = field(default_factory=list)
    preview: LinkPreview | None = None
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
    frame_hold: float = FRAME_MIN_HOLD_SEC


def _pause_before(current: Segment, previous: Segment | None) -> float:
    if previous is None:
        return 0.7
    if current.kind == "heading":
        return 0.9
    if previous.kind == "heading":
        return 0.55
    side = {"sidebar", "caption", "link", "annotation"}
    if current.kind in side:
        return 0.5
    if previous.kind in side:
        return 0.5
    return 0.35


def plan_chapter(
    chapter: Chapter,
    main_voice: str,
    sidebar_voice: str,
    *,
    frame_hold: float = FRAME_MIN_HOLD_SEC,
    resolutions: Mapping[str, LinkPreview] | None = None,
    annotation_voice: str | None = None,
) -> ChapterPlan:
    if frame_hold <= 0:
        raise ValueError("frame_hold must be positive")
    segments: list[Segment] = []
    frames: list[Frame] = []
    resolutions = resolutions or {}
    annotation_voice = annotation_voice or sidebar_voice

    def add_segment(text: str, voice: str, kind: str, block_index: int) -> int:
        segment = Segment(text=text, voice=voice, kind=kind, block_index=block_index)
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
                url = link.href.strip()
                segment_index = add_segment(
                    link_narration(url),
                    main_voice,
                    "link",
                    block_index,
                )
                preview = resolutions.get(url)
                if preview is not None:
                    add_segment(
                        preview.annotation,
                        annotation_voice,
                        "annotation",
                        block_index,
                    )
                    add_frame(
                        Frame(
                            kind="content",
                            caption=preview.title,
                            url=url,
                            preview=preview,
                            anchor_segment=segment_index,
                            min_hold=frame_hold,
                        )
                    )
                else:
                    add_frame(
                        Frame(
                            kind="qr",
                            caption=url,
                            url=url,
                            anchor_segment=segment_index,
                            min_hold=frame_hold,
                        )
                    )
            continue

        if block.kind in {"image", "table"}:
            caption = normalize_for_speech(block.caption)
            kind = "table" if block.kind == "table" else "figure"
            if caption:
                segment_index = add_segment(
                    caption,
                    main_voice,
                    "caption",
                    block_index,
                )
                add_frame(
                    Frame(
                        kind=kind,
                        caption=block.caption,
                        source=block.image,
                        anchor_segment=segment_index,
                        min_hold=frame_hold,
                    )
                )
            else:
                add_frame(
                    Frame(
                        kind=kind,
                        caption="",
                        source=block.image,
                        anchor_after_segment=len(segments) - 1,
                        min_hold=frame_hold,
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
                    anchor_after_segment=None
                    if segment_index is not None
                    else len(segments) - 1,
                    min_hold=frame_hold,
                )
            )
            continue

    for index, segment in enumerate(segments):
        segment.pause_before = _pause_before(
            segment, segments[index - 1] if index else None
        )

    return ChapterPlan(
        chapter=chapter,
        segments=segments,
        frames=frames,
        frame_hold=frame_hold,
    )


def assign_audio_times(plan: ChapterPlan, start: float) -> float:
    """Compute segment and frame times; return the chapter end time."""
    plan.start = start
    cursor = start
    for segment in plan.segments:
        segment.start = cursor + segment.pause_before
        segment.end = segment.start + segment.duration
        cursor = segment.end
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


# ---------------------------------------------------------------------------
# Frame scheduling


def _anchor_groups(anchors: list[float]) -> list[tuple[int, int, float]]:
    """Return ``(first, end, anchor)`` runs; ``end`` is exclusive."""
    groups: list[tuple[int, int, float]] = []
    index = 0
    while index < len(anchors):
        end = index + 1
        while end < len(anchors) and abs(anchors[end] - anchors[index]) < 1e-6:
            end += 1
        groups.append((index, end, anchors[index]))
        index = end
    return groups


def _natural_boundaries(
    anchors: list[float],
    start: float,
    end: float,
) -> list[float]:
    """Midpoint cuts, with runs that share an anchor spread evenly."""
    count = len(anchors)
    boundaries = [start] * (count + 1)
    boundaries[count] = end
    groups = _anchor_groups(anchors)
    for group_index, (lo, hi, anchor) in enumerate(groups):
        previous = anchors[groups[group_index - 1][0]] if group_index else None
        following = (
            anchors[groups[group_index + 1][0]]
            if group_index + 1 < len(groups)
            else None
        )
        group_start = (previous + anchor) / 2.0 if previous is not None else start
        group_end = (anchor + following) / 2.0 if following is not None else end
        group_start = max(start, min(end, group_start))
        group_end = max(group_start, min(end, group_end))
        size = hi - lo
        boundaries[lo] = group_start
        for offset in range(1, size):
            boundaries[lo + offset] = group_start + (
                (group_end - group_start) * offset / size
            )
        boundaries[hi] = group_end

    for index in range(1, count + 1):
        boundaries[index] = max(boundaries[index], boundaries[index - 1])
    boundaries[0] = start
    boundaries[count] = end
    return boundaries


def _enforce_min_hold(
    boundaries: list[float],
    start: float,
    end: float,
    hold: float,
) -> None:
    """Project boundaries onto the feasible set ``duration_i >= hold``."""
    count = len(boundaries) - 1
    boundaries[0] = start
    boundaries[count] = end
    for index in range(1, count):
        boundaries[index] = max(boundaries[index], boundaries[index - 1] + hold)
    for index in range(count - 1, 0, -1):
        boundaries[index] = min(boundaries[index], boundaries[index + 1] - hold)
    boundaries[0] = start
    for index in range(1, count + 1):
        boundaries[index] = max(boundaries[index], boundaries[index - 1])


def _apply_mention_preference(
    anchors: list[float],
    boundaries: list[float],
    start: float,
    end: float,
    hold: float,
) -> bool:
    """Move group boundaries so a mention keeps half a hold after it.

    Only boundaries that already exist are moved; min holds are restored by
    the caller.  The move stops at the next/previous anchor so a neighbouring
    mention is not pushed out of its own frame.
    """
    count = len(anchors)
    wanted = hold / 2.0
    groups = _anchor_groups(anchors)
    changed = False
    for group_index, (lo, hi, anchor) in enumerate(groups):
        group_start = boundaries[lo]
        group_end = boundaries[hi]

        if group_end < anchor + wanted - 1e-6:
            deficit = anchor + wanted - group_end
            next_anchor = (
                anchors[groups[group_index + 1][0]]
                if group_index + 1 < len(groups)
                else end
            )
            latest = min(next_anchor, end - hold * (count - hi))
            new_end = min(latest, group_end + deficit)
            if new_end > group_end + 1e-6:
                boundaries[hi] = new_end
                changed = True

        if group_start > anchor + 1e-6:
            deficit = group_start - anchor
            previous_anchor = (
                anchors[groups[group_index - 1][0]]
                if group_index
                else start
            )
            earliest = start + hold * lo
            if group_index:
                earliest = max(earliest, previous_anchor + wanted)
            new_start = max(earliest, group_start - deficit)
            if new_start < group_start - 1e-6:
                boundaries[lo] = new_start
                changed = True
    return changed


def _schedule_frames(plan: ChapterPlan) -> None:
    frames = plan.frames
    if not frames:
        return

    anchors = [
        min(max(frame.anchor, plan.start), plan.end) for frame in frames
    ]
    order = sorted(range(len(frames)), key=lambda index: (anchors[index], index))
    frames[:] = [frames[index] for index in order]
    anchors = [anchors[index] for index in order]

    count = len(frames)
    duration = max(0.0, plan.end - plan.start)
    hold = plan.frame_hold
    if duration <= 0:
        for frame in frames:
            frame.start = frame.end = plan.start
        return

    if duration < hold * count - 1e-9:
        # The narration is too short for every frame to get its minimum.
        # Shorten all frames equally instead of privileging some of them.
        step = duration / count
        boundaries = [plan.start + step * index for index in range(count + 1)]
        boundaries[count] = plan.end
    else:
        boundaries = _natural_boundaries(anchors, plan.start, plan.end)
        _enforce_min_hold(boundaries, plan.start, plan.end, hold)
        for _ in range(4):
            if not _apply_mention_preference(
                anchors, boundaries, plan.start, plan.end, hold
            ):
                break
            _enforce_min_hold(boundaries, plan.start, plan.end, hold)

    for index, frame in enumerate(frames):
        frame.start = max(plan.start, min(boundaries[index], plan.end))
        frame.end = max(frame.start, min(boundaries[index + 1], plan.end))


def plan_chapters(
    chapters: list[Chapter],
    main_voice: str,
    sidebar_voice: str,
    *,
    frame_hold: float = FRAME_MIN_HOLD_SEC,
    resolutions: Mapping[str, LinkPreview] | None = None,
    annotation_voice: str | None = None,
) -> list[ChapterPlan]:
    return [
        plan_chapter(
            chapter,
            main_voice,
            sidebar_voice,
            frame_hold=frame_hold,
            resolutions=resolutions,
            annotation_voice=annotation_voice,
        )
        for chapter in chapters
    ]


def carry_frames(plans: list[ChapterPlan]) -> None:
    """Make every chapter covered by a frame.

    If a chapter has no frame, the previous chapter's last frame stays on
    screen.  Before the first illustration of the book, a neutral paper frame
    is used instead of a black screen.
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
                rows=list(previous.rows),
                preview=previous.preview,
                min_hold=plan.frame_hold,
            )
            plan.frames.append(clone)
            previous = clone
        else:
            blank = Frame(
                kind="blank",
                caption="",
                min_hold=plan.frame_hold,
            )
            plan.frames.append(blank)
            previous = blank
