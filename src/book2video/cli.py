"""Command line interface for book2video."""

from __future__ import annotations

import argparse
from pathlib import Path

from .voices import TERA_VOICES, VOICE_IDS, get_voice


def _cmd_voices(args: argparse.Namespace) -> int:
    print(f"{'id':<18} {'lang':<5} {'gender':<7} description")
    print("-" * 72)
    for voice in TERA_VOICES:
        print(f"{voice.id:<18} {voice.language:<5} {voice.gender:<7} {voice.description}")
    return 0


def _cmd_say(args: argparse.Namespace) -> int:
    from .speed import apply_speed
    from .tts.tera import TeraBackend

    get_voice(args.voice)  # validate early
    backend = TeraBackend(provider=args.provider, threads=args.threads)
    out = Path(args.out).expanduser()
    if abs(args.speed - 1.0) < 1e-6:
        backend.synthesize(args.text, voice=args.voice, out_path=out)
    else:
        natural = out.with_name(f".{out.stem}.natural.wav")
        backend.synthesize(args.text, voice=args.voice, out_path=natural)
        apply_speed(natural, out, args.speed)
        natural.unlink(missing_ok=True)
    print(out)
    return 0


def _cmd_stress(args: argparse.Namespace) -> int:
    from .tts.tera import TeraBackend

    backend = TeraBackend(provider=args.provider, threads=args.threads)
    print(backend.mark_text(args.text))
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    from .epub import load_book

    book = load_book(args.epub)
    try:
        print(f"{book.title} — {book.author}")
        for chapter in book.chapters:
            images = sum(1 for b in chapter.blocks if b.kind in {"image", "table"})
            sidebars = sum(1 for b in chapter.blocks if b.kind == "sidebar")
            print(
                f"{chapter.index:3d}  n={str(chapter.number):>4}  "
                f"blocks={len(chapter.blocks):4d}  images={images:3d}  "
                f"boxes={sidebars:3d}  chars={len(chapter.text):7d}  {chapter.title}"
            )
        if args.blocks:
            from .epub import select_chapter

            chapter = select_chapter(book, args.blocks)
            print(f"\n--- {chapter.title}")
            for index, block in enumerate(chapter.blocks):
                extra = ""
                if block.image:
                    extra += f" img={block.image}"
                if block.links:
                    extra += " links=" + ",".join(link.href for link in block.links)
                print(
                    f"{index:03d} {block.kind:10s} box={int(block.box)} "
                    f"level={block.level} :: {block.text[:110]!r}{extra}"
                )
        return 0
    finally:
        book.close()


def _cmd_build(args: argparse.Namespace) -> int:
    from .build import build

    build(
        args.epub,
        args.out,
        chapter=None if args.all else args.chapter,
        all_chapters=args.all,
        voice=args.voice,
        sidebar_voice=args.sidebar_voice,
        work_dir=args.work_dir,
        provider=args.provider,
        threads=args.threads,
        table_min_hold=args.table_hold,
        speed=args.speed,
        crf=args.crf,
        preset=args.preset,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="book2video",
        description="Turn Russian EPUB books into narrated MP4 videos.",
    )
    parser.add_argument("--provider", default="CPUExecutionProvider",
                        help="ONNX provider for TeraTTSv2 (default: CPUExecutionProvider)")
    parser.add_argument("--threads", type=int, default=None,
                        help="ONNX threads for TeraTTSv2")

    sub = parser.add_subparsers(dest="command", required=True)

    p_voices = sub.add_parser("voices", help="list available TeraTTSv2 voices")
    p_voices.set_defaults(func=_cmd_voices)

    p_say = sub.add_parser("say", help="synthesize a single phrase (smoke test)")
    p_say.add_argument("text")
    p_say.add_argument("--voice", default="ru_m5", choices=VOICE_IDS)
    p_say.add_argument("--speed", type=float, default=1.2,
                       help="speech rate multiplier (1.0 = natural, default 1.2)")
    p_say.add_argument("--out", default="out.wav")
    p_say.set_defaults(func=_cmd_say)

    p_stress = sub.add_parser("stress", help="show Tera's own stress markup")
    p_stress.add_argument("text")
    p_stress.set_defaults(func=_cmd_stress)

    p_inspect = sub.add_parser("inspect", help="show chapters and parsed blocks")
    p_inspect.add_argument("epub")
    p_inspect.add_argument("--blocks", default=None,
                           help="chapter number to dump block by block")
    p_inspect.set_defaults(func=_cmd_inspect)

    p_build = sub.add_parser("build", help="build a video from an EPUB")
    p_build.add_argument("epub")
    p_build.add_argument("--out", default="out.mp4")
    p_build.add_argument("--chapter", default=None,
                         help="chapter number or title fragment (default: first)")
    p_build.add_argument("--all", action="store_true",
                         help="build every content chapter into one video")
    p_build.add_argument("--voice", default="ru_m5", choices=VOICE_IDS)
    p_build.add_argument("--sidebar-voice", default=None, choices=VOICE_IDS)
    p_build.add_argument("--work-dir", default=None,
                         help="directory for audio, frames and timeline.json")
    p_build.add_argument("--table-hold", type=float, default=8.0,
                         help="minimum seconds a table stays on screen")
    p_build.add_argument("--speed", type=float, default=1.2,
                         help="speech rate multiplier (1.0 = natural, default 1.2)")
    p_build.add_argument("--crf", type=int, default=20)
    p_build.add_argument("--preset", default="medium")
    p_build.set_defaults(func=_cmd_build)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
