# ADR-0007: Content filtering is heuristic and EPUB-specific

**Status:** accepted

## Context

Books from different publishers use different class names and document
structure. Narrating covers, copyright pages, TOCs, notes, indexes, promo pages
or decorative logos would add noise and break the "illustrations only" rule.
A generic EPUB library does not know which documents are content.

## Decision

`epub.py` parses the spine directly and classifies documents with explicit
heuristics:

- keep the introduction and everything after it; drop short front-matter pages
  before the first numbered chapter;
- drop documents whose title matches back matter (acknowledgements, about the
  author, notes, bibliography, index, promo, series);
- drop documents with too little text, too many footnotes, or a copyright/promo
  signature;
- drop title-only documents by merging them into the following body;
- drop images whose name marks them as decorative (`logo`, `icon`, `cover`,
  `emblem`, `qr`) or whose smaller side is under 64 px;
- classify boxed paragraphs (`vrez` / `vstavka`) as sidebars and caption
  classes (`podris`, `tablpodp`) as captions;
- treat external links as narration only when they are deictic or long enough
  to need a QR frame.

## Consequences

- The parser is intentionally publisher-specific; a new publisher may need a
  new class name or rule.
- A wrong heuristic can silently drop a chapter. `inspect` and the manual
  acceptance gate exist to catch that before a full build.
- Synthetic EPUB fixtures pin each rule; add one when a real book exposes a
  new pattern. Do not commit copyrighted books as fixtures.
