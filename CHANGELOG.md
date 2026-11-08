# Changelog

All notable changes are recorded here. The project follows a simple
`MAJOR.MINOR.PATCH` scheme; during early access, minor versions may change
command-line behaviour.

## 0.2.0 - 2026-11-08

### Added

- Optional NVIDIA GPU acceleration. A `book2video:gpu` image uses
  `onnxruntime-gpu` with CUDA 12.8 user-space libraries and NVENC; the default
  CPU image is unchanged.
- `--provider auto|cpu|cuda`, `--encoder auto|libx264|h264_nvenc`, `--no-gpu`
  and a `doctor` command that reports ONNX providers, CUDA devices and NVENC
  status. `auto` probes real availability and falls back to CPU.
- `compose.gpu.yaml`, `make image-gpu`, `make doctor`, and `GPU=1`,
  `PROVIDER`, `ENCODER`, `NO_GPU` make variables.
- `Dockerfile.offline` can rebuild either the CPU or the GPU image through
  `BASE_IMAGE`.
- ADR-0011 records the NVIDIA decision.
- 98 automated tests, including render-part reuse.

### Changed

- The render chunk bound is 32 still inputs instead of 96. On a 14 GiB host,
  96 inputs at 1080p reached 8.2 GiB RSS and were killed before encoding
  started; 32 keeps peak memory near 3 GiB. Long books are split into more
  parts and joined by the same concat demuxer.
- Finished render parts are reused after an interruption. A part is reused
  only when its frame inputs and encoder settings match and ffprobe confirms
  its expected duration, so a killed or stale part is re-encoded instead of
  being spliced into the output.

## 0.1.0 - 2026-11-07

First early-access source release.

### Added

- EPUB parsing and heuristic front/back-matter filtering.
- TeraTTSv2 narration on CPU with four native Russian voices and six English
  cross-lingual voices.
- Content-addressed TTS chunk cache and cached ffmpeg `atempo` output.
- Illustration, table, QR and blank frames with a minimum-hold scheduler.
- Link previews for Google Docs/Sheets/Slides, Yandex Disk, Yandex Docs,
  generic PDFs, images and HTML pages, with QR fallback and offline mode.
- Content-frame footer with compact URL, mini-QR and partial-item status.
- One MP4 per book with H.264/AAC, metadata and chapter markers.
- `voices`, `say`, `stress`, `inspect`, `links`, `build` and `clean-cache`
  commands.
- MIT license (`LICENSE`).
- 81 automated tests, including an end-to-end build with a fake TTS backend.

### Changed

- The implicit sidebar and annotation voice is now native Russian `ru_f2`
  instead of `ru_f1`; `ru_f1` was too shrill next to the male narrator on long
  listens. Explicit `--sidebar-voice` is unchanged. See
  [ADR-0010](docs/adr/0010-sidebar-voice.md).

### Fixed

- Books with hundreds of frames no longer exhaust container memory: renders
  are encoded in bounded chunks and joined losslessly. The 416-frame
  validation book previously died with `SIGKILL` after ffmpeg reached 13.4 GiB
  RSS.

### Validated

Four full-length Russian books were built at 2.0×, from 175.8 to 597.5
minutes, with 10 to 149 chapters. Audio/video delta stayed below 0.034 s and
every output carried the expected chapter markers. The books, audio, frames
and caches are not part of this release.
