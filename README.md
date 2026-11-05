# book2video

Turn Russian EPUB books into long narrated MP4 videos with illustrations
synchronized to the narration.

One video per book. Only illustrations are shown: static frames, hard cuts, no
subtitles, no on-screen titles. Images never appear before their chapter starts.
Everything runs inside a container; the host needs Docker and nothing else.

## What it produces

- A single 1920×1080 H.264/AAC MP4 per book, with MP4 metadata and one chapter
  marker per content chapter.
- Narration from a local TTS model (TeraTTSv2, ONNX, CPU).
- Illustrations, tables and QR codes anchored to the sentence that introduces
  them. Cuts land at the midpoint between two anchors.
- Sidebars read in place with an opposite-gender voice.
- URLs read aloud and shown as a QR frame with the full URL as a caption.

The full illustration and content-selection policy is in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The words used in the code are
defined in [docs/GLOSSARY.md](docs/GLOSSARY.md).

## Status

The pipeline works end to end and has been validated on *Как приготовить
проект* by Егор Ганин, chapter 4 «Аналитика»:

| Run | Duration | Frames | Sync |
| --- | --- | --- | --- |
| natural speed | 22.8 min | 8 | audio/video within 0.01 s |
| default 1.2× | 19.2 min | 8 | audio/video within 0.01 s |

Both runs had the correct chapter marker and both QR frames in place. The same
chapter has not yet been accepted for a full-book build; a full book is built
only after one chapter passes the listening check in
[docs/TESTING.md](docs/TESTING.md).

## Requirements

- Docker with Compose.
- No CUDA, no Python, no ffmpeg on the host. The image is CPU-only.
- Roughly 3 GB of disk for the image and model cache, plus space for output.
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

# Render one chapter as a pilot.
docker compose run --rm book2video build "/data/My Book.epub" \
  --chapter 4 --voice ru_m5 --sidebar-voice ru_f1 \
  --out /out/pilot.mp4 --work-dir /out/_work_pilot

# Render the whole book into one file.
docker compose run --rm book2video build "/data/My Book.epub" \
  --all --voice ru_m5 --sidebar-voice ru_f1 \
  --out /out/book.mp4 --work-dir /out/_work_book
```

Books are mounted read-only at `/data` (the parent directory of this project),
output goes to `./out`. Model and TTS caches live in the named volumes
`book2video_hf-cache` and `book2video_b2v-cache`, so rebuilding the image does
not re-download the model.

`make` wraps the common cases:

```bash
make image                       # docker compose build
make voices
make inspect BOOK="/data/My Book.epub"
make pilot BOOK="/data/My Book.epub" CHAPTER=4
make all BOOK="/data/My Book.epub" ALL_OUT=/out/book.mp4
make test                        # unit tests inside the container
make check                       # tests + CLI smoke check
make clean                       # remove out/*
```

## Commands

| Command | Purpose |
| --- | --- |
| `book2video voices` | list the ten Tera voices |
| `book2video say "текст" --speed 1.2` | synthesize one phrase (smoke test) |
| `book2video stress "текст"` | print Tera's own stress markup |
| `book2video inspect book.epub` | list parsed chapters and counts |
| `book2video inspect book.epub --blocks 4` | dump one chapter block by block |
| `book2video build book.epub` | build the first content chapter |
| `book2video build book.epub --chapter 4` | build one chapter by number or title fragment |
| `book2video build book.epub --all` | build every content chapter into one video |

Global options `--provider` and `--threads` control the ONNX runtime. Build
options: `--voice`, `--sidebar-voice`, `--work-dir`, `--table-hold`, `--speed`,
`--atempo-workers`, `--crf`, `--preset`.

## Voices

Primary backend: **TeraTTSv2** (`TeraSpace/TeraTTSv2`), ONNX, CPU.

All ten built-in voices are exposed; four are native Russian, six are English
voices that read Russian cross-lingually. Use `book2video voices` for the list.
The defaults are:

- main narration: `ru_m5` (male)
- sidebars and boxes: the opposite-gender native voice (`ru_f1` for `ru_m5`)

Both are CLI options; nothing is hard-coded to one voice. English terms are
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
   render URLs as words; replace dashes Tera cannot pronounce.
3. **Synthesize.** Split text into sentence-sized chunks, call Tera, cache each
   chunk by text + voice, then apply `atempo` to the whole take.
4. **Plan.** Build a `Segment` per narrated unit, anchor frames to segments,
   and schedule cuts at midpoints. Tables, QR codes and blank frames are normal
   frames with their own area of influence.
5. **Assemble.** Concatenate segment audio with planned pauses, normalize
   loudness, and write one PCM16 WAV.
6. **Render.** Loop each still for its exact duration, join with the ffmpeg
   `concat` filter, encode H.264/AAC, and attach MP4 metadata and chapters.

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
Dockerfile.offline          rebuild app code on the existing image (no network)
compose.yaml                caches, /data read-only, /out writable
docker-entrypoint.sh        fixes volume ownership, drops to app user
Makefile                    image, build, test and cleanup targets
src/book2video/epub.py      spine, blocks, front/back matter filtering
src/book2video/normalize.py numbers, years, abbreviations, units, URLs
src/book2video/timeline.py  segments, anchors, midpoint scheduling, QR frames
src/book2video/audio.py     TTS orchestration, loudness, WAV assembly
src/book2video/speed.py     ffmpeg atempo time scaling
src/book2video/render.py    frames, ffmpeg render, metadata, chapters
src/book2video/build.py     end-to-end orchestration
src/book2video/cli.py       voices, say, stress, inspect, build
src/book2video/voices.py    voice catalogue and defaults
src/book2video/tts/tera.py  Tera backend, chunking, chunk cache
src/book2video/images/qr.py QR frame generation with URL caption
tests/                      unit tests (stdlib unittest)
scripts/check_repetition.py optional Tera repeat diagnostic
docs/                       architecture, glossary, audio, testing, ADRs
```
