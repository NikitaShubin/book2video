# ADR-0008: Link previews, with QR as the fallback

**Status:** accepted

## Context

Every external link used to become a spoken URL plus a QR frame. A QR code is
reliable but it asks the viewer to pick up a phone for something the video
could show directly: the first page of a document, the first slide, or the top
of a web page. A full-screen preview is also more useful than a QR when the
video is watched on a TV or a second monitor.

At the same time, a preview must never turn a book build into a fetch-and-render
exercise that fails on one bad URL. Captchas, logins, dead links and unsupported
file types are normal on the web.

## Decision

- Every external link except a footnote gets a spoken sentence and a frame.
- Resolve each unique HTTP(S) URL once per book, before planning.
- If an adapter produces a still, render a **content frame**: dark surround,
  preview `contain`, compact URL and a mini-QR in the footer. A full item has no
  status line; a partial one reports its page count or `первый экран`.
- Otherwise render the existing **QR frame** with the full URL.
- A failed fetch or an unsupported type is a QR frame, never a build failure.
- Use narrow adapters: Google Docs/Sheets/Slides PDF export, Yandex Disk and
  Yandex Docs, generic PDF via poppler, images, HTML via Playwright. Everything
  else is a QR.
- HTTP(S) only, 20 s timeout, 50 MB limit, at most five redirects.
- No captcha, login, cookie-wall or SSRF heuristic. The EPUB is trusted; show
  whatever was captured.
- Cache previews per book under `<work>/links/<sha256(url)>/`. The cache is
  read and populated on every run.
- `--offline-links` makes the cache the only source. A miss is a QR and no
  network request is made.
- No date is printed on any frame.
- An explicitly supplied `--sidebar-voice` is used for the annotation even if
  it is a whisper voice; the implicit default is the opposite-gender native
  voice.

## Consequences

- Builds now depend on network access unless `--offline-links` is used.
- The image needs `poppler-utils` and a Playwright Chromium build.
- A URL can produce a "wrong" capture whose site text is misleading. That is
  accepted: the QR is always on the frame, and the alternative is no preview.
- Preview failures are not cached, so a transient failure can succeed on the
  next run.
- The annotation voice doubles as the sidebar voice, so a book with both
  sidebars and links uses one extra voice.
- `links` is a deep module: a few calls hide provider policy, rendering, HTTP
  limits and caching. New providers belong there, not in `build`.
