"""Command-line interface: ``audiotranslator-cli lecture.mp3 -t ru -f srt,txt``."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from . import __version__
from .core import JobItem, JobOptions, Pipeline, Transcriber
from .core.exporters import FORMATS, format_duration
from .core.media import collect_media
from .core.transcriber import DEFAULT_MODEL, MODELS
from .core.translation import PROVIDERS
from .languages import LANGUAGES, display_name, is_supported
from .paths import models_dir


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="audiotranslator-cli",
        description="Recognize speech in audio/video files and translate it.",
        epilog="Example: audiotranslator-cli ./lectures -t ru -f txt,srt -m small",
    )
    p.add_argument("inputs", nargs="*", help="files or folders to process")
    p.add_argument("-t", "--to", default="ru", metavar="LANG", help="target language code (default: ru)")
    p.add_argument(
        "-s", "--from", dest="source", default="", metavar="LANG", help="spoken language (default: auto)"
    )
    p.add_argument("--no-translate", action="store_true", help="only transcribe, do not translate")
    p.add_argument("-m", "--model", default=DEFAULT_MODEL, choices=[m.name for m in MODELS])
    p.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    p.add_argument("-f", "--formats", default="txt,srt", help=f"comma-separated: {','.join(FORMATS)}")
    p.add_argument(
        "-o", "--output", default="", metavar="DIR", help="output folder (default: next to each file)"
    )
    p.add_argument("--provider", default="google", choices=PROVIDERS, help="translation service")
    p.add_argument(
        "--deepl-key", default=os.environ.get("DEEPL_API_KEY", ""), help="DeepL key (or DEEPL_API_KEY)"
    )
    p.add_argument("--no-fallback", action="store_true", help="do not switch to another service on failure")
    p.add_argument("--no-report", action="store_true", help="skip the combined translations.txt")
    p.add_argument("--no-original", action="store_true", help="leave the original text out of outputs")
    p.add_argument("--no-vad", action="store_true", help="disable silence filtering")
    p.add_argument("--no-recursive", action="store_true", help="do not look into subfolders")
    p.add_argument("--lang", default="en", choices=["en", "ru"], help="language of labels in text files")
    p.add_argument("--list-models", action="store_true", help="show available models and exit")
    p.add_argument("--list-languages", action="store_true", help="show language codes and exit")
    p.add_argument("-q", "--quiet", action="store_true", help="print only errors and the summary")
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return p


class ConsoleReporter:
    def __init__(self, quiet: bool) -> None:
        self.quiet = quiet
        self.live = sys.stdout.isatty()
        self.names: dict[str, str] = {}
        self.line_open = False

    def _line(self, text: str, final: bool = False) -> None:
        if self.quiet or (not final and not self.live):
            return
        if not self.live:
            print(text.strip())
            return
        width = 100
        sys.stdout.write("\r" + text[:width].ljust(width if self.line_open else 0))
        if final:
            sys.stdout.write("\n")
        sys.stdout.flush()
        self.line_open = not final

    def _break(self) -> None:
        if self.line_open:
            self._line("", True)

    def __call__(self, event: dict) -> None:
        kind = event["type"]
        if kind == "model_loading":
            what = "Downloading" if event["downloading"] else "Loading"
            self._line(f"{what} model {event['model']}…")
        elif kind == "model_download":
            self._line(f"Downloading model {event['model']}: {event['progress'] * 100:5.1f}%")
        elif kind == "model_ready":
            self._line(
                f"Model {event['model']} ready on {event['device'].upper()} ({event['compute_type']})", True
            )
        elif kind == "file_started":
            self.names[event["id"]] = event["name"]
            self._line(f"[{event['index'] + 1}/{event['total']}] {event['name']}")
        elif kind == "file_progress":
            name = self.names.get(event["id"], "")
            self._line(f"  {name}: {event['stage']} {event['progress'] * 100:5.1f}%")
        elif kind == "file_done":
            name = self.names.get(event["id"], "")
            lang = display_name(event["language"])
            if event.get("target_language"):
                lang += f" → {display_name(event['target_language'])}"
            self._line(f"  ✓ {name} ({lang}, {format_duration(event['duration'])})", True)
            if event.get("translation_error"):
                print(f"    ! translation failed: {event['translation_error']}", file=sys.stderr)
            if not self.quiet:
                for path in event["outputs"]:
                    print(f"    → {path}")
        elif kind == "file_error":
            name = self.names.get(event["id"], "")
            self._break()
            print(f"  ✗ {name}: {event['error']['message']}", file=sys.stderr)
        elif kind == "job_error":
            self._break()
            print(f"Error: {event['error']['message']}", file=sys.stderr)
        elif kind == "log" and event.get("level") in ("warning", "error"):
            self._break()
            print(f"  ! {event.get('message') or event.get('code')}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # never crash on "✓" in a legacy Windows code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if args.list_models:
        print(f"{'model':<16}{'download':>10}  speed  accuracy")
        for m in MODELS:
            print(f"{m.name:<16}{m.size_mb:>7} MB  {'●' * m.speed:<5}  {'●' * m.accuracy}")
        return 0
    if args.list_languages:
        for lang in LANGUAGES:
            print(f"{lang.code:<4}{lang.en}")
        return 0
    if not args.inputs:
        build_parser().print_usage(sys.stderr)
        print("error: give at least one file or folder", file=sys.stderr)
        return 2

    target = "" if args.no_translate else args.to.lower()
    for code in filter(None, (target, args.source.lower())):
        if not is_supported(code):
            print(f"error: unsupported language '{code}' (see --list-languages)", file=sys.stderr)
            return 2
    formats = tuple(f.strip().lower() for f in args.formats.split(",") if f.strip())
    unknown = [f for f in formats if f not in FORMATS]
    if unknown:
        print(f"error: unknown format(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    files = collect_media(args.inputs, recursive=not args.no_recursive)
    if not files:
        print("error: no audio or video files found", file=sys.stderr)
        return 1

    options = JobOptions(
        model=args.model,
        device=args.device,
        source_language=args.source.lower(),
        target_language=target,
        provider=args.provider,
        deepl_key=args.deepl_key,
        fallback=not args.no_fallback,
        formats=formats,
        report=not args.no_report,
        include_original=not args.no_original,
        output_dir=args.output,
        vad=not args.no_vad,
        ui_language=args.lang,
    )
    pipeline = Pipeline(Transcriber(models_dir()), ConsoleReporter(args.quiet))
    items = [JobItem(id=str(i), path=Path(f)) for i, f in enumerate(files)]
    started = time.monotonic()
    try:
        summary = pipeline.run(items, options)
    except KeyboardInterrupt:
        pipeline.cancel()
        print("\nStopped.", file=sys.stderr)
        return 130
    print(
        f"\nDone: {summary.done} of {len(items)} file(s), "
        f"{summary.failed} failed, {time.monotonic() - started:.1f}s"
    )
    if summary.report:
        print(f"Report: {summary.report}")
    return 0 if summary.failed == 0 and not summary.cancelled else 1


if __name__ == "__main__":
    sys.exit(main())
