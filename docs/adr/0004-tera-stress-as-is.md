# ADR-0004: Tera's stress output is accepted as-is

**Status:** accepted

## Context

Russian homographs need context to accentuate. TeraTTSv2 has its own
context-aware accentizer. Pre-marking text with `+` would make Tera skip its
accentizer for the affected `<ru>` span and replace the model's disambiguation
with ours. A separate RUAccent pass or exception dictionary adds a second
source of truth and a new failure mode.

## Decision

- Pass **raw text** to Tera.
- Use the model's marked output **unchanged**: no manual overrides, no
  exception dictionary, no RUAccent pre-marking, no post-correction.
- If the model places a stress incorrectly, the error stays in the audio.
- `book2video stress` only prints the model's markup for inspection.

## Consequences

- One owner for accentuation, one place to improve: the model.
- No per-book stress maintenance, which would not scale to a shelf of books.
- A wrong stress is a model limitation, not a pipeline bug. Revisit only if the
  model changes or a backend without native accentuation is added.
