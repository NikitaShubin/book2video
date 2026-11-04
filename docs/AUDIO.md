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
| `ru_f1` | female | ru (recommended by the model authors) |
| `ru_m1`, `ru_f2` | male / female | ru |
| `eng_m3`, `eng_m4`, `eng_f3`, `eng_f5` | male / female | en, read Russian cross-lingually |
| `eng_m2_whisper`, `eng_f4_whisper` | male / female | en whisper, cross-lingual |

Defaults: main `ru_m5`; sidebars `opposite_gender(ru_m5)` = `ru_f1`. The
sidebar voice is used for every block parsed as a sidebar, in place.

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

- ffmpeg 8 accepts `atempo` in the range 0.5–100, so one filter covers every
  supported rate. Only speeds below 0.5 chain `atempo=0.5` stages.
- Intermediate stretched files are `pcm_f32le`, 44.1 kHz, mono.
- The final narration is written once as `pcm_s16le`.
- Pauses are inserted after stretching, so they keep their intended length.
- The timeline uses the measured duration of the stretched file, so frames and
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
3. the segment audio;
4. `hold_after`, the extra silence needed to reach a frame's minimum hold.

Pauses come from `timeline._pause_before`:

| Transition | Pause |
| --- | --- |
| first segment of a chapter | 0.7 s |
| before a heading | 0.9 s |
| after a heading | 0.55 s |
| before/after a sidebar, caption or link | 0.5 s |
| ordinary paragraph | 0.35 s |

The result is one mono 44.1 kHz PCM16 WAV. Its duration is the video duration.

## Quality checks

Before a full book build:

1. Build one chapter and listen at 1.2× on headphones.
2. Check that consonants survive at the fast rate and that no phrase repeats.
3. Check tables and QR frames against the `timeline.json` timestamps.
4. Run `scripts/check_repetition.py` over the chapter WAVs if a repeat is
   suspected.

The manual acceptance procedure is in [TESTING.md](TESTING.md).
