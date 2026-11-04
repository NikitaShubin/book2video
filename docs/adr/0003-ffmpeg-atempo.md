# ADR-0003: ffmpeg atempo is the only time-stretch

**Status:** accepted

## Context

The default narration rate is 1.2×. The first attempt let Tera render faster
with `duration_scale`; the second used `rubberband` after synthesis. Both
failed listening tests:

- Tera `duration_scale` below 1.0 repeats words (at 0.65× the phrase «к
  деталям» came out twice) and above ~1.4 swallows consonants.
- `rubberband` with the short window / mixed transients produced audible
  timbre artefacts on the pilot that was rejected.

A speed change must preserve pitch and timbre and must not eat consonants.

## Decision

- Tera always renders at **natural speed**.
- Apply the rate afterwards with **ffmpeg `atempo`** (WSOLA,
  pitch-preserving), as a **single pass** for the whole 0.5–100 range.
- Only speeds below 0.5 chain `atempo=0.5` stages.
- Write intermediate stretched WAVs as `pcm_f32le`; write the final narration
  once as `pcm_s16le`.
- Do not add `aresample` or a second resampler: the stream is already
  44.1 kHz.
- Expose only `--speed`; no `--speed-method`, no `--engine-max-speed`.

## Consequences

- The rate is a post-processing concern; Tera and the cache are independent of
  it.
- Timeline durations come from the stretched files, so sync is preserved.
- The pitch result was measured on the pilot: frame-wise F0 within ~1.5 Hz of
  natural, correlation 0.998.
- If a future rate needs a different algorithm, it must go through
  `speed.apply_speed` and repeat the listening and F0 checks; it must not leak
  into the CLI as a second method.
