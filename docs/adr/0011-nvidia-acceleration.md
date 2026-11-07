# ADR-0011: Optional NVIDIA GPU acceleration

**Status:** accepted

## Context

A full-book rebuild is dominated by re-encoding, not synthesis: the 597.5 min
validation book took about 2 h 10 min to encode, while the new TTS for its
last rebuild took about 8.4 min because the chunk cache was already full.
Synthesis is also slow on CPU. The build host is NVIDIA-only; AMD/ROCm is not
a target. The same image must keep working on hosts without a GPU, and a user
must be able to force CPU even when a GPU exists.

## Decision

- Ship two images from one codebase: `book2video:latest` (CPU, default) and
  `book2video:gpu`.
- The GPU image installs `onnxruntime-gpu` 1.26 with its CUDA 12.8 and cuDNN
  user-space libraries from PyPI. It keeps the CPU PyTorch wheel: Tera's ONNX
  graph does not need a CUDA PyTorch build.
- `--provider auto` (default) selects the CUDA execution provider only when
  NVIDIA devices are mounted and `onnxruntime` exposes CUDA. If CUDA setup or
  model loading fails under `auto`, the backend logs the reason and retries on
  CPU. Explicit `--provider cuda` fails loudly instead.
- `--encoder auto` (default) selects `h264_nvenc` only after a real one-frame
  probe encode succeeds; NVENC support is compiled into ffmpeg independently
  of the driver, so `ffmpeg -encoders` is not a sufficient check. Otherwise it
  uses `libx264`. Explicit `--encoder h264_nvenc` fails loudly when unavailable.
- `--no-gpu` forces CPU for both TTS and encoding.
- Quality stays comparable: x264 uses `-crf`, NVENC uses
  `-rc vbr -cq` with `-b:v 0`; presets are mapped to the closest NVENC preset.
- The audio chunk cache is provider-agnostic: its key is voice + marked text,
  so CPU and GPU runs share it.
- The GPU compose override requests all NVIDIA devices and sets
  `NVIDIA_DRIVER_CAPABILITIES=compute,utility,video` so NVENC can load
  `libnvidia-encode`.

## Consequences

- CPU-only hosts are unaffected; no CUDA package is pulled into the default
  image.
- GPU hosts accelerate both synthesis and re-encoding, and fall back
  automatically if the driver is unusable from the container.
- The CUDA image is much larger than the CPU image.
- CUDA 12.8 libraries require a sufficiently new host driver. Choosing
  `onnxruntime-gpu` 1.26 instead of 1.27+ avoids the newer CUDA 13 default.
- NVENC output is not bit-identical to x264 and has different rate control;
  both are validated by the same A/V and chapter checks, not by file hashes.
- The GPU path cannot be validated without an NVIDIA host: CUDA speed-up,
  NVENC chunk concat and output quality remain environment checks.
