# Glossary

Domain language for `book2video`. Use these words in code, tests, docs and
reviews; do not invent synonyms for them.

## Content model

**Book** — one EPUB file after parsing. Holds the title, author and the list of
content **Chapters**. Front and back matter are not part of the Book.

**Chapter** — a content document selected from the EPUB spine. Has a stable
`index` (1-based, only content chapters), an optional printed `number`, a
`title`, and an ordered list of **Blocks**.

**Block** — the smallest unit the EPUB parser emits: `heading`, `paragraph`,
`sidebar`, `caption`, `footnote`, `image`, `table`, or `html_table`. A Block is
not narrated directly; the **Plan** turns most Blocks into **Segments** and
**Frames**.

**Sidebar** — a boxed passage (`vrez` / `vstavka`). Read in place, in an
opposite-gender **Voice**, never moved to an appendix.

**Caption** — the text attached to an image or table (`podris` / `tablpodp`).
It is read aloud and also anchors the corresponding **Frame**.

**Content chapter** — a Chapter that survived front/back-matter filtering.
Covers, title pages, copyright, TOC, dedications, about-the-author, notes,
indexes, promo pages, QR codes, age marks, logos and icons under ~64 px are not
content chapters and are never narrated.

## Narration and timing

**Segment** — one narrated unit: a heading, paragraph, sidebar, caption, or the
spoken form of a URL. Every Segment is synthesized separately, so its measured
duration gives an exact start time.

**Plan** — the ordered **Segments** and **Frames** for a set of Chapters, with
pauses, anchors and times. `plan_chapter` builds one; `plan_chapters` builds a
list; `assign_audio_times` fills in the clock.

**ChapterPlan** — the Plan for one Chapter: `segments`, `frames`, `start`,
`end`.

**Anchor** — the point in the narration where a Frame is introduced. Usually
the start of the caption Segment, or the start of the URL Segment for a QR
frame. A Frame without a caption anchors after the previous Segment.

**Area of influence** — the interval a Frame is on screen: from the midpoint
between its own Anchor and the previous Anchor, until the next Frame's cut. A
frame therefore owns the narration that follows its anchor, not a fixed
duration.

**Midpoint rule** — a cut happens at the midpoint between two Anchors. The
first Frame of a chapter cuts in at the chapter start; the last one stays until
the chapter end.

**Carry** — when a Chapter has no Frames, the previous Chapter's last Frame
stays on screen. Before the first illustration of the Book, a **blank frame**
(neutral paper) is used instead of a black screen.

**Frame** — one still shown in the video: `figure`, `table`, `html_table`, `qr`
or `blank`. It has an Anchor, a start, an end and an optional minimum hold.

**QR frame** — a Frame generated from an external URL. It is scheduled exactly
like a figure: it has its own Anchor and area of influence, and no fixed
maximum duration. The full URL is both the caption and the encoded content.

**Timeline JSON** — the machine-readable dump of every Segment and Frame with
its times and the frame file. Written to the **work directory**; useful for
debugging and for checking sync without watching the video.

## Audio

**Voice** — one of the ten TeraTTSv2 voice ids in `voices.py`. The **main
voice** narrates headings, paragraphs and captions. The **sidebar voice**
narrates Sidebars and defaults to the opposite-gender native voice.

**Chunk cache** — per-sentence WAV files keyed by model, voice and Tera's
marked text. Re-renders reuse them; changing the voice or the text creates new
entries.

**Narration WAV** — the assembled mono 44.1 kHz PCM16 file for the whole plan.
It is the single audio source for the MP4.

**Speed factor** — the multiplier applied after synthesis with ffmpeg
`atempo`. `1.2` is the default; `1.0` is natural speed. It is not a Tera
parameter.

**Work directory** — where segment audio, frame PNGs, `timeline.json`,
`frames.txt`, `metadata.txt` and `narration.wav` live. Rebuilding it is safe.

## Architecture

Architecture terms (**module**, **interface**, **seam**, **adapter**,
**depth**, **leverage**, **locality**) follow the `codebase-design` vocabulary.
A module is anything with an interface and an implementation; the interface is
everything a caller must know, not just the type signature.
