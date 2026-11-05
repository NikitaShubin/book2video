"""Time-scale synthesized speech with ffmpeg ``atempo``.

Tera always renders at natural speed; the only speed change is ffmpeg's
``atempo`` (WSOLA), applied as a single pass.  ffmpeg 8 accepts the whole
0.5-100 range in one filter, so there is no chain of ``2.0`` stages.

Two alternatives were tested and rejected:

* Tera's own ``duration_scale`` repeats words below 1.0x (at 0.65x the phrase
  «к деталям» came out twice) and swallows consonants above ~1.4x.
* ``rubberband`` with the short window / mixed transients produced audible
  timbre artefacts on the pilot that was rejected.  It is not used at all.

Pitch is preserved: on our samples the 1.2x take keeps frame-wise F0 within
~1.5 Hz of the natural take (correlation 0.998).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

SAMPLE_RATE = 44_100
MIN_ATEMPO = 0.5
MAX_ATEMPO = 100.0


def _atempo_filter(speed: float) -> str:
    """Return an atempo filter chain for ``speed``.

    One pass is enough for 0.5-100.  Only speeds below 0.5 are chained with
    ``atempo=0.5`` stages, which is still plain ffmpeg.
    """
    if speed <= 0:
        raise ValueError("speed must be positive")
    parts: list[str] = []
    remaining = speed
    while remaining < MIN_ATEMPO:
        parts.append(f"atempo={MIN_ATEMPO}")
        remaining /= MIN_ATEMPO
    if remaining > MAX_ATEMPO:
        raise ValueError(f"speed must not exceed {MAX_ATEMPO}")
    parts.append(f"atempo={remaining:.6f}")
    return ",".join(parts)


def _part_path(dst: Path) -> Path:
    """Temporary sibling with a ``.wav`` suffix so ffmpeg can infer the format."""
    return dst.with_name(f".{dst.name}.part.wav")


def apply_speed(
    src: str | Path,
    dst: str | Path,
    speed: float,
) -> Path:
    """Write a pitch-preserving, time-scaled copy of ``src`` to ``dst``.

    The output is float32 WAV so a later normalization / concatenation step
    does not quantize the signal a second time.  The final narration is
    written once, as PCM16, in :func:`book2video.audio.assemble_audio`.

    The write is atomic: ffmpeg writes ``.<name>.part.wav`` and the file is
    renamed only after a successful encode.  A killed build therefore cannot
    leave a truncated file that a later run mistakes for a cache hit.  This
    matters because several ``apply_speed`` calls run in parallel.
    """
    src = Path(src)
    dst = Path(dst)
    if speed <= 0:
        raise ValueError("speed must be positive")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if abs(speed - 1.0) < 1e-6:
        if src.resolve() != dst.resolve():
            part = _part_path(dst)
            shutil.copy2(src, part)
            part.replace(dst)
        return dst

    part = _part_path(dst)
    command = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
        "-filter:a", _atempo_filter(speed),
        "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_f32le",
        str(part),
    ]
    try:
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg atempo failed: {result.stderr[-800:]}")
        part.replace(dst)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return dst
