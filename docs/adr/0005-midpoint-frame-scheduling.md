# ADR-0005: Midpoint scheduling, QR as a normal frame

**Status:** superseded by [ADR-0009](0009-frame-timing.md) for scheduling.
The QR-as-a-normal-frame and carry/blank rules remain in force.

## Context

Figures and tables are introduced in the text. If a frame cut immediately at
the introducing sentence, the illustration would appear while the previous
thought is still being read. A fixed duration for QR codes made them disappear
before the listener could scan them on a long link explanation, and made short
links hold the screen too long.

## Decision

- Anchor every frame to the Segment that introduces it.
- Cut at the **midpoint between its anchor and the previous anchor**; the first
  frame of a chapter cuts in at the chapter start.
- The frame stays until the next frame's cut. That interval is its **area of
  influence**.
- A **QR frame is a normal frame**: own anchor, own area of influence, no fixed
  maximum duration. Its caption and encoded content are the full URL.
- A chapter with no frames carries the previous chapter's last frame. Before
  the first illustration, show a neutral blank frame.
- A run of images sharing one anchor is spread evenly so none is skipped.
- Tables hold for at least `--table-hold` seconds.
- Appendices are part of the same timeline and end up at the tail.

## Consequences

- Timing depends on measured narration durations, not on sentence counts.
- `timeline` is a pure scheduling module and can be tested without audio.
- `render` must close gaps between chapters so the screen is never blank.
- Frames with no caption anchor after the previous Segment, not at the chapter
  start.
