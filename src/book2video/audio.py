"""Synthesis and audio assembly."""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf

from .speed import apply_speed
from .timeline import CHAPTER_GAP_SEC, ChapterPlan, Segment

TARGET_RMS = 0.07
MAX_PEAK = 0.95


def _normalise(audio: np.ndarray) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if audio.size == 0:
        return audio
    rms = float(np.sqrt(np.mean(audio * audio)))
    peak = float(np.max(np.abs(audio)))
    if rms < 1e-5 or peak < 1e-5:
        return audio
    gain = TARGET_RMS / rms
    gain = min(gain, MAX_PEAK / peak)
    return np.clip(audio * gain, -1.0, 1.0)


def default_atempo_workers() -> int:
    """Reasonable number of concurrent ffmpeg processes."""
    return min(8, os.cpu_count() or 1)


def _apply_atempo_parallel(
    pending: list[tuple[Path, Path]],
    speed: float,
    workers: int,
    log,
) -> None:
    """Apply ``atempo`` to every ``(natural, adjusted)`` pair concurrently.

    Workers only block on ffmpeg subprocesses, so threads are enough; a
    process pool would add pickling cost for no gain.  Each ``apply_speed``
    writes its own atomic ``.part.wav``, so parallel runs cannot collide.
    """
    if not pending:
        return
    log(f"Applying atempo to {len(pending)} segment(s) at {speed:.3f}x with {workers} worker(s)")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(apply_speed, natural, adjusted, speed)
            for natural, adjusted in pending
        ]
        for future in futures:
            future.result()


def _segment_stem(segment: Segment) -> str:
    """Content address for a segment's audio.

    Segment indices shift whenever the plan gains a link sentence or a
    caption, so an index-based filename would silently reuse the wrong audio.
    Keying by voice and text keeps the cache correct across plan changes and
    lets identical segments share one file.
    """
    digest = hashlib.sha256(
        f"{segment.voice}\0{segment.text}".encode("utf-8")
    ).hexdigest()
    return digest[:20]


def synthesize_plans(
    backend,
    plans: list[ChapterPlan],
    work_dir: str | Path,
    *,
    speed: float = 1.2,
    atempo_workers: int | None = None,
    log=print,
) -> None:
    """Synthesize every segment and apply the speed change.

    Two phases keep Tera's own threads busy only with synthesis: first all
    missing natural WAVs are rendered sequentially, then all missing speed-adjusted
    WAVs are produced by a pool of ffmpeg processes.  Cached files from an
    earlier run are reused in both phases, so restarts resume cheaply.
    """
    audio_dir = Path(work_dir) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    if speed <= 0:
        raise ValueError("speed must be positive")
    if atempo_workers is None:
        atempo_workers = default_atempo_workers()
    if atempo_workers < 1:
        raise ValueError("atempo_workers must be at least 1")

    log(f"Speed: {speed:.3f}x via ffmpeg atempo (single pass)")

    entries: list[tuple[ChapterPlan, Segment, Path, Path]] = []
    total = sum(len(plan.segments) for plan in plans)
    for plan in plans:
        for segment in plan.segments:
            stem = _segment_stem(segment)
            natural_path = audio_dir / f"{stem}.wav"
            speed_path = (
                natural_path
                if abs(speed - 1.0) < 1e-6
                else audio_dir / f"{stem}_s{speed:.3f}_at.wav"
            )
            entries.append((plan, segment, natural_path, speed_path))

    missing_natural = {
        natural_path
        for _, _, natural_path, _ in entries
        if not natural_path.exists()
    }
    if missing_natural:
        log(f"Synthesizing {len(missing_natural)}/{total} segment(s) with Tera")

    for plan, segment, natural_path, _ in entries:
        if natural_path.exists():
            continue
        backend.synthesize(
            segment.text,
            voice=segment.voice,
            out_path=natural_path,
        )

    pending = []
    seen_speed: set[Path] = set()
    for _, _, natural_path, speed_path in entries:
        if natural_path == speed_path or speed_path.exists():
            continue
        # Identical segments share one content-addressed file.  Submit each
        # destination once, or two workers race to rename the same .part.wav.
        if speed_path in seen_speed:
            continue
        seen_speed.add(speed_path)
        pending.append((natural_path, speed_path))
    _apply_atempo_parallel(pending, speed, atempo_workers, log)

    done = 0
    total_audio = 0.0
    for plan, segment, _, path in entries:
        done += 1
        info = sf.info(path)
        segment.audio_path = str(path)
        segment.duration = info.frames / info.samplerate
        total_audio += segment.duration
        log(
            f"[{done:4d}/{total}] ch{plan.chapter.index} "
            f"{segment.kind:9s} {segment.voice:5s} "
            f"{segment.duration:6.1f}s  audio={total_audio/60:6.1f}min  "
            f"{segment.text[:60]!r}"
        )


def assemble_audio(plans: list[ChapterPlan], out_path: str | Path) -> float:
    """Concatenate segment audio with pauses; return the duration in seconds."""
    pieces: list[np.ndarray] = []
    sample_rate: int | None = None
    for plan_index, plan in enumerate(plans):
        if plan_index:
            if sample_rate is None:
                raise ValueError("No audio")
            pieces.append(np.zeros(int(sample_rate * CHAPTER_GAP_SEC), dtype=np.float32))
        for segment in plan.segments:
            if not segment.audio_path:
                continue
            audio, rate = sf.read(segment.audio_path, dtype="float32")
            audio = _normalise(audio)
            if sample_rate is None:
                sample_rate = rate
            elif rate != sample_rate:
                raise ValueError(f"Sample rate mismatch: {rate} != {sample_rate}")
            if segment.pause_before > 0:
                pieces.append(np.zeros(int(rate * segment.pause_before), dtype=np.float32))
            pieces.append(audio)

    if not pieces or sample_rate is None:
        raise ValueError("Nothing to assemble")
    result = np.concatenate(pieces)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out_path, result, sample_rate, subtype="PCM_16")
    return len(result) / sample_rate
