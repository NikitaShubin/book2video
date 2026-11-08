# book2video

Turn Russian EPUB books into long narrated MP4 videos with illustrations
synchronized to the narration.

One video per book. Only stills are shown: illustrations, tables and link
previews; static frames, hard cuts, no subtitles, no on-screen titles. Images
never appear before their chapter starts. Everything runs inside a container;
the host needs Docker and nothing else. An optional NVIDIA image uses CUDA for
synthesis and NVENC for encoding when the driver is available, and falls back
to CPU otherwise.

## What it produces

- A single 1920×1080 H.264/AAC MP4 per book, with MP4 metadata and one chapter
  marker per content chapter.
- Narration from a local TTS model (TeraTTSv2, ONNX, CPU or NVIDIA GPU).
- Illustrations, tables and link previews anchored to the sentence that
  introduces them. Every frame stays at least `--frame-hold` seconds when the
  chapter has room; otherwise all frames are shortened equally.
- Sidebars read in place with an opposite-gender voice.
- Links read aloud: a compressed URL in the main voice, then a short
  annotation in the other voice. The frame shows the first page or first
  screen when it can be rendered, with the compact URL and a mini-QR in the
  footer. Anything that cannot be rendered falls back to a full QR frame.

The full illustration and content-selection policy is in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The words used in the code are
defined in [docs/GLOSSARY.md](docs/GLOSSARY.md).

## Status

Early access, version **0.1.0**. The pipeline works end to end and has been
validated on four full-length Russian books, not just a pilot chapter:

| Validation book | Output | Frames | Chapters | A/V delta |
| --- | ---: | ---: | ---: | ---: |
| *Как приготовить проект* | 175.8 min | 86 | 10 | 0.013 s |
| *Scrum на практике* | 220.6 min | 12 | 10 | 0.033 s |
| *Scrum. Революция* | 257.2 min | 31 | 24 | 0.013 s |
| *Настольная книга project-менеджера* | 597.5 min | 416 | 149 | 0.008 s |

All four were rendered at 2.0× with link previews, QR fallbacks, chapter
markers and the chunked renderer used for long books. The copyright holders'
EPUBs, narration and MP4 files are **not** part of the release; only the
pipeline and this documentation are.

The release scope, artifact contents and known limitations are in
[docs/RELEASE.md](docs/RELEASE.md). The manual chapter acceptance procedure is
still in [docs/TESTING.md](docs/TESTING.md).

## Requirements

- Docker with Compose.
- No Python or ffmpeg on the host. The default image is CPU-only.
- Optional NVIDIA acceleration: an NVIDIA GPU, a driver supported by the
  installed CUDA runtime, and the
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/).
  No CUDA toolkit is needed on the host; the user-space libraries live in the
  GPU image.
- Roughly 3 GB of disk for the CPU image and model cache, plus space for
  output. The GPU image is larger because it carries the CUDA and cuDNN
  runtime. Long books need much more temporary space: the PM validation run
  used about 17 GB for caches and intermediate audio.
- Network access for link previews (Google Docs, Yandex Disk, generic sites).
  Rendering and TTS are otherwise local; `--offline-links` avoids the network.
- About 0.25 RTF for synthesis on a 16-core CPU: a 5-hour book takes roughly
  1.5 hours of synthesis. Audio chunks are cached, so re-renders are cheaper.

### Offline runs

The first run downloads TeraTTSv2 into the `hf-cache` volume. After that the
model is local. If Hugging Face is unreachable, force the cache-only path:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 docker compose run --rm book2video ...
```

`compose.yaml` passes both variables through. Without them, transformers may
spend a minute retrying HEAD requests before falling back to the cache.

## Quick start

```bash
cd book2video
docker compose build

# List the ten built-in Tera voices.
docker compose run --rm book2video voices

# Inspect a book: chapters, image counts, character counts.
docker compose run --rm book2video inspect "/data/My Book.epub"

# Dump one chapter block by block.
docker compose run --rm book2video inspect "/data/My Book.epub" --blocks 4

# Resolve every external link without building a video.
docker compose run --rm book2video links "/data/My Book.epub"

