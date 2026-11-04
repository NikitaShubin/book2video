# Coding standards

This file is for reviewers. Mechanical rules are enforced by `make check` and
by the module boundaries; the points below are judgement calls that no linter
can make.

## Before reviewing

Read [docs/GLOSSARY.md](docs/GLOSSARY.md) and the ADRs for the area you touch.
If a change contradicts an ADR, say so explicitly; do not silently re-litigate
the decision.

## Module boundaries

- Product policy lives in the module that names it. Illustration rules go in
  `timeline.py`, content-selection rules in `epub.py`, speech text rules in
  `normalize.py`, ffmpeg argument construction in `render.py` or `speed.py`.
  `build.py` only orchestrates.
- A module's interface is what callers must know: signatures, invariants,
  ordering, error modes. Keep it small. If a caller needs a private helper,
  the helper belongs in the module's public interface or the caller is in the
  wrong place.
- Do not add an abstraction for a single adapter. The synthesis backend is
  duck-typed on purpose; a protocol or base class arrives when a second
  production backend does.
- New I/O (network, subprocess, filesystem) belongs at an adapter seam, not in
  a pure scheduler or parser.

## Code

- Match the surrounding style: 4-space indent, type hints on public functions,
  `from __future__ import annotations`, module docstrings that explain *why*.
- Russian text is data, not UI copy. Do not translate it, do not add stress
  marks, do not "fix" the author's wording in normalisation.
- Error messages should name the input and the expected shape. A failure in a
  two-hour build must be diagnosable from the log line alone.
- Prefer returning a value over mutating a caller's object. The existing
  exceptions are the planning data structures (`Segment`, `Frame`,
  `ChapterPlan`), which are filled in place by design.
- Comments explain constraints (why a midpoint, why float32), not restate the
  code.

## Tests

- Every bug fix gets a regression test at the seam where the bug occurred.
- Tests must not need the model, the network, or a copyrighted book. Use
  synthetic EPUBs and the fake backend.
- A test that only checks "it did not crash" is not a test. Assert the
  observable result: a duration, a cut time, a chapter title, a codec.
- If a rule cannot be tested without reaching past the interface, report that
  as a design problem instead of importing a private helper.

## Repository hygiene

- Do not commit books, audio, video, model caches or work directories. See
  `.gitignore`.
- Do not commit generated metadata, logs or screenshots.
- Keep the README commands in sync with `book2video --help`.
- The only supported speed path is ffmpeg `atempo`. `duration_scale` and
  `rubberband` are rejected decisions; do not reintroduce them without a new
  ADR and a fresh listening test.

## Review output

State findings as: file, what is wrong, why it matters, and the smallest fix.
Distinguish a bug from a preference. If the code is correct but the design
friction is real, record it in the architecture review rather than blocking
the change.
