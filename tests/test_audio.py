"""Synthesis orchestration: two phases, cached files and parallel atempo."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from book2video.audio import default_atempo_workers, synthesize_plans
from book2video.epub import Chapter
from book2video.timeline import ChapterPlan, Segment


class FakeBackend:
    """One short tone per Segment; counts real (uncached) synthesis calls."""

    def __init__(self, seconds: float = 0.5) -> None:
        self.calls = 0
        self.seconds = seconds

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        self.calls += 1
        rate = 44_100
        time = np.arange(int(rate * self.seconds), dtype=np.float32) / rate
        tone = 0.2 * np.sin(2 * np.pi * 220.0 * time)
        sf.write(out_path, tone, rate, subtype="PCM_16")
        return Path(out_path)


def _plans(chapters: int = 2, segments: int = 3) -> list[ChapterPlan]:
    plans: list[ChapterPlan] = []
    for chapter_index in range(1, chapters + 1):
        chapter = Chapter(
            index=chapter_index,
            href=f"ch{chapter_index}.xhtml",
            title=f"Глава {chapter_index}",
            blocks=[],
            number=chapter_index,
        )
        plans.append(
            ChapterPlan(
                chapter=chapter,
                segments=[
                    Segment(
                        text=f"Фраза {chapter_index}.{segment_index}",
                        voice="ru_m5",
                        kind="paragraph",
                        block_index=segment_index,
                    )
                    for segment_index in range(segments)
                ],
                frames=[],
            )
        )
    return plans


class SynthesizePlansTests(unittest.TestCase):
    def test_applies_speed_and_reuses_the_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            backend = FakeBackend()

            plans = _plans()
            synthesize_plans(
                backend,
                plans,
                work,
                speed=2.0,
                atempo_workers=3,
                log=lambda *_: None,
            )

            self.assertEqual(backend.calls, 6)
            for plan in plans:
                for segment in plan.segments:
                    path = Path(segment.audio_path)
                    self.assertEqual(path.name[-len("_s2.000_at.wav"):], "_s2.000_at.wav")
                    self.assertAlmostEqual(segment.duration, 0.25, delta=0.03)

            leftovers = list((work / "audio").glob(".*.part.wav"))
            self.assertEqual(leftovers, [])

            second = _plans()
            synthesize_plans(
                backend,
                second,
                work,
                speed=2.0,
                atempo_workers=3,
                log=lambda *_: None,
            )
            self.assertEqual(backend.calls, 6)
            self.assertEqual(
                [s.audio_path for p in second for s in p.segments],
                [s.audio_path for p in plans for s in p.segments],
            )

    def test_plan_changes_reuse_audio_by_text_not_by_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            backend = FakeBackend()
            first = _plans(chapters=1, segments=2)
            synthesize_plans(
                backend,
                first,
                work,
                speed=2.0,
                atempo_workers=2,
                log=lambda *_: None,
            )
            self.assertEqual(backend.calls, 2)
            old_paths = {s.text: s.audio_path for s in first[0].segments}

            shifted = _plans(chapters=1, segments=2)
            shifted[0].segments.insert(
                0,
                Segment(
                    text="Новая вставка",
                    voice="ru_m5",
                    kind="link",
                    block_index=0,
                ),
            )
            synthesize_plans(
                backend,
                shifted,
                work,
                speed=2.0,
                atempo_workers=2,
                log=lambda *_: None,
            )

            self.assertEqual(backend.calls, 3)
            self.assertEqual(
                {s.text: s.audio_path for s in shifted[0].segments if s.text in old_paths},
                old_paths,
            )

    def test_atempo_runs_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            backend = FakeBackend()
            plans = _plans(chapters=1, segments=8)

            lock = threading.Lock()
            state = {"active": 0, "peak": 0}

            def fake_apply_speed(src: Path, dst: Path, speed: float) -> Path:
                with lock:
                    state["active"] += 1
                    state["peak"] = max(state["peak"], state["active"])
                time.sleep(0.1)
                with lock:
                    state["active"] -= 1
                Path(dst).write_bytes(Path(src).read_bytes())
                return Path(dst)

            with mock.patch("book2video.audio.apply_speed", fake_apply_speed):
                synthesize_plans(
                    backend,
                    plans,
                    work,
                    speed=2.0,
                    atempo_workers=4,
                    log=lambda *_: None,
                )

            self.assertGreater(
                state["peak"],
                1,
                "atempo calls did not overlap; the speed phase is sequential",
            )

    def test_invalid_workers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                synthesize_plans(
                    FakeBackend(),
                    _plans(),
                    Path(tmp),
                    atempo_workers=0,
                    log=lambda *_: None,
                )

    def test_default_worker_count_is_bounded(self) -> None:
        self.assertGreaterEqual(default_atempo_workers(), 1)
        self.assertLessEqual(default_atempo_workers(), 8)

    def test_speed_one_uses_the_natural_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plans = _plans(chapters=1, segments=2)
            synthesize_plans(
                FakeBackend(),
                plans,
                Path(tmp),
                speed=1.0,
                log=lambda *_: None,
            )
            for segment in plans[0].segments:
                name = Path(segment.audio_path).name
                self.assertNotIn("_s", name)
                self.assertAlmostEqual(segment.duration, 0.5, delta=0.02)


if __name__ == "__main__":
    unittest.main()
