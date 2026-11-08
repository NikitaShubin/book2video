# Release 0.2.0

This is the second early-access release of `book2video`. It adds optional
NVIDIA acceleration and resumable rendering. It is a **source release**: the
pipeline, container definitions, tests and documentation. It deliberately does
not contain books or generated media.

## What is in the release

- `src/book2video/` — the pipeline.
- `tests/` — 98 automated tests, including one end-to-end render.
- `Dockerfile`, `Dockerfile.offline`, `compose.yaml`, `compose.gpu.yaml`,
  `Makefile`.
- `README.md`, `docs/`, `CHANGELOG.md`, `THIRD_PARTY.md`, `LICENSE`.
- Small scripts used for diagnostics under `scripts/`.

## What is not in the release

The following are excluded by `.gitignore` and must never be attached to a
release:

- EPUB files and any other source book;
- MP4, MKV, MOV, WAV, FLAC or MP3 output;
- `out/` work directories: frames, timelines, per-book caches, narration;
- model weights and Hugging Face / ONNX caches;
- credentials, `.env` files and session data.

This keeps the artifact small and avoids redistributing copyrighted books or
their narration.

## Requirements

- Docker with Compose.
- A CPU-only host is enough. No host Python, ffmpeg or CUDA is required.
- Optional NVIDIA acceleration: a supported driver and the NVIDIA Container
  Toolkit. The GPU image carries the CUDA 12.8 and cuDNN user-space libraries;
  no host CUDA toolkit is needed.
- Roughly 3 GB for the CPU image and model cache, plus output space. The GPU
  image is larger. A 10-hour book used about 17 GB of work cache in validation.
- Network access is needed for the first model download and for online link
  previews. `--offline-links` and `HF_HUB_OFFLINE=1` support air-gapped runs
  once the caches exist.

## Reproduce the validation

The release was validated against four full-length Russian EPUBs at 2.0×.
The table records output duration, frame count, chapter count and the measured
audio/video delta:

| Book | Duration | Frames | Chapters | A/V delta |
| --- | ---: | ---: | ---: | ---: |
| *Как приготовить проект* | 175.6 min | 86 | 10 | 0.001 s |
| *Scrum на практике* | 220.6 min | 12 | 10 | 0.001 s |
| *Scrum. Революция* | 257.2 min | 31 | 24 | 0.001 s |
| *Настольная книга project-менеджера* | 597.5 min | 416 | 149 | 0.001 s |

A representative run:

```bash
docker compose build

docker compose run --rm book2video links "/data/Book.epub" \
  --work-dir /out/_work_book

docker compose run --rm book2video build "/data/Book.epub" \
  --all --voice ru_m5 --sidebar-voice ru_f2 \
  --speed 2.0 --work-dir /out/_work_book \
  --out /out/book.mp4

ffprobe -v error \
  -show_entries format=duration:stream=codec_type,codec_name,duration \
  -show_chapters -of json /out/book.mp4
```

Expected: one H.264 1920×1080 stream, one AAC stream, an A/V delta below
0.05 s, and one chapter marker per content chapter. The release itself does
not ship the EPUBs, so the validation table is a record, not a reproducible
fixture.

## Verification before publishing

1. `make check` — all tests pass and the CLI starts.
2. `git status --short` — clean.
3. `git ls-files` — no media or cache paths; only source and docs.
4. Build the source archive and inspect its file list.

```bash
git archive --format=tar.gz \
  --prefix=book2video-0.2.0/ \
  -o /tmp/book2video-0.2.0.tar.gz v0.2.0
tar -tzf /tmp/book2video-0.2.0.tar.gz | sort
```

The archive must contain no `.epub`, `.mp4`, `.wav`, `.onnx`, generated `out/`
work files or model cache entries. `out/.gitkeep` is the only allowed path
under `out/`; it keeps the empty directory in a checkout.

## Known limitations

- The parser is tuned for Russian, text-heavy EPUBs. Fixed-layout, comics and
  DRM-protected books are out of scope.
- Link previews depend on public pages. Captchas, logins, dead hosts and
  unsupported file types fall back to QR frames; they never fail the build.
- Tera's stress placement is accepted as-is; wrong stresses stay in the audio.
- Synthesis is CPU-only by default and deliberately slow. The cache makes
  reruns cheaper but a first full-book build is an overnight job. The optional
  GPU image accelerates synthesis and NVENC re-encoding; GPU performance and
  NVENC chunk concatenation still need validation on an NVIDIA host and are
  not part of the 0.2.0 CPU validation record.
- Preview rendering requires Playwright/Chromium and poppler, which are in the
  main image, not the offline app-only image.
- The project source is MIT-licensed; third-party components and the TeraTTSv2
  model keep their own terms.

## Suggested release notes

> Early access 0.2.0: EPUB to narrated 1080p MP4, TeraTTSv2 on CPU, cached
> per-segment synthesis, illustration/table/link-preview frames, QR fallback,
> chapter markers, and bounded, resumable rendering for long books. Optional
> NVIDIA CUDA and NVENC acceleration with automatic CPU fallback. Validated
> on four full-length Russian books. Books and generated media are not
> included.
