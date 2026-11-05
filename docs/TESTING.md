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

### Coverage

| Test | What it pins |
| --- | --- |
| `test_normalize` | year cases, percent/unit agreement, dashes, symbols, sentence numbers, URL speech, QR decisions |
| `test_speed` | single-pass atempo, sub-0.5 chaining, invalid speeds, float32 output and duration, atomic `.part.wav` write on success and failure |
| `test_audio` | two-phase cache reuse, parallel atempo overlap, worker-bound validation, speed 1.0 path |
| `test_timeline` | first frame at chapter start, midpoint cuts, uncapped QR frames, table minimum hold, carry and blank frames |
| `test_tts` | sentence chunking limits and long-sentence fallback |
| `test_epub` | package metadata, content filtering, image+caption extraction, chapter selection |
| `test_voices` | unique ids, defaults, opposite-gender selection, unknown voice |
| `test_build` | full EPUB → MP4 with a fake backend: H.264/AAC, non-zero duration, chapter marker |

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
   tables, sidebars and captions are classified as expected.

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
   - a cut lands in the middle of the pause between the two anchors;
   - tables are readable and hold for at least `--table-hold`;
   - each QR frame shows the full URL and stays as long as its area of
     influence, with no 15-second cap;
   - a chapter without illustrations keeps the previous frame.

6. **Check the tail.** Appendices are in the same file, after the last content
   chapter.

7. **Only then** run `--all`.

## Diagnostics

- `book2video say "текст" --speed 1.2` — synthesis and atempo smoke test.
- `book2video stress "текст"` — print Tera's own stress markup; confirms raw
  text is passed without pre-marking.
- `scripts/check_repetition.py out/_work_book/audio/ch04_*.wav` — scan WAVs for
  a repeated phrase (a Tera `duration_scale` artefact). The production path no
  longer uses `duration_scale`, so this is a regression check.
- `work/timeline.json` — every Segment and Frame with times and text.
- `work/frames.txt` — the exact frame plan handed to ffmpeg.
