"""Finding media files and decoding their audio.

Decoding uses PyAV, which ships its own FFmpeg libraries, so users do not
need to install FFmpeg separately.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from ..errors import MediaError

SAMPLE_RATE = 16_000

AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wma", ".aif", ".aiff", ".amr"}
)
VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".m4v", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".flv", ".3gp", ".ts", ".mts", ".mpg", ".mpeg"}
)
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


def is_media(path: str | os.PathLike) -> bool:
    return Path(path).suffix.lower() in MEDIA_EXTENSIONS


def media_kind(path: str | os.PathLike) -> str:
    return "video" if Path(path).suffix.lower() in VIDEO_EXTENSIONS else "audio"


def natural_key(text: str) -> list:
    """Sort key that puts ``part 2`` before ``part 10``."""
    return [int(chunk) if chunk.isdigit() else chunk.casefold() for chunk in re.split(r"(\d+)", text)]


def collect_media(paths: Iterable[str | os.PathLike], recursive: bool = True) -> list[Path]:
    """Expand files and folders into a de-duplicated list of media files.

    Files keep the order they were given in; files found inside a folder are
    sorted naturally by their path relative to that folder.
    """
    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            found.append(path)

    for raw in paths:
        if not raw:
            continue
        path = Path(raw).expanduser()
        try:
            path = path.resolve()
        except OSError:
            continue
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            inner = [p for p in path.glob(pattern) if p.is_file() and is_media(p)]
            inner.sort(key=lambda p: natural_key(str(p.relative_to(path))))
            for item in inner:
                add(item)
        elif path.is_file() and is_media(path):
            add(path)
    return found


def probe_duration(path: str | os.PathLike) -> float | None:
    """Return the media duration in seconds, or ``None`` if it is unknown."""
    import av

    try:
        with av.open(str(path)) as container:
            if container.duration:
                return container.duration / 1_000_000
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is not None and stream.duration and stream.time_base:
                return float(stream.duration * stream.time_base)
    except Exception:
        return None
    return None


def decode_audio(path: str | os.PathLike, sampling_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Decode the first audio track to mono float32 PCM at ``sampling_rate``."""
    import av

    path = Path(path)
    if not path.is_file():
        raise MediaError("file_not_found", f"File not found: {path}", path=str(path))

    resampler = av.AudioResampler(format="s16", layout="mono", rate=sampling_rate)
    chunks: list[np.ndarray] = []
    try:
        with av.open(str(path)) as container:
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is None:
                raise MediaError("no_audio", f"No audio track in {path.name}", path=str(path))
            stream.thread_type = "AUTO"
            for frame in container.decode(stream):
                for out in resampler.resample(frame):
                    chunks.append(out.to_ndarray())
            for out in resampler.resample(None):
                chunks.append(out.to_ndarray())
    except MediaError:
        raise
    except Exception as exc:  # PyAV raises many specific error types
        raise MediaError("decode_failed", f"Cannot decode {path.name}: {exc}", path=str(path)) from exc

    if not chunks:
        raise MediaError("no_audio", f"No audio data in {path.name}", path=str(path))
    audio = np.concatenate(chunks, axis=1).reshape(-1)
    return audio.astype(np.float32) / 32768.0


def waveform_peaks(audio: np.ndarray, bins: int = 360) -> list[float]:
    """Downsample audio to ``bins`` normalized peak values for drawing a waveform."""
    if audio.size == 0 or bins <= 0:
        return []
    bins = min(bins, audio.size)
    usable = audio[: audio.size - audio.size % bins]
    blocks = np.abs(usable.reshape(bins, -1))
    # 95th percentile per block reads better than the raw max (clicks dominate otherwise)
    peaks = np.percentile(blocks, 95, axis=1)
    top = float(peaks.max()) or 1.0
    return [round(float(v) / top, 3) for v in peaks]
