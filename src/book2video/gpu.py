"""Optional NVIDIA acceleration: encoder choice and device detection."""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

LIBX264 = "libx264"
NVENC = "h264_nvenc"

# The NVIDIA container runtime mounts these when the container is started with
# ``--gpus all``.  Their presence is the cheapest reliable signal that the
# driver is exposed; the encoder probe below is still required because NVENC
# needs the separate libnvidia-encode library.
_NVIDIA_DEVICES = (Path("/dev/nvidia0"), Path("/dev/nvidiactl"))

_ENCODER_ALIASES = {
    "auto": None,
    "cpu": LIBX264,
    "libx264": LIBX264,
    "nvenc": NVENC,
    "h264_nvenc": NVENC,
}

_NVENC_PRESETS = {
    "ultrafast": "p1",
    "superfast": "p2",
    "veryfast": "p3",
    "faster": "p4",
    "fast": "p5",
    "medium": "p5",
    "slow": "p6",
    "slower": "p7",
    "veryslow": "p7",
}


def nvidia_devices_visible() -> bool:
    """Return True when the NVIDIA driver devices are mounted in the container."""
    return any(path.exists() for path in _NVIDIA_DEVICES)


@lru_cache(maxsize=1)
def nvenc_available() -> bool:
    """Probe ffmpeg once for a working H.264 NVENC encoder.

    Encoder support is compiled into ffmpeg independently of the driver, so
    ``ffmpeg -encoders`` is not enough.  A tiny one-frame encode proves that
    the driver, libnvidia-encode and the GPU are all usable.
    """
    if not nvidia_devices_visible() or shutil.which("ffmpeg") is None:
        return False
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=64x64:r=30:d=0.1",
        "-frames:v",
        "1",
        "-c:v",
        NVENC,
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def resolve_encoder(requested: str = "auto", *, log=None) -> str:
    """Resolve ``auto``/``cpu``/``nvenc`` to a concrete ffmpeg encoder.

    ``auto`` uses NVENC only when the device is visible and a probe encode
    succeeds.  An explicitly requested NVENC fails loudly instead of silently
    falling back.
    """
    key = (requested or "auto").lower()
    if key not in _ENCODER_ALIASES:
        raise ValueError(
            f"Unknown encoder {requested!r}. Use auto, libx264, or h264_nvenc."
        )
    resolved = _ENCODER_ALIASES[key]
    if resolved is None:
        resolved = NVENC if nvenc_available() else LIBX264
        if log:
            reason = "NVENC probe succeeded" if resolved == NVENC else "NVENC unavailable"
            log(f"Video encoder: {resolved} ({reason})")
        return resolved
    if resolved == NVENC and not nvenc_available():
        raise RuntimeError(
            "NVENC was requested, but no usable NVIDIA device is exposed to "
            "this container. Start it with --gpus all and a working driver, "
            "or use --encoder libx264."
        )
    if log:
        log(f"Video encoder: {resolved}")
    return resolved


def encoder_args(encoder: str, crf: int, preset: str) -> list[str]:
    """Return the ffmpeg video-codec arguments for one encoder."""
    if encoder == LIBX264:
        return ["-c:v", LIBX264, "-preset", preset, "-crf", str(crf)]
    if encoder == NVENC:
        return [
            "-c:v",
            NVENC,
            "-preset",
            _NVENC_PRESETS.get(preset, "p5"),
            "-rc",
            "vbr",
            "-cq",
            str(crf),
            "-b:v",
            "0",
        ]
    raise ValueError(f"Unsupported encoder: {encoder}")
