# ADR-0002: TeraTTSv2 as the local TTS backend

**Status:** accepted

## Context

The pipeline must run locally, free, on CPU, inside a container. The books are
Russian, with English terms and names mixed in. Cloud TTS would add keys,
network dependence and per-book cost. The voice must be intelligible for long
form and must accept raw Russian text without a separate stress dictionary.

## Decision

Use **TeraTTSv2** (`TeraSpace/TeraTTSv2`), ONNX, loaded through
`transformers` remote code. CPU is the default execution provider; the
optional GPU image can use CUDA with CPU fallback
([ADR-0011](0011-nvidia-acceleration.md)). Expose all ten built-in voices;
default to `ru_m5` for narration and the opposite-gender native voice for
sidebars.

English terms are read by the same voice. Tera's vocabulary covers A–Z, so no
transliteration or second backend is used. Long English quotations are checked
by ear before a full build.

## Consequences

- About 0.25 RTF on a 16-core CPU; a book takes hours, not days.
- The model is downloaded once into the `hf-cache` volume and can then run
  offline.
- Tera owns Russian accentuation. Its mistakes are accepted as-is
  ([ADR-0004](0004-tera-stress-as-is.md)).
- The voice catalogue is a closed list of ten ids; a new backend would need a
  new adapter at the synthesis seam.
- CPU synthesis is the portable baseline; GPU acceleration is optional and
  must never be required to build a book.
