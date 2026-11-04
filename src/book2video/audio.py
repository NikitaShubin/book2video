"""Synthesis and audio assembly."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from .speed import apply_speed
from .timeline import CHAPTER_GAP_SEC, ChapterPlan

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


def synthesize_plans(
    backend,
    plans: list[ChapterPlan],
    work_dir: str | Path,
    *,
    speed: float = 1.2,
    log=print,
) -> None:
    audio_dir = Path(work_dir) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    if speed <= 0:
        raise ValueError("speed must be positive")
    log(f"Speed: {speed:.3f}x via ffmpeg atempo (single pass)")
    total = sum(len(plan.segments) for plan in plans)
    done = 0
    total_audio = 0.0
    for plan in plans:
        for index, segment in enumerate(plan.segments):
            done += 1
            stem = f"ch{plan.chapter.index:02d}_{index:04d}"
            natural_path = audio_dir / f"{stem}.wav"
            if not natural_path.exists():
                backend.synthesize(
                    segment.text,
                    voice=segment.voice,
                    out_path=natural_path,
                )
            if abs(speed - 1.0) < 1e-6:
                path = natural_path
            else:
                path = audio_dir / f"{stem}_s{speed:.3f}_at.wav"
                if not path.exists():
                    apply_speed(natural_path, path, speed)
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
            if segment.hold_after > 0:
                pieces.append(np.zeros(int(rate * segment.hold_after), dtype=np.float32))

    if not pieces or sample_rate is None:
        raise ValueError("Nothing to assemble")
    result = np.concatenate(pieces)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out_path, result, sample_rate, subtype="PCM_16")
    return len(result) / sample_rate
