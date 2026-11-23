"""Runs a batch job: decode → recognize → translate → save, file by file.

Progress is reported through ``emit(event: dict)`` so the same pipeline can
drive the desktop interface and the command line.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from ..errors import AppError, Cancelled
from . import exporters
from .media import decode_audio, waveform_peaks
from .models import Transcript
from .transcriber import DEFAULT_MODEL, Transcriber
from .translation import Translator, make_chain

log = logging.getLogger(__name__)

Emit = Callable[[dict[str, Any]], None]

# Share of a file's progress bar given to each stage.
_DECODE, _RECOGNIZE, _TRANSLATE = 0.04, 0.80, 0.14


@dataclass
class JobOptions:
    model: str = DEFAULT_MODEL
    device: str = "auto"  # auto | cpu | cuda
    source_language: str = ""  # "" = detect automatically
    target_language: str = "ru"  # "" = no translation
    provider: str = "google"
    deepl_key: str = ""
    fallback: bool = True
    formats: tuple[str, ...] = ("txt", "srt")
    report: bool = True
    include_original: bool = True
    output_dir: str = ""  # "" = next to each source file
    vad: bool = True
    ui_language: str = "ru"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobOptions:
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in (data or {}).items() if k in known}
        if "formats" in values:
            values["formats"] = tuple(f for f in values["formats"] if f in exporters.FORMATS)
        return cls(**values)


@dataclass
class JobItem:
    id: str
    path: Path


@dataclass
class JobSummary:
    done: int = 0
    failed: int = 0
    cancelled: bool = False
    outputs: list[str] = field(default_factory=list)
    report: str | None = None
    elapsed: float = 0.0
    transcripts: list[Transcript] = field(default_factory=list)


class Pipeline:
    def __init__(self, transcriber: Transcriber, emit: Emit | None = None) -> None:
        self.transcriber = transcriber
        self.emit: Emit = emit or (lambda event: None)
        self._stop = threading.Event()

    # ----------------------------------------------------------------- control
    def cancel(self) -> None:
        self._stop.set()

    @property
    def cancelled(self) -> bool:
        return self._stop.is_set()

    def _event(self, kind: str, **data: Any) -> None:
        try:
            self.emit({"type": kind, **data})
        except Exception:  # a broken listener must never kill the job
            log.exception("Event listener failed")

    # --------------------------------------------------------------------- run
    def run(self, items: Sequence[JobItem], options: JobOptions) -> JobSummary:
        self._stop.clear()
        summary = JobSummary()
        started = time.monotonic()
        output_dir = Path(options.output_dir).expanduser() if options.output_dir else None
        self._event("job_started", total=len(items), ids=[item.id for item in items])

        try:
            self._load_model(options)
            for index, item in enumerate(items):
                if self.cancelled:
                    raise Cancelled()
                transcript = self._process(item, index, len(items), options, output_dir, summary)
                if transcript is not None:
                    summary.transcripts.append(transcript)
        except Cancelled:
            summary.cancelled = True
        except AppError as exc:
            # Model problems stop the whole job; per-file errors are handled in _process.
            self._event("job_error", error=exc.to_dict())
            summary.failed = len(items) - summary.done

        if options.report and summary.transcripts and not summary.cancelled:
            folder = output_dir or exporters.common_folder([t.source for t in summary.transcripts])
            try:
                report = exporters.write_report(
                    summary.transcripts, folder, options.include_original, options.ui_language
                )
                summary.report = str(report)
                summary.outputs.append(str(report))
            except OSError as exc:
                self._event("log", level="error", code="write_failed", message=str(exc))

        summary.elapsed = time.monotonic() - started
        self._event(
            "job_done",
            done=summary.done,
            failed=summary.failed,
            cancelled=summary.cancelled,
            outputs=summary.outputs,
            report=summary.report,
            elapsed=round(summary.elapsed, 1),
        )
        return summary

    def _load_model(self, options: JobOptions) -> None:
        name = options.model
        downloaded = self.transcriber.is_downloaded(name)
        self._event("model_loading", model=name, downloading=not downloaded)

        def on_download(fraction: float) -> None:
            self._event("model_download", model=name, progress=round(fraction, 3))

        self.transcriber.load(name, options.device, on_download, lambda: self.cancelled)
        self._event(
            "model_ready",
            model=name,
            device=self.transcriber.device,
            compute_type=self.transcriber.compute_type,
        )

    def _process(
        self,
        item: JobItem,
        index: int,
        total: int,
        options: JobOptions,
        output_dir: Path | None,
        summary: JobSummary,
    ) -> Transcript | None:
        fid = item.id
        last_emit = 0.0

        def progress(stage: str, value: float, force: bool = False) -> None:
            nonlocal last_emit
            now = time.monotonic()
            if force or now - last_emit > 0.12:
                last_emit = now
                self._event("file_progress", id=fid, stage=stage, progress=round(min(value, 1.0), 4))

        self._event("file_started", id=fid, index=index, total=total, name=item.path.name)
        try:
            progress("decoding", 0, force=True)
            audio = decode_audio(item.path)
            duration = audio.size / 16_000
            self._event("file_audio", id=fid, duration=round(duration, 2), waveform=waveform_peaks(audio))
            if self.cancelled:
                raise Cancelled()

            translate = bool(options.target_language)
            recog_share = _RECOGNIZE + (0 if translate else _TRANSLATE)

            def on_segment(segment, fraction):
                self._event("segment", id=fid, **segment.to_dict())
                progress("recognizing", _DECODE + recog_share * fraction)

            progress("recognizing", _DECODE, force=True)
            result = self.transcriber.transcribe(
                audio,
                language=options.source_language or None,
                vad=options.vad,
                on_segment=on_segment,
                should_stop=lambda: self.cancelled,
            )
            del audio
            transcript = Transcript(
                source=item.path,
                language=result.language,
                language_probability=result.language_probability,
                duration=result.duration,
                segments=result.segments,
            )
            self._event(
                "file_language",
                id=fid,
                language=result.language,
                probability=round(result.language_probability, 3),
            )

            if translate and transcript.segments:
                self._translate(transcript, options, fid, progress)

            progress("saving", 0.99, force=True)
            outputs = exporters.write_outputs(
                transcript,
                options.formats,
                output_dir,
                options.include_original,
                options.ui_language,
            )
            summary.done += 1
            summary.outputs.extend(str(p) for p in outputs)
            self._event(
                "file_done",
                id=fid,
                language=transcript.language,
                target_language=transcript.target_language,
                provider=transcript.translation_provider,
                translation_error=transcript.translation_error,
                segments=[s.to_dict() for s in transcript.segments],
                outputs=[str(p) for p in outputs],
                duration=round(transcript.duration, 2),
            )
            return transcript
        except Cancelled:
            self._event("file_cancelled", id=fid)
            raise
        except AppError as exc:
            if exc.code in ("model_load_failed", "model_download_failed", "model_not_loaded"):
                raise
            summary.failed += 1
            self._event("file_error", id=fid, error=exc.to_dict())
        except OSError as exc:
            summary.failed += 1
            self._event("file_error", id=fid, error={"code": "write_failed", "message": str(exc)})
        except Exception as exc:  # keep going with the next file
            log.exception("Unexpected error while processing %s", item.path)
            summary.failed += 1
            self._event("file_error", id=fid, error={"code": "unexpected", "message": str(exc)})
        return None

    def _translate(self, transcript: Transcript, options: JobOptions, fid: str, progress) -> None:
        target = options.target_language
        if transcript.language == target:
            self._event("log", level="info", code="same_language", id=fid, language=target)
            return
        transcript.target_language = target
        translator = Translator(
            make_chain(options.provider, options.deepl_key, options.fallback),
            stop_event=self._stop,
        )
        start = _DECODE + _RECOGNIZE
        progress("translating", start, force=True)
        try:
            lines = [s.text for s in transcript.segments]
            translated = translator.translate(
                lines,
                transcript.language,
                target,
                on_progress=lambda f: progress("translating", start + _TRANSLATE * f),
            )
        except AppError as exc:
            transcript.translation_error = exc.message
            self._event("log", level="warning", code=exc.code, id=fid, message=exc.message)
            return
        for segment, text in zip(transcript.segments, translated, strict=False):
            segment.translation = text
        transcript.translation_provider = translator.used_provider
        if translator.warnings:
            self._event(
                "log",
                level="warning",
                code="provider_fallback",
                id=fid,
                provider=translator.used_provider,
                message="; ".join(translator.warnings),
            )
