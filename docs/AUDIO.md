# Audio

The narration path is deliberately simple: Tera renders natural speech, ffmpeg
changes the rate, and one PCM16 WAV feeds the renderer.

## Synthesis

Backend: **TeraTTSv2** (`TeraSpace/TeraTTSv2`), ONNX, CPU, loaded through
`transformers` with `trust_remote_code=True`. The model ships its own Russian
accentuation; raw text is passed to `normalize_text` and the result is used
unchanged. See [ADR-0004](adr/0004-tera-stress-as-is.md).

Tera treats bare `<` and `>` as language-tag delimiters. Normalization replaces
them with «меньше» and «больше» before synthesis, so a comparison such as
`1 + 1 > два` is read instead of raising `invalid language tags`.

`TeraBackend.synthesize` splits text into sentence-sized chunks
(`split_sentences`, max 350 characters by default) and calls
`generate_speech` for each. Chunks are joined with a 0.18 s pause. The split
keeps long paragraphs from exceeding the model's comfortable context and gives
the cache useful granularity.

### Chunk cache

Each chunk is written to `$BOOK2VIDEO_CACHE/tts/<sha256>.wav` (`/cache/tts` in
the container). The key includes the model id, voice and Tera's marked text.
Changing the text, voice or model creates new entries; re-rendering the same
book reuses everything. The cache is safe to delete.

### Voices

Ten voices, defined in `voices.py`:

| id | gender | language |
| --- | --- | --- |
| `ru_m5` | male | ru (recommended by the model authors) |
| `ru_f1` | female | ru (recommended by the model authors, high pitch) |
| `ru_f2` | female | ru (lower pitch; default sidebar voice) |
| `ru_m1` | male | ru |
| `eng_m3`, `eng_m4`, `eng_f3`, `eng_f5` | male / female | en, read Russian cross-lingually |
| `eng_m2_whisper`, `eng_f4_whisper` | male / female | en whisper, cross-lingual |

Defaults: main `ru_m5`; sidebars and link annotations
`opposite_gender(ru_m5)` = `ru_f2`. `ru_f1` is the authors' recommended voice,
but its median F0 is roughly 278 Hz against 206 Hz for `ru_f2`; on long
listening tests it sounds shrill next to the male narrator. See
[ADR-0010](adr/0010-sidebar-voice.md). The sidebar voice is used for every
block parsed as a sidebar, in place, and for the annotation sentence after a
spoken URL. An explicit `--sidebar-voice` is obeyed even when it is a whisper
voice; the implicit default always prefers a native, non-whisper voice.

## Loudness

Every segment is normalised independently before assembly:

- target RMS `0.07`;
- peak ceiling `0.95`.

The gain is `min(TARGET_RMS / rms, MAX_PEAK / peak)`, clipped to `[-1, 1]`.
This removes level differences between short headings, long paragraphs and
sidebars without compressing dynamics. Assembly is plain float32 addition of
segments and silence, written once as PCM16.

## Speech rate

Default: **1.2×**. Tera always renders at natural speed; `speed.apply_speed`
uses ffmpeg `atempo` (WSOLA, pitch-preserving) in a single pass.

Synthesis runs in two phases so the slow, thread-hungry model and the cheap,
process-bound speed change never compete for the same resources:

1. every missing natural WAV is rendered sequentially by Tera;
2. every missing speed-adjusted WAV is produced by a `ThreadPoolExecutor` of
   `--atempo-workers` ffmpeg processes (default `min(8, CPU count)`).

Cached files are skipped in both phases, so a restart after an interruption
resumes from the last finished segment. Segment WAVs are content-addressed by
voice and text, not by position, so adding a link sentence or a caption cannot
silently reuse another segment's audio. A thread pool is enough because each
worker only waits on a subprocess. Each atempo run writes `.<name>.part.wav` and
renames it on success, so a killed build cannot leave a truncated file that a
later run mistakes for a cache hit.

- ffmpeg 8 accepts `atempo` in the range 0.5–100, so one filter covers every
  supported rate. Only speeds below 0.5 chain `atempo=0.5` stages.
- Intermediate speed-adjusted files are `pcm_f32le`, 44.1 kHz, mono.
- The final narration is written once as `pcm_s16le`.
- Pauses are inserted after the speed change, so they keep their intended length.
- The timeline uses the measured duration of the speed-adjusted file, so frames and
  chapter markers stay aligned with the audio.

Pitch behaviour: on the pilot, frame-wise F0 stayed within about 1.5 Hz of the
natural take (correlation 0.998), so timbre does not shift audibly.

Rejected alternatives (see [ADR-0003](adr/0003-ffmpeg-atempo.md)):

- Tera `duration_scale` below 1.0 repeats words; above ~1.4 it swallows
  consonants.
- `rubberband` in the short-window / mixed-transient configuration produced
  audible timbre artefacts on the rejected pilot.

## Assembly

`assemble_audio` walks the plans in order and concatenates:

1. a 1.5 s chapter gap between chapters (`CHAPTER_GAP_SEC`);
2. each segment's `pause_before`;
3. the segment audio.

A link adds two ordinary segments: the compressed URL in the main voice and
the annotation in the annotation voice. Frame minimums do not extend the
audio; the frame scheduler uses the real narration length and shortens or
stretches frames to fit it.

Pauses come from `timeline._pause_before`:

| Transition | Pause |
| --- | --- |
| first segment of a chapter | 0.7 s |
| before a heading | 0.9 s |
| after a heading | 0.55 s |
| before/after a sidebar, caption, link or annotation | 0.5 s |
| ordinary paragraph | 0.35 s |

The result is one mono 44.1 kHz PCM16 WAV. Its duration is the video duration.

## Quality checks

Before a full book build:

1. Build one chapter and listen at 1.2× on headphones.
2. Check that consonants survive at the fast rate and that no phrase repeats.
3. Check tables, content previews and QR frames against the `timeline.json`
   timestamps. For a content frame, check that the footer URL is readable, the
   mini-QR scans, and the status line appears only for partial items.
4. Run `scripts/check_repetition.py` over the chapter WAVs if a repeat is
   suspected.

The manual acceptance procedure is in [TESTING.md](TESTING.md).
