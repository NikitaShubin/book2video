# Agent map

`book2video` turns Russian EPUB books into narrated MP4 videos. Read
[README.md](README.md) first, then:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — data flow, modules, seams and
  known friction. Read before changing scheduling, parsing or rendering.
- [docs/GLOSSARY.md](docs/GLOSSARY.md) — use these words for Book, Chapter,
  Block, Segment, Frame, Anchor, Plan.
- [docs/AUDIO.md](docs/AUDIO.md) — TTS, cache, loudness, atempo and assembly.
- [docs/TESTING.md](docs/TESTING.md) — `make test`, the fake backend, and the
  manual chapter gate before a full-book build.
- [docs/RELEASE.md](docs/RELEASE.md) — release scope, artifact contents,
  validation record and the media-exclusion checklist.
- [docs/adr/0011-nvidia-acceleration.md](docs/adr/0011-nvidia-acceleration.md)
  — optional CUDA/NVENC path and its CPU fallback.
- [CHANGELOG.md](CHANGELOG.md) — user-visible changes per version.
- [docs/adr/](docs/adr/) — accepted decisions. Do not re-litigate one without
  saying so.
- [CODING_STANDARDS.md](CODING_STANDARDS.md) — review judgement calls.

Commands:

```bash
make test       # unit + integration tests in the container
make check      # tests + CLI help
make image      # rebuild after changing src/
make image-gpu  # rebuild the optional NVIDIA image
make doctor     # show CUDA/NVENC availability inside the container
make inspect BOOK="/data/book.epub"
make pilot BOOK="/data/book.epub" CHAPTER=4
```

Rules:

- The host has Docker only. Run Python through `docker compose run`.
- Tests run against the installed package: rebuild the image after `src/`
  changes.
- Do not commit EPUBs, MP4/WAV files, `out/`, caches or `__pycache__`.
- The only time-stretch is ffmpeg `atempo`; Tera `duration_scale` and
  `rubberband` are rejected decisions.
- Do not start a full-book build before one chapter passes the listening gate.
