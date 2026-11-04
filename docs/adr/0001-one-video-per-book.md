# ADR-0001: One long MP4 per book, illustrations only

**Status:** accepted

## Context

The source books are text with figures, tables and sidebars. The output is
meant to be watched like a narrated slide deck, not like a video adaptation.
Splitting a book into many files makes it awkward to resume or cast; adding
subtitles or on-screen titles duplicates the narration and distracts from the
figures.

## Decision

- Produce **one MP4 per book**.
- Show **illustrations only**: static frames, hard cuts, 16:9, aspect ratio
  preserved, white canvas.
- **No subtitles**, no burned-in chapter titles, no logos, no motion effects.
- Read headings and captions; do not display them as text overlays.
- Appendices stay in the same file, after the last content chapter.
- Write MP4 metadata and one chapter marker per content chapter.

## Consequences

- The renderer is a still-image concat job, not a video editor. Frame timing is
  the only thing that matters.
- Long books produce large files; `+faststart` and chapter markers make them
  easier to navigate.
- A chapter without illustrations must inherit a frame rather than show black,
  otherwise the "illustrations only" rule leaves a gap.