# Render one chapter as a pilot.
docker compose run --rm book2video build "/data/My Book.epub" \
  --chapter 4 --voice ru_m5 --sidebar-voice ru_f2 \
  --out /out/pilot.mp4 --work-dir /out/_work_pilot

# Render the whole book into one file.
docker compose run --rm book2video build "/data/My Book.epub" \
  --all --voice ru_m5 --sidebar-voice ru_f2 \
  --out /out/book.mp4 --work-dir /out/_work_book
```

### NVIDIA acceleration (optional)

The default image is CPU-only. To use an NVIDIA GPU, build the GPU target and
start the container through the GPU override:

```bash
# Build book2video:gpu with onnxruntime-gpu and the CUDA user-space libraries.
docker compose -f compose.yaml -f compose.gpu.yaml build

# Check what the container actually sees.
docker compose -f compose.yaml -f compose.gpu.yaml run --rm book2video doctor

# Build with automatic GPU selection.
docker compose -f compose.yaml -f compose.gpu.yaml run --rm book2video build \
  "/data/My Book.epub" --all --voice ru_m5 --sidebar-voice ru_f2 \
  --out /out/book.mp4 --work-dir /out/_work_book

# Force CPU even though the GPU is available.
docker compose -f compose.yaml -f compose.gpu.yaml run --rm book2video \
  --no-gpu build "/data/My Book.epub" --all --out /out/book.mp4
```

With `--provider auto` (default) and `--encoder auto` (default) TTS uses the
CUDA execution provider when the NVIDIA devices are visible and
`onnxruntime` has CUDA, and the encoder uses NVENC only when a real one-frame
probe encode succeeds. Any missing piece falls back to CPU. `doctor` prints
the decisions without loading the model. `--no-gpu` forces CPU for both TTS
and encoding; `--provider cpu` and `--encoder libx264` force one part.

The GPU image needs a host driver that supports CUDA 12.8 and the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/).
No CUDA toolkit is installed on the host. The CPU image can still use NVENC
if it is started with `--gpus all`; TTS stays on CPU there because the CPU
image does not carry the CUDA execution provider.

Without the container toolkit, Compose fails with
`failed to discover GPU vendor from CDI`. Install the toolkit, or use
`compose.yaml` alone for a CPU build.

Books are mounted read-only at `/data` (the parent directory of this project),
output goes to `./out`. Model and TTS caches live in the named volumes
`book2video_hf-cache` and `book2video_b2v-cache`, so rebuilding the image does
not re-download the model.

`make` wraps the common cases:

```bash
make image                       # docker compose build (CPU)
make image-gpu                   # docker compose with the GPU override
make voices
make doctor                      # show ONNX/CUDA/NVENC availability
make inspect BOOK="/data/My Book.epub"
make pilot BOOK="/data/My Book.epub" CHAPTER=4
make all BOOK="/data/My Book.epub" ALL_OUT=/out/book.mp4
make test                        # unit tests inside the container
make check                       # tests + CLI smoke check
make clean                       # remove out/*
```

`GPU=1 make ...` uses the GPU compose files for every target. `PROVIDER`
(`auto`, `cpu`, `cuda`), `ENCODER` (`auto`, `libx264`, `h264_nvenc`) and
`NO_GPU=1` are passed through to the build, for example
`NO_GPU=1 make all BOOK=...`.

## Commands

| Command | Purpose |
| --- | --- |
| `book2video voices` | list the ten Tera voices |
| `book2video doctor` | show ONNX providers, CUDA devices and NVENC status |
| `book2video say "текст" --speed 1.2` | synthesize one phrase (smoke test) |
| `book2video stress "текст"` | print Tera's own stress markup |
| `book2video inspect book.epub` | list parsed chapters and counts |
| `book2video inspect book.epub --blocks 4` | dump one chapter block by block |
| `book2video links book.epub` | resolve and classify every external link (dry run) |
| `book2video links book.epub --json` | the same decisions as JSON |
| `book2video build book.epub` | build the first content chapter |
| `book2video build book.epub --chapter 4` | build one chapter by number or title fragment |
| `book2video build book.epub --all` | build every content chapter into one video |
| `book2video clean-cache --root out` | remove per-book work directories (`--dry-run` to list) |

Global options `--provider` (`auto`, `cpu`, `cuda` or a full ONNX provider
name), `--threads` and `--no-gpu` control TTS hardware. Build options:
`--voice`, `--sidebar-voice`, `--work-dir`, `--frame-hold`, `--offline-links`,
`--store-cache`, `--speed`, `--atempo-workers`, `--crf`, `--preset`,
`--encoder` (`auto`, `libx264` or `h264_nvenc`).

### Links and previews

External links (except footnotes) get a spoken sentence and a frame. The
default is **online**: each unique URL is resolved once per book and cached
under `<work-dir>/links/`. The adapters cover Google Docs/Sheets/Slides,
Yandex Disk and Yandex Docs, generic PDFs, images and HTML screenshots.
Everything else - docx, archives, video, failed fetches - stays a QR frame; a
failure never fails the build.

`--offline-links` reads only the existing per-book cache. A cache miss becomes
a QR frame and no network request is made. Use it for an air-gapped rerun:

```bash
book2video build "/data/My Book.epub" --all \
  --offline-links --work-dir /out/_work_book \
  --out /out/book.mp4
