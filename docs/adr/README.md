# Architecture decision records

Accepted decisions for `book2video`. Read the one for the area you are
changing before proposing an alternative; if you want to revisit one, say so
explicitly and write a new ADR that supersedes it.

| ADR | Decision |
| --- | --- |
| [0001](0001-one-video-per-book.md) | One long MP4 per book, illustrations only, static frames, chapter markers |
| [0002](0002-terattsv2.md) | TeraTTSv2 as the local CPU TTS backend |
| [0003](0003-ffmpeg-atempo.md) | ffmpeg `atempo` is the only time-scaling method; Tera and rubberband rejected |
| [0004](0004-tera-stress-as-is.md) | Tera's stress output is accepted as-is |
| [0005](0005-midpoint-frame-scheduling.md) | Midpoint cuts, QR as a normal frame, carry and blank frames (scheduling superseded by 0009) |
| [0006](0006-container-only-offline.md) | Container-only setup with offline model and chunk caches |
| [0007](0007-content-filtering.md) | Heuristic, EPUB-specific front/back-matter filtering |
| [0008](0008-link-previews.md) | Link previews replace QR when renderable; QR is the fallback |
| [0009](0009-frame-timing.md) | Minimum frame hold, equal shortening, mention preference |
| [0010](0010-sidebar-voice.md) | Lower-pitch native `ru_f2` for sidebars and annotations |
| [0011](0011-nvidia-acceleration.md) | Optional NVIDIA GPU: CUDA TTS and NVENC encoding, CPU fallback |
