# ADR-0009: Frame timing with a minimum hold and mention preference

**Status:** accepted

**Supersedes:** [ADR-0005](0005-midpoint-frame-scheduling.md) for scheduling.
ADR-0005 still defines QR-as-a-normal-frame and carry/blank frames.

## Context

ADR-0005 cut every frame at the midpoint between its anchor and the previous
anchor. That is good for pictures introduced mid-paragraph, but it broke down
with many frames in one chapter:

- a frame could appear after its mention had already been read;
- a short chapter could give a frame a fraction of a second;
- a QR or content frame had no guaranteed time to be read;
- extending the audio to reach a minimum hold changed the narration rhythm.

## Decision

Schedule frames inside one chapter with these rules, in order:

1. If `chapter_duration < frame_hold * frame_count`, shorten **all** frames
   equally to `chapter_duration / frame_count`. No frame is privileged.
2. Otherwise start from the natural midpoint between neighbouring anchors and
   spread a run of frames that share one anchor evenly.
3. Project the boundaries so every frame holds at least `frame_hold`
   (`--frame-hold`, default 8 s).
4. Prefer each mention to be inside its own frame with at least
   `frame_hold / 2` seconds after it starts. If that is impossible, make the
   smallest deviation. Surplus time fills the natural midpoint area up to the
   chapter bounds.
5. The first frame cuts in at the chapter start, the last one runs to the
   chapter end, and the screen is never blank inside a chapter that has a
   frame.
6. A frame never crosses a chapter boundary.

Frame minimums are not inserted into the narration audio. The scheduler uses
the measured post-atempo durations, so audio, frames and chapter markers stay
aligned without artificial pauses.

## Consequences

- `timeline` is still pure: durations in, frame times out.
- A chapter with fewer than `8 * N` seconds of narration shows each frame for
  an equal, possibly short, slice rather than dropping frames.
- The scheduler is monotone and deterministic; tests pin the equal-shortening
  case, the minimum-hold case and the mention preference.
- `--table-hold` is gone. Tables, figures, QR frames and content frames share
  `--frame-hold`, which keeps the policy explainable.
