"""Narration planning and illustration scheduling.

The whole illustration policy is pure data in, data out: no ffmpeg, no model,
no files.  These tests pin the rules that are easy to break during a refactor.
"""

from __future__ import annotations

import unittest

from book2video.epub import Block, Chapter, Link
from book2video.timeline import (
    QR_MIN_HOLD_SEC,
    assign_audio_times,
    carry_frames,
    plan_chapter,
)


def _chapter(index: int, blocks: list[Block]) -> Chapter:
    return Chapter(index=index, href=f"ch{index}.xhtml", title=f"Глава {index}", blocks=blocks)


def _set_durations(plan, seconds: float = 2.0) -> None:
    for segment in plan.segments:
        segment.duration = seconds


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

    def test_cut_happens_at_the_midpoint_between_anchors(self) -> None:
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
        _set_durations(plan)
        assign_audio_times(plan, 0.0)

        first, second = plan.frames
        expected = (first.anchor + second.anchor) / 2.0
        self.assertAlmostEqual(second.start, expected, places=3)
        self.assertAlmostEqual(first.end, second.start, places=3)
        self.assertAlmostEqual(plan.frames[-1].end, plan.end, places=3)

    def test_qr_frame_is_not_capped_at_a_fixed_duration(self) -> None:
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
        self.assertEqual(plan.frames[0].min_hold, QR_MIN_HOLD_SEC)

        _set_durations(plan, 20.0)
        assign_audio_times(plan, 0.0)

        duration = plan.frames[0].end - plan.frames[0].start
        self.assertGreater(duration, 15.0)

    def test_table_respects_its_minimum_hold(self) -> None:
        chapter = _chapter(
            1,
            [
                Block("heading", "Глава 1. Начало"),
                Block("table", caption="таблица 1. Данные", image="table.png"),
                Block("paragraph", "Текст после таблицы."),
            ],
        )
        plan = plan_chapter(chapter, "ru_m5", "ru_f1", table_min_hold=8.0)
        _set_durations(plan, 1.0)
        assign_audio_times(plan, 0.0)

        self.assertGreaterEqual(
            plan.frames[0].end - plan.frames[0].start,
            8.0,
        )


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


if __name__ == "__main__":
    unittest.main()
