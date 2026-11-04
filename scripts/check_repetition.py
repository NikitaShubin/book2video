"""Scan WAV files for repeated phrases (Tera duration_scale artifact).

A repeated phrase produces two nearly identical stretches of speech.  The
script builds a log-magnitude spectrogram, normalises every frame, and looks
for a diagonal of high frame-to-frame cosine similarity at a lag between
0.4 s and 4 s.  A genuine repeat shows up as a long, high-similarity diagonal;
ordinary speech only has short phoneme-level matches.

Usage:

    python scripts/check_repetition.py out/_work_book/audio/ch04_*.wav
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

FRAME = 2048
HOP = 512
WINDOW_SECONDS = 0.8
MIN_LAG_SECONDS = 0.4
MAX_LAG_SECONDS = 4.0


def spectrogram(path: Path) -> tuple[np.ndarray, float]:
    audio, rate = sf.read(path, dtype="float32")
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if audio.size < FRAME * 2:
        return np.zeros((0, FRAME // 2 + 1), dtype=np.float32), rate
    count = 1 + (audio.size - FRAME) // HOP
    frames = np.lib.stride_tricks.as_strided(
        audio,
        shape=(count, FRAME),
        strides=(audio.strides[0] * HOP, audio.strides[0]),
        writeable=False,
    )
    window = np.hanning(FRAME).astype(np.float32)
    spec = np.abs(np.fft.rfft(frames * window, axis=1)).astype(np.float32)
    spec = np.log1p(spec)
    return spec, rate


def normalise(spec: np.ndarray) -> np.ndarray:
    spec = spec - spec.mean(axis=1, keepdims=True)
    norm = np.linalg.norm(spec, axis=1, keepdims=True)
    return spec / np.maximum(norm, 1e-8)


def scan(path: Path) -> dict:
    spec, rate = spectrogram(path)
    if spec.shape[0] < 10:
        return {"path": str(path), "duration": 0.0, "score": 0.0, "lag": 0.0}
    frames = normalise(spec)
    sim = frames @ frames.T
    frame_seconds = HOP / rate
    window = max(2, int(round(WINDOW_SECONDS / frame_seconds)))
    min_lag = max(1, int(round(MIN_LAG_SECONDS / frame_seconds)))
    max_lag = min(sim.shape[0] - window - 1,
                  int(round(MAX_LAG_SECONDS / frame_seconds)))

    best_score = 0.0
    best_lag = 0
    best_start = 0
    kernel = np.ones(window, dtype=np.float32) / window
    for lag in range(min_lag, max_lag + 1):
        diagonal = np.diagonal(sim, offset=lag)
        if diagonal.size < window:
            continue
        smoothed = np.convolve(diagonal, kernel, mode="valid")
        index = int(np.argmax(smoothed))
        score = float(smoothed[index])
        if score > best_score:
            best_score = score
            best_lag = lag
            best_start = index

    duration = spec.shape[0] * frame_seconds
    return {
        "path": str(path),
        "duration": duration,
        "score": best_score,
        "lag": best_lag * frame_seconds,
        "start": best_start * frame_seconds,
        "repeat_at": (best_start + best_lag) * frame_seconds,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--threshold", type=float, default=0.80)
    args = parser.parse_args()

    rows = []
    for name in args.files:
        path = Path(name)
        if not path.exists():
            continue
        rows.append(scan(path))
    rows.sort(key=lambda row: row["score"], reverse=True)
    print(f"{'score':>7} {'lag':>6} {'at':>6} {'dur':>7}  file")
    for row in rows:
        flag = "REPEAT?" if row["score"] >= args.threshold else ""
        print(f"{row['score']:7.3f} {row['lag']:6.2f} "
              f"{row.get('repeat_at', 0):6.2f} {row['duration']:7.2f}  "
              f"{Path(row['path']).name} {flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
