# ADR-0010: lower-pitch native female voice for sidebars

Date: 2026-11-07
Status: accepted

## Context

The default sidebar and link-annotation voice was `ru_f1`, the female voice
recommended by the TeraTTSv2 authors. Long-form listening tests on the four
full validation books showed that `ru_f1` sounds shrill next to the `ru_m5`
male narrator, especially at 2.0×. Measured on the fixed comparison phrase
from `_tts_samples`, the median F0 is about 278 Hz for `ru_f1` and 206 Hz for
`ru_f2`.

Tera exposes two native Russian female voices. The English cross-lingual
voices are a fallback, but they read Russian with a foreign accent, so they are
not suitable for the default.

## Decision

Use `ru_f2` as the implicit sidebar and annotation voice when the main voice is
male. `DEFAULT_SIDEBAR_VOICE` is `ru_f2`, and `opposite_gender()` follows an
explicit preference order: native Russian voices first, then non-whisper
English voices. An explicit `--sidebar-voice` still wins, including whisper
voices.

Do not pitch-shift or otherwise post-process the voice. `atempo` remains the
only signal transform, and it preserves pitch by design.

## Consequences

- Sidebars and annotations are less shrill and sit better under the male
  narrator on long listens.
- Existing audio caches keyed by `ru_f1` are not reused for sidebar segments;
  the first rebuild after this change synthesizes those segments again.
- `ru_f1` remains available through `--sidebar-voice ru_f1`.
- The default is a taste decision, not a quality claim about the model's own
  recommendation.
