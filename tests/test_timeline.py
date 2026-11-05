"""Narration planning and frame scheduling.

The whole illustration policy is pure data in, data out: no ffmpeg, no model,
no files.  These tests pin the rules that are easy to break during a refactor.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from book2video.epub import Block, Chapter, Link
from book2video.links import LinkPreview
from book2video.timeline import (
    FRAME_MIN_HOLD_SEC,
    ChapterPlan,
    Frame,
    Segment,
    assign_audio_times,
    carry_frames,
    plan_chapter,
)


def _chapter(index: int, blocks: list[Block]) -> Chapter:
    return Chapter(index=index, href=f"ch{index}.xhtml", title=f"Глава {index}", blocks=blocks)


def _set_durations(plan, seconds: float = 2.0) -> None:
    for segment in plan.segments:
        segment.duration = seconds


def _preview(
    kind: str = "document",
    pages: int = 3,
    *,
    full: bool = False,
    title: str = "Итоги встречи",
) -> LinkPreview:
    return LinkPreview(
        url="https://example.com/report",
        kind=kind,
        title=title,
        page_count=pages,
        full=full,
        image_path=Path("preview.png"),
    )


class FrameSchedulingTests(unittest.TestCase):
    def test_first_frame_starts_with_the_chapter(self) -> None:
        chapter = _chapter(
            1,
            [
                Block("heading", "Глава 1. Начало"),
                Block("paragraph", "Длинный первый абзац."),
                Block("image", caption="рисунок 1. Схема", image="img1.png"),
                Block("paragraph", "Текст после рисунка."),
            ],
        )
        plan = plan_chapter(chapter, "ru_m5", "ru_f1")
        _set_durations(plan)
        assign_audio_times(plan, 10.0)

        self.assertEqual(plan.frames[0].start, 10.0)
        self.assertGreater(plan.frames[0].end, plan.frames[0].start)

    def test_frames_cover_the_chapter_without_gaps(self) -> None:
        chapter = _chapter(
            1,
            [
                Block("heading", "Глава 1. Начало"),
                Block("paragraph", "Первый абзац."),
                Block("image", caption="рисунок 1. Схема", image="img1.png"),
                Block("paragraph", "Второй абзац."),
                Block("image", caption="рисунок 2. Схема", image="img2.png"),
                Block("paragraph", "Третий абзац."),
            ],
        )
        plan = plan_chapter(chapter, "ru_m5", "ru_f1")
        _set_durations(plan, 10.0)
        assign_audio_times(plan, 0.0)

        self.assertEqual(plan.frames[0].start, plan.start)
        self.assertEqual(plan.frames[-1].end, plan.end)
        for previous, current in zip(plan.frames, plan.frames[1:]):
            self.assertAlmostEqual(previous.end, current.start, places=6)

    def test_cut_uses_the_midpoint_when_every_frame_has_room(self) -> None:
        chapter = _chapter(
            1,
            [
                Block("heading", "Глава 1. Начало"),
                Block("paragraph", "Первый абзац."),
                Block("image", caption="рисунок 1. Схема", image="img1.png"),
                Block("paragraph", "Второй абзац."),
                Block("image", caption="рисунок 2. Схема", image="img2.png"),
                Block("paragraph", "Третий абзац."),
            ],
        )
        plan = plan_chapter(chapter, "ru_m5", "ru_f1")
        _set_durations(plan, 20.0)
        assign_audio_times(plan, 0.0)

        first, second = plan.frames
        expected = (first.anchor + second.anchor) / 2.0
        self.assertAlmostEqual(second.start, expected, places=3)
        self.assertAlmostEqual(first.end, second.start, places=3)
        self.assertAlmostEqual(plan.frames[-1].end, plan.end, places=3)

    def test_every_frame_gets_the_minimum_when_the_chapter_has_room(self) -> None:
        chapter = _chapter(
            1,
            [
                Block("heading", "Глава 1. Начало"),
                Block("paragraph", "Первый абзац."),
                Block("image", caption="рисунок 1. Схема", image="img1.png"),
                Block("paragraph", "Второй абзац."),
                Block("image", caption="рисунок 2. Схема", image="img2.png"),
                Block("paragraph", "Третий абзац."),
                Block("image", caption="рисунок 3. Схема", image="img3.png"),
                Block("paragraph", "Четвёртый абзац."),
            ],
        )
        plan = plan_chapter(chapter, "ru_m5", "ru_f1", frame_hold=8.0)
        _set_durations(plan, 12.0)
        assign_audio_times(plan, 0.0)

        self.assertGreaterEqual(plan.end - plan.start, 8.0 * len(plan.frames))
        for frame in plan.frames:
            self.assertGreaterEqual(frame.end - frame.start, 8.0 - 1e-6)

    def test_short_chapter_shortens_all_frames_equally(self) -> None:
        chapter = _chapter(
            1,
            [
                Block("heading", "Глава 1. Начало"),
                Block("image", caption="рисунок 1. Схема", image="img1.png"),
                Block("image", caption="рисунок 2. Схема", image="img2.png"),
                Block("image", caption="рисунок 3. Схема", image="img3.png"),
            ],
        )
        plan = plan_chapter(chapter, "ru_m5", "ru_f1", frame_hold=8.0)
        _set_durations(plan, 1.0)
        assign_audio_times(plan, 0.0)

        self.assertLess(plan.end - plan.start, 8.0 * len(plan.frames))
        expected = (plan.end - plan.start) / len(plan.frames)
        for frame in plan.frames:
            self.assertAlmostEqual(frame.end - frame.start, expected, places=6)

    def test_mention_keeps_half_a_hold_after_it_when_possible(self) -> None:
        plan = ChapterPlan(
            chapter=_chapter(1, []),
            segments=[
                Segment("a", "ru_m5", "paragraph", 0, duration=10.0),
                Segment("b", "ru_m5", "paragraph", 1, duration=4.0),
                Segment("c", "ru_m5", "paragraph", 2, duration=26.0),
            ],
            frames=[
                Frame(kind="figure", anchor_after_segment=0, min_hold=8.0),
                Frame(kind="figure", anchor_after_segment=1, min_hold=8.0),
            ],
            frame_hold=8.0,
        )
        assign_audio_times(plan, 0.0)

        first, second = plan.frames
        self.assertGreaterEqual(first.end - first.anchor, 4.0 - 1e-6)
        self.assertLessEqual(first.anchor, first.end)
        self.assertLessEqual(second.anchor, second.end)
        self.assertGreaterEqual(second.end - second.start, 8.0 - 1e-6)

    def test_qr_frame_is_a_normal_frame(self) -> None:
        chapter = _chapter(
            1,
            [
                Block(
                    "paragraph",
                    "Подробности по ссылке.",
                    links=[Link("здесь", "https://example.com/report")],
                )
            ],
        )
        plan = plan_chapter(chapter, "ru_m5", "ru_f1")
        self.assertEqual(plan.frames[0].kind, "qr")
        self.assertEqual(plan.frames[0].min_hold, FRAME_MIN_HOLD_SEC)

        _set_durations(plan, 20.0)
        assign_audio_times(plan, 0.0)

        duration = plan.frames[0].end - plan.frames[0].start
        self.assertGreater(duration, 15.0)

    def test_table_uses_the_general_frame_hold(self) -> None:
        chapter = _chapter(
            1,
            [
                Block("heading", "Глава 1. Начало"),
                Block("table", caption="таблица 1. Данные", image="table.png"),
                Block("paragraph", "Текст после таблицы."),
            ],
        )
        plan = plan_chapter(chapter, "ru_m5", "ru_f1", frame_hold=8.0)
        _set_durations(plan, 1.0)
        assign_audio_times(plan, 0.0)

        self.assertEqual(plan.frames[0].min_hold, 8.0)
        # The chapter is shorter than the minimum, so all frames share it
        # equally instead of extending the audio.
        self.assertAlmostEqual(plan.frames[0].end - plan.frames[0].start, plan.end - plan.start)


class LinkPlanningTests(unittest.TestCase):
    def test_known_link_becomes_a_content_frame_with_an_annotation(self) -> None:
        url = "https://example.com/report"
        chapter = _chapter(
            1,
            [
                Block(
                    "paragraph",
                    "Подробности в документе.",
                    links=[Link("Итоги встречи", url)],
                )
            ],
        )
        preview = _preview()
        plan = plan_chapter(
            chapter,
            "ru_m5",
            "ru_f1",
            resolutions={url: preview},
            annotation_voice="ru_f1",
        )

        self.assertEqual(plan.frames[0].kind, "content")
        self.assertIs(plan.frames[0].preview, preview)
        kinds = [segment.kind for segment in plan.segments]
        self.assertEqual(kinds, ["paragraph", "link", "annotation"])
        annotation = plan.segments[-1]
        self.assertEqual(annotation.voice, "ru_f1")
        self.assertIn("страница 1 из 3", annotation.text)
        self.assertIn("остальное по ссылке", annotation.text)

    def test_unknown_link_stays_a_qr_frame(self) -> None:
        chapter = _chapter(
            1,
            [
                Block(
                    "paragraph",
                    "Подробности в документе.",
                    links=[Link("Итоги встречи", "https://example.com/report")],
                )
            ],
        )
        plan = plan_chapter(chapter, "ru_m5", "ru_f1", resolutions={})
        self.assertEqual(plan.frames[0].kind, "qr")
        self.assertFalse(any(segment.kind == "annotation" for segment in plan.segments))

    def test_link_url_is_read_in_the_main_voice_inside_a_sidebar(self) -> None:
        url = "https://example.com/report"
        chapter = _chapter(
            1,
            [
                Block(
                    "sidebar",
                    "Врезка со ссылкой.",
                    box=True,
                    links=[Link("Итоги встречи", url)],
                )
            ],
        )
        plan = plan_chapter(
            chapter,
            "ru_m5",
            "ru_f1",
            resolutions={url: _preview()},
        )
        voices = {segment.kind: segment.voice for segment in plan.segments}
        self.assertEqual(voices["sidebar"], "ru_f1")
        self.assertEqual(voices["link"], "ru_m5")
        self.assertEqual(voices["annotation"], "ru_f1")


class CarryFrameTests(unittest.TestCase):
    def test_chapter_without_images_reuses_the_previous_frame(self) -> None:
        illustrated = _chapter(
            1,
            [
                Block("heading", "Глава 1. Начало"),
                Block("image", caption="рисунок 1. Схема", image="img1.png"),
            ],
        )
        plain = _chapter(2, [Block("heading", "Глава 2. Текст")])

        plans = [
            plan_chapter(illustrated, "ru_m5", "ru_f1"),
            plan_chapter(plain, "ru_m5", "ru_f1"),
        ]
        carry_frames(plans)

        self.assertEqual(len(plans[1].frames), 1)
        self.assertEqual(plans[1].frames[0].source, "img1.png")

    def test_book_starts_with_a_neutral_frame_before_the_first_image(self) -> None:
        plain = _chapter(1, [Block("heading", "Предисловие")])
        illustrated = _chapter(
            2,
            [
                Block("heading", "Глава 1. Начало"),
                Block("image", caption="рисунок 1. Схема", image="img1.png"),
            ],
        )

        plans = [
            plan_chapter(plain, "ru_m5", "ru_f1"),
            plan_chapter(illustrated, "ru_m5", "ru_f1"),
        ]
        carry_frames(plans)

        self.assertEqual(plans[0].frames[0].kind, "blank")

    def test_carried_content_frame_keeps_its_preview(self) -> None:
        preview = _preview()
        illustrated = _chapter(
            1,
            [
                Block(
                    "paragraph",
                    "Документ.",
                    links=[Link("Итоги", preview.url)],
                )
            ],
        )
        plain = _chapter(2, [Block("heading", "Глава 2. Текст")])
        plans = [
            plan_chapter(
                illustrated,
                "ru_m5",
                "ru_f1",
                resolutions={preview.url: preview},
            ),
            plan_chapter(plain, "ru_m5", "ru_f1"),
        ]
        carry_frames(plans)
        self.assertEqual(plans[1].frames[0].kind, "content")
        self.assertIs(plans[1].frames[0].preview, preview)


if __name__ == "__main__":
    unittest.main()
