# Changelog

All notable changes are recorded here. The project follows a simple
`MAJOR.MINOR.PATCH` scheme; during early access, minor versions may change
command-line behaviour.

## 0.1.0 - 2026-11-07

First early-access source release.

### Added

- EPUB parsing and heuristic front/back-matter filtering.
- TeraTTSv2 narration on CPU with four native Russian voices and six English
  cross-lingual voices.
- Content-addressed TTS chunk cache and cached ffmpeg `atempo` output.
- Illustration, table, QR and blank frames with a minimum-hold scheduler.
- Link previews for Google Docs/Sheets/Slides, Yandex Disk, Yandex Docs,
  generic PDFs, images and HTML pages, with QR fallback and offline mode.
- Content-frame footer with compact URL, mini-QR and partial-item status.
- One MP4 per book with H.264/AAC, metadata and chapter markers.
- `voices`, `say`, `stress`, `inspect`, `links`, `build` and `clean-cache`
  commands.
- MIT license (`LICENSE`).
- 81 automated tests, including an end-to-end build with a fake TTS backend.

### Changed

- The implicit sidebar and annotation voice is now native Russian `ru_f2`
  instead of `ru_f1`; `ru_f1` was too shrill next to the male narrator on long
  listens. Explicit `--sidebar-voice` is unchanged. See
  [ADR-0010](docs/adr/0010-sidebar-voice.md).

### Fixed

- Books with hundreds of frames no longer exhaust container memory: renders
  are encoded in bounded chunks and joined losslessly. The 416-frame
  validation book previously died with `SIGKILL` after ffmpeg reached 13.4 GiB
  RSS.

### Validated

Four full-length Russian books were built at 2.0×, from 175.8 to 597.5
minutes, with 10 to 149 chapters. Audio/video delta stayed below 0.034 s and
every output carried the expected chapter markers. The books, audio, frames
and caches are not part of this release.
