# Testing

Two layers: fast unit/integration tests that run without the model, and a
manual listening gate before a full-book build.

## Automated checks

```bash
make test      # unit + integration tests inside the container
make check     # tests + `book2video --help`
```

Tests run with the standard library `unittest` inside the `book2video` image,
against the **installed** package. Rebuild the image after changing `src/`:

```bash
docker compose build            # online
# or, without network:
docker tag book2video:latest book2video:base
docker build -f Dockerfile.offline -t book2video:latest .
```

`make test` mounts the repository read-only at `/data/book2video` and runs:

```bash
cd /data/book2video && python -m unittest discover -s tests -t tests -v
```

No model download and no network access are required.

### GPU checks

On a host with an NVIDIA GPU and the container toolkit:

```bash
docker compose -f compose.yaml -f compose.gpu.yaml build
docker compose -f compose.yaml -f compose.gpu.yaml run --rm book2video doctor
docker compose -f compose.yaml -f compose.gpu.yaml run --rm book2video \
  --no-gpu doctor
```

`doctor` must list `CUDAExecutionProvider` and `NVENC available: yes` in the
first case, and CPU/NVENC as decided by the fallback rules in the second. The
tests themselves never need a GPU: device detection and the probe are mocked.

### Coverage

| Test | What it pins |
| --- | --- |
| `test_normalize` | year cases, percent/unit agreement, dashes, symbols, sentence numbers, compressed spoken URLs |
| `test_links` | footer status and annotation text, footnote exclusion, compact URL, one-page/multi-page PDFs, image previews, cache reuse and offline misses |
| `test_speed` | single-pass atempo, sub-0.5 chaining, invalid speeds, float32 output and duration, atomic `.part.wav` write on success and failure |
| `test_audio` | two-phase cache reuse, parallel atempo overlap, worker-bound validation, speed 1.0 path |
| `test_timeline` | first frame at chapter start, no gaps, minimum holds, equal shortening, mention preference, content vs QR frames, carry and blank frames |
| `test_tts` | sentence chunking limits, long-sentence fallback, provider auto/cpu/cuda resolution and error cases |
| `test_gpu` | encoder aliases, NVENC probe fallback, explicit-encoder failure, CRF/CQ mapping |
| `test_epub` | package metadata, content filtering, image+caption extraction, chapter selection |
| `test_voices` | unique ids, defaults, opposite-gender selection, non-whisper default, unknown voice |
| `test_build` | full EPUB → MP4 with a fake backend and an injected preview: H.264/AAC, non-zero duration, chapter marker, content frame in `timeline.json`, and bounded chunk rendering |
| `test_render` | finished render parts are reusable only when frame inputs, encoder settings and ffprobe duration match |

The PDF tests use `pdfinfo` and `pdftoppm` from `poppler-utils`; they are
skipped with a clear message if the tool is missing. The production image
installs poppler and Playwright/Chromium, so both run there. `book2video links`
is the manual network smoke test: it exercises every provider without the
model.

The integration test uses `FakeBackend`, which writes a short tone for each
Segment. It is the seam that keeps the pipeline testable without Tera. See
[ARCHITECTURE.md](ARCHITECTURE.md#seams-and-adapters).

### Adding tests

- Put them in `tests/test_*.py`, use `unittest`, and do not require the model.
- Prefer the module's public interface. If a rule can only be tested by
  reaching inside, that is a design signal, not a reason to add a private
  import.
- For a new EPUB rule, add a synthetic EPUB fixture (see `test_epub.py`) rather
  than committing a copyrighted book.

## Manual acceptance gate

Do not start a full-book build until one chapter passes this checklist.

1. **Inspect the parse.**

   ```bash
   book2video inspect "/data/book.epub"
   book2video inspect "/data/book.epub" --blocks 4
   ```

   Check that the chapter list has no front/back matter, and that images,
   tables, sidebars, captions and links are classified as expected. Then
   resolve the links as a dry run:

   ```bash
   book2video links "/data/book.epub"
   ```

   Every non-footnote URL should appear once, with a `content` or `qr`
   decision. A content decision should have a plausible kind and page count.

2. **Build one chapter.**

   ```bash
   book2video build "/data/book.epub" --chapter 4 \
     --out /out/pilot.mp4 --work-dir /out/_work_pilot
   ```

3. **Listen at the default rate.** Headphones, first minute and a random
   middle minute. Reject if consonants are swallowed, a phrase repeats, or the
   voice changes inside a paragraph.

4. **Check sync.** Audio and video must end together and chapter markers must
   match the narration:

   ```bash
   ffprobe -v error -show_entries format=duration \
     -show_entries stream=codec_type,duration -show_chapters \
     -of default=nw=1 /out/pilot.mp4
   ```

   Video and audio durations should differ by less than 0.05 s. The chapter
   marker title and start time should match `timeline.json`.

5. **Check frames.** Use `timeline.json` to find each frame's start and end:
   - no image before the chapter start;
   - every frame holds at least `--frame-hold`, unless the chapter is too
     short, in which case all frames are shortened equally;
   - a cut doesn't cross a chapter boundary and the mention is inside its own
     frame where possible;
   - tables are readable;
   - each link frame shows the compact URL and a scannable mini-QR, or the
     full URL in the QR fallback;
   - a full document has no status line, a partial one reports its page count
     or `первый экран`;
   - a chapter without illustrations keeps the previous frame.

6. **Check the tail.** Appendices are in the same file, after the last content
   chapter.

7. **Only then** run `--all`.

## Diagnostics

- `book2video say "текст" --speed 1.2` — synthesis and atempo smoke test.
- `book2video stress "текст"` — print Tera's own stress markup; confirms raw
  text is passed without pre-marking.
- `book2video links "/data/book.epub" --json` — classify every link without
  building; `--work-dir` keeps the previews for inspection.
- `book2video links "/data/book.epub" --offline-links` — prove an air-gapped
  rerun uses only the cache.
- `book2video clean-cache --root out --dry-run` — list work caches that would be
  removed.
- `scripts/check_repetition.py out/_work_book/audio/*.wav` — scan WAVs for a
  repeated phrase (a Tera `duration_scale` artefact). The production path no
  longer uses `duration_scale`, so this is a regression check.
- `work/timeline.json` — every Segment and Frame with times, text and preview
  metadata.
- `work/frames.txt` — the exact frame plan handed to ffmpeg.

## Full-book validation record

The 0.1.0 release was validated on four complete books, not only a pilot
chapter. The durations, frame counts, chapter counts and A/V deltas are in
[docs/RELEASE.md](RELEASE.md). One of those books has 416 frames and 149
chapters; it is the regression case for the bounded chunk renderer. A synthetic
version of the same path is covered by
`test_build.test_many_frames_are_rendered_in_chunks`, so the OOM regression is
caught without a copyrighted fixture.
