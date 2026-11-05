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

**Segment** — one narrated unit: a heading, paragraph, sidebar, caption, the
spoken form of a URL, or a link annotation. Every Segment is synthesized
separately, so its measured duration gives an exact start time.

**Link** — an external HTTP(S) reference found inside a Block. Footnote links
are not Links for narration. Every other unique URL gets a link Segment and a
**Frame**.

**Link preview** (`LinkPreview`) — a still captured for a Link: the first page
of a PDF, the first slide, the first screen of a site, or an image. It carries
`kind`, `title`, `page_count`, `full`, the image path, and derives the footer
**status** and the **annotation**.

**Content frame** — a Frame that shows a Link preview in the dark content
layout: preview `contain`, compact URL and mini-QR in the footer. A **full**
preview has no status; a **partial** one says how much is on screen.

**QR frame** — the fallback Frame for a Link with no preview. The full URL is
both the caption and the encoded content. It is scheduled like any other
frame.

**Annotation** — the short sentence read by the annotation voice after the
spoken URL: «На экране документ „X“» for a full document,
«…, страница 1 из N, остальное по ссылке» for a partial one, «На экране первый
экран сайта, остальное по ссылке» for a site, «На экране изображение» for an
image.

**Frame hold** — the minimum time a Frame should stay on screen
(`--frame-hold`, default 8 s). Inside one Chapter, if the narration is long
enough every Frame gets at least one hold; otherwise all Frames are shortened
equally.

**Mention** — the Segment that introduces a Frame (a caption or a spoken URL).
The scheduler prefers the mention to sit inside its own frame with at least
half a hold after it starts, and minimises deviation when that is impossible.

**Plan** — the ordered **Segments** and **Frames** for a set of Chapters, with
pauses, anchors and times. `plan_chapter` builds one; `plan_chapters` builds a
list; `assign_audio_times` fills in the clock.

**ChapterPlan** — the Plan for one Chapter: `segments`, `frames`, `start`,
`end`.

**Anchor** — the point in the narration where a Frame is introduced. Usually
the start of the caption Segment, or the start of the URL Segment for a link
frame. A Frame without a caption anchors after the previous Segment.

**Area of influence** — the interval a Frame is on screen, computed by the
frame scheduler. It starts at the natural cut between neighbouring Anchors and
is then adjusted for the Frame hold and the mention preference. A frame owns
the narration around its anchor, not a fixed duration.

**Frame** — one still shown in the video: `figure`, `table`, `html_table`,
`qr`, `content` or `blank`. It has an Anchor, a start, an end, an optional
minimum hold and, for `content`, a `LinkPreview`.

**Carry** — when a Chapter has no Frames, the previous Chapter's last Frame
stays on screen. Before the first illustration of the Book, a **blank frame**
(neutral paper) is used instead of a black screen.

**Timeline JSON** — the machine-readable dump of every Segment and Frame with
its times and the frame file. Written to the **work directory**; useful for
debugging and for checking sync without watching the video.

## Audio

**Voice** — one of the ten TeraTTSv2 voice ids in `voices.py`. The **main
voice** narrates headings, paragraphs, captions and compressed URLs. The
**sidebar voice** narrates Sidebars and annotations and defaults to the
opposite-gender native voice. An explicit `--sidebar-voice` is always obeyed,
including a whisper voice.

**Annotation voice** — the voice used for the **Annotation** after a spoken
URL. It is the sidebar voice.

**Chunk cache** — per-sentence WAV files keyed by model, voice and Tera's
marked text. Re-renders reuse them; changing the voice or the text creates new
entries.

**Narration WAV** — the assembled mono 44.1 kHz PCM16 file for the whole plan.
It is the single audio source for the MP4.

**Speed factor** — the multiplier applied after synthesis with ffmpeg
`atempo`. `1.2` is the default; `1.0` is natural speed. It is not a Tera
parameter.

**Work directory** — where segment audio, link previews, frame PNGs,
`timeline.json`, `frames.txt`, `metadata.txt` and `narration.wav` live.
Rebuilding derived files is safe; the `audio/` and `links/` caches make
re-runs cheap.

## Architecture

Architecture terms (**module**, **interface**, **seam**, **adapter**,
**depth**, **leverage**, **locality**) follow the `codebase-design` vocabulary.
A module is anything with an interface and an implementation; the interface is
everything a caller must know, not just the type signature.
