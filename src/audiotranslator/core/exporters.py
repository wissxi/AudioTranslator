"""Writing results to text, subtitle and JSON files."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

from .. import APP_NAME, __version__
from ..languages import display_name
from .models import Segment, Transcript

FORMATS = ("txt", "srt", "vtt", "json")
REPORT_NAME = "translations.txt"
PARAGRAPH_GAP = 1.5  # seconds of silence that start a new paragraph

_LABELS = {
    "en": {
        "file": "File",
        "language": "Language",
        "duration": "Duration",
        "original": "Original",
        "translation": "Translation",
        "no_speech": "(no speech recognized)",
        "translation_failed": "(translation failed: {error})",
        "files": "files",
        "created": "Created",
    },
    "ru": {
        "file": "Файл",
        "language": "Язык",
        "duration": "Длительность",
        "original": "Оригинал",
        "translation": "Перевод",
        "no_speech": "(речь не распознана)",
        "translation_failed": "(перевод не удался: {error})",
        "files": "файлов",
        "created": "Создано",
    },
}


def labels(ui: str) -> dict[str, str]:
    return _LABELS.get(ui, _LABELS["en"])


# ------------------------------------------------------------------ helpers
def format_timestamp(seconds: float, separator: str = ",") -> str:
    """``3725.5`` → ``01:02:05,500`` (SRT) or ``01:02:05.500`` (VTT)."""
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def format_duration(seconds: float) -> str:
    seconds = round(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def paragraphs(segments: Sequence[Segment], field: str = "text") -> list[str]:
    """Join segments into paragraphs, breaking on long pauses."""
    result: list[str] = []
    current: list[str] = []
    previous_end: float | None = None
    for segment in segments:
        text = getattr(segment, field).strip()
        if not text:
            continue
        if current and previous_end is not None and segment.start - previous_end >= PARAGRAPH_GAP:
            result.append(" ".join(current))
            current = []
        current.append(text)
        previous_end = segment.end
    if current:
        result.append(" ".join(current))
    return result


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------- renderers
def render_srt(segments: Sequence[Segment], field: str = "text") -> str:
    blocks = []
    index = 0
    for segment in segments:
        text = getattr(segment, field).strip()
        if not text:
            continue
        index += 1
        start = format_timestamp(segment.start)
        end = format_timestamp(max(segment.end, segment.start + 0.2))
        blocks.append(f"{index}\n{start} --> {end}\n{text}\n")
    return "\n".join(blocks)


def render_vtt(segments: Sequence[Segment], field: str = "text") -> str:
    lines = ["WEBVTT", ""]
    for segment in segments:
        text = getattr(segment, field).strip()
        if not text:
            continue
        start = format_timestamp(segment.start, ".")
        end = format_timestamp(max(segment.end, segment.start + 0.2), ".")
        lines += [f"{start} --> {end}", text, ""]
    return "\n".join(lines)


def _section(transcript: Transcript, include_original: bool, ui: str) -> list[str]:
    lab = labels(ui)
    src = transcript.language
    out: list[str] = []
    translated = transcript.target_language and transcript.has_translation
    if not transcript.segments:
        return [lab["no_speech"], ""]
    if include_original or not translated:
        out += [f"{lab['original']} ({src.upper()}, {display_name(src, ui)}):", ""]
        out += [p + "\n" for p in paragraphs(transcript.segments, "text")]
    if transcript.target_language:
        dst = transcript.target_language
        out += [f"{lab['translation']} ({dst.upper()}, {display_name(dst, ui)}):", ""]
        if translated:
            out += [p + "\n" for p in paragraphs(transcript.segments, "translation")]
        else:
            out += [lab["translation_failed"].format(error=transcript.translation_error or "?"), ""]
    return out


def _header(transcript: Transcript, ui: str) -> list[str]:
    lab = labels(ui)
    lang = f"{display_name(transcript.language, ui)}"
    if transcript.target_language:
        lang += f" → {display_name(transcript.target_language, ui)}"
    return [
        f"{lab['file']}: {transcript.source.name}",
        f"{lab['language']}: {lang}",
        f"{lab['duration']}: {format_duration(transcript.duration)}",
    ]


def render_txt(transcript: Transcript, include_original: bool = True, ui: str = "en") -> str:
    lines = [*_header(transcript, ui), "", *_section(transcript, include_original, ui)]
    return "\n".join(lines).rstrip() + "\n"


def render_json(transcript: Transcript) -> str:
    data = {"generator": f"{APP_NAME} {__version__}", **transcript.to_dict()}
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def render_report(transcripts: Iterable[Transcript], include_original: bool = True, ui: str = "en") -> str:
    lab = labels(ui)
    items = list(transcripts)
    rule = "=" * 60
    out = [
        f"{APP_NAME} — {len(items)} {lab['files']}",
        f"{lab['created']}: {datetime.now():%Y-%m-%d %H:%M}",
        "",
    ]
    for transcript in items:
        out += [rule, *_header(transcript, ui), rule, ""]
        out += _section(transcript, include_original, ui)
    return "\n".join(out).rstrip() + "\n"


# ------------------------------------------------------------------- writers
def output_stem(transcript: Transcript, output_dir: Path | None) -> Path:
    folder = output_dir if output_dir else transcript.source.parent
    return folder / transcript.source.stem


def write_outputs(
    transcript: Transcript,
    formats: Iterable[str],
    output_dir: Path | None = None,
    include_original: bool = True,
    ui: str = "en",
) -> list[Path]:
    """Write the selected formats for one file and return the created paths."""
    stem = output_stem(transcript, output_dir)
    written: list[Path] = []
    translated = bool(transcript.target_language and transcript.has_translation)
    subtitle_tracks: list[tuple[str, str]] = []
    if translated:
        subtitle_tracks.append(("translation", transcript.target_language or ""))
    if include_original or not translated:
        subtitle_tracks.append(("text", transcript.language))

    for fmt in formats:
        if fmt == "txt":
            written.append(
                _write(stem.with_name(stem.name + ".txt"), render_txt(transcript, include_original, ui))
            )
        elif fmt == "json":
            written.append(_write(stem.with_name(stem.name + ".json"), render_json(transcript)))
        elif fmt in ("srt", "vtt") and transcript.segments:
            render = render_srt if fmt == "srt" else render_vtt
            for field, lang in subtitle_tracks:
                name = f"{stem.name}.{lang}.{fmt}"
                written.append(_write(stem.with_name(name), render(transcript.segments, field)))
    return written


def write_report(
    transcripts: Sequence[Transcript],
    folder: Path,
    include_original: bool = True,
    ui: str = "en",
) -> Path:
    return _write(folder / REPORT_NAME, render_report(transcripts, include_original, ui))


def common_folder(paths: Sequence[Path]) -> Path:
    """The deepest folder containing all ``paths`` (first file's folder across drives)."""
    folders = [str(p.parent) for p in paths]
    try:
        return Path(os.path.commonpath(folders))
    except ValueError:
        return paths[0].parent