```

`book2video links` is a dry run that prints the decision for every URL without
synthesizing or rendering. Add `--work-dir` to populate a real cache, or let it
use a temporary directory.

### Cache cleanup

Each build keeps its work directory, including TTS chunks, link previews,
speed-adjusted WAVs and frame PNGs. Rerunning the same build reuses all of it.
`book2video clean-cache --root out` lists the per-book work directories under
`out` and removes them; add `--dry-run` to inspect and `--work-dir DIR` to
target one. `--store-cache` is the release-time switch that keeps a successful
build's cache once automatic cleanup is enabled.

## Voices

Primary backend: **TeraTTSv2** (`TeraSpace/TeraTTSv2`), ONNX, CPU or NVIDIA
GPU through the CUDA execution provider.

All ten built-in voices are exposed; four are native Russian, six are English
voices that read Russian cross-lingually. Use `book2video voices` for the list.
The defaults are:

- main narration: `ru_m5` (male)
- sidebars and boxes: the opposite-gender native voice (`ru_f2` for `ru_m5`).
  `ru_f2` is used instead of the authors' recommended `ru_f1` because it has a
  lower pitch and sounds less shrill next to `ru_m5`; see
  [ADR-0010](docs/adr/0010-sidebar-voice.md)

Both are CLI options; the defaults can be overridden per run. English terms are
read by the same voice, because Tera's vocabulary covers A–Z. No
transliteration or separate English TTS is used; long English quotations are
checked by ear before a full build.

## Speech rate

Default is **1.2×**. Tera always renders natural speech; the speed-up is
applied afterwards with ffmpeg `atempo` (WSOLA, pitch-preserving). ffmpeg 8
accepts a single `atempo` pass for the whole 0.5–100 range, so no filter chain
is used. Synthesis and the speed change are separate phases: Tera renders missing
natural WAVs sequentially, then a bounded pool of ffmpeg processes applies atempo to
the segments that are not cached yet (`--atempo-workers`, default
`min(8, CPU count)`). Intermediate speed-adjusted files are float32 and written
atomically; the narration is written once as PCM16. Pauses are not time-scaled,
and the timeline is built from the actual post-atempo durations, so audio,
frames, and chapter markers stay in sync. Interrupting a build loses at most
the segment being worked on; a restart reuses both caches.

```bash
book2video build book.epub --all --speed 1.2     # default
book2video build book.epub --all --speed 1.0     # natural
book2video build book.epub --all --speed 2.0 --atempo-workers 8
```

Two alternatives were tried and removed from the production path:

- Tera's own `duration_scale` repeats words below 1.0× (at 0.65× the phrase
  «к деталям» came out twice) and swallows consonants above ~1.4×.
- `rubberband` with the short window / mixed transients produced audible
  timbre artefacts in a rejected pilot.

There is no `--speed-method` switch: ffmpeg `atempo` is the only time-stretch.
See [ADR-0003](docs/adr/0003-ffmpeg-atempo.md).

## Stress

TeraTTSv2 has its own context-aware Russian accentuation. Its output is used
as-is: no manual overrides, no exception dictionaries, no RUAccent pre-marking.
If the model places a stress incorrectly, the error stays in the audio. Pass
raw text to Tera: it skips its accentizer for any `<ru>` span that already
contains a `+`, so pre-marking would replace the model's own disambiguation.
See [ADR-0004](docs/adr/0004-tera-stress-as-is.md).

## How it works

1. **Parse.** Read the EPUB spine, drop front/back matter, and extract
   headings, paragraphs, sidebars, images, tables, links and captions.
2. **Normalize.** Expand numbers, years, dates, abbreviations and units;
   compress URLs into a short spoken phrase; replace dashes Tera cannot
   pronounce.
3. **Resolve links.** Turn each unique external URL into a still preview
   (first PDF page, first slide, first screen or image) and keep a per-book
   cache. Failures are left as QR frames.
4. **Synthesize.** Split text into sentence-sized chunks, call Tera, cache each
   chunk by text + voice, then apply `atempo` to the whole take.
5. **Plan.** Build a `Segment` per narrated unit, add the link narration and
   annotation, anchor frames to segments, and schedule cuts with a minimum
   hold. Tables, content previews, QR codes and blank frames are normal frames
   with their own area of influence.
6. **Assemble.** Concatenate segment audio with planned pauses, normalize
   loudness, and write one PCM16 WAV.
7. **Render.** Loop each still for its exact duration, join with the ffmpeg
   `concat` filter, encode H.264/AAC with x264 or NVENC, and attach MP4
   metadata and chapters. Books with more than 32 frames are encoded in
   bounded chunks and joined losslessly, so a 400-frame book cannot exhaust
   the container's memory. Finished chunks are reused when an interrupted
   render is restarted with the same frames and encoder settings.

The module map and design rationale are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); audio details are in
[docs/AUDIO.md](docs/AUDIO.md).

## Development

```bash
make test        # unit tests
make check       # tests + help/smoke checks
```

Tests run inside the container against the installed package, so rebuild the
image after changing `src/`. The test strategy and the manual chapter
acceptance procedure are in [docs/TESTING.md](docs/TESTING.md). Coding
conventions for reviewers are in [CODING_STANDARDS.md](CODING_STANDARDS.md).

## Layout

```
Dockerfile                  CPU image: ffmpeg, fonts, torch CPU, Tera deps
compose.gpu.yaml            GPU override: book2video:gpu, all NVIDIA devices
Dockerfile.offline          rebuild app code on the existing image (no network)
compose.yaml                caches, /data read-only, /out writable
docker-entrypoint.sh        fixes volume ownership, drops to app user
Makefile                    image, build, test and cleanup targets
src/book2video/epub.py      spine, blocks, front/back matter filtering
src/book2video/normalize.py numbers, years, abbreviations, units, spoken URLs
src/book2video/links.py     link policy, providers, previews, per-book cache
src/book2video/timeline.py  segments, anchors, frame scheduler, content frames
src/book2video/audio.py     TTS orchestration, loudness, WAV assembly
src/book2video/speed.py     ffmpeg atempo time scaling
src/book2video/render.py    frames, ffmpeg render, metadata, chapters
src/book2video/gpu.py       NVIDIA detection, NVENC probe, encoder arguments
src/book2video/build.py     end-to-end orchestration
src/book2video/cli.py       voices, say, stress, inspect, links, build
src/book2video/voices.py    voice catalogue and defaults
src/book2video/tts/tera.py  Tera backend, chunking, chunk cache
src/book2video/images/qr.py QR frame generation with URL caption
tests/                      unit tests (stdlib unittest)
scripts/check_repetition.py optional Tera repeat diagnostic
docs/                       architecture, glossary, audio, testing, ADRs
```

## Release

Version 0.1.0 is the first early-access release. It is a source release: the
repository, container definitions and documentation only. No EPUB, MP4, WAV,
frame, cache or model file is included. See [docs/RELEASE.md](docs/RELEASE.md)
for the artifact checklist, validation commands and known limitations.
Changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## License and third-party notices

The project source is released under the [MIT License](LICENSE). The
TeraTTSv2 model is **not** bundled and is used under its own OpenRAIL-M terms;
generated audio may carry additional restrictions. Other components and their
roles are listed in [THIRD_PARTY.md](THIRD_PARTY.md).
