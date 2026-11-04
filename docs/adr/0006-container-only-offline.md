# ADR-0006: Container-only setup with an offline model cache

**Status:** accepted

## Context

The host must not need Python, ffmpeg, CUDA or a model install. The machine
that builds the books is not always online; Hugging Face may be unreachable
even when Docker can build from a local image.

## Decision

- The only host dependency is **Docker with Compose**.
- The image is CPU-only and contains ffmpeg, fonts, torch CPU and Tera's
  dependencies.
- The model lives in the `hf-cache` volume (`HF_HOME=/models/hf`); the chunk
  cache lives in `b2v-cache` (`BOOK2VIDEO_CACHE=/cache`).
- `compose.yaml` passes `HF_HUB_OFFLINE` and `TRANSFORMERS_OFFLINE` through.
  Set both to `1` to force cache-only operation.
- `Dockerfile.offline` rebuilds only the application code on top of a tagged
  base image, so an offline rebuild does not re-download torch:

  ```bash
  docker tag book2video:latest book2video:base
  docker build -f Dockerfile.offline -t book2video:latest .
  ```

- Books are mounted read-only at `/data`; output is `./out`.

## Consequences

- No host-level installs and reproducible dependencies.
- The first run needs network unless the cache volume is already populated.
- The offline rebuild path must be checked whenever the package layout or
  Python version changes.
