"""Speech recognition with faster-whisper (CTranslate2).

* Models are downloaded once into the app data folder, with progress.
* A CUDA GPU is used when available; any CUDA problem falls back to CPU.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..errors import Cancelled, ModelError
from .models import Segment

log = logging.getLogger(__name__)

# Hugging Face Hub: no telemetry, no console progress bars (a windowed exe has no console).
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
# The Hub sends an "unauthenticated requests" notice on every download; it is not actionable here.
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)


@dataclass(frozen=True)
class ModelInfo:
    name: str
    size_mb: int
    speed: int  # 1 (slow) … 5 (fast)
    accuracy: int  # 1 (rough) … 5 (best)


MODELS: tuple[ModelInfo, ...] = (
    ModelInfo("tiny", 75, 5, 1),
    ModelInfo("base", 145, 5, 2),
    ModelInfo("small", 485, 4, 3),
    ModelInfo("medium", 1530, 2, 4),
    ModelInfo("large-v3-turbo", 1620, 3, 4),
    ModelInfo("large-v3", 3100, 1, 5),
)
MODEL_BY_NAME = {m.name: m for m in MODELS}
DEFAULT_MODEL = "small"

ProgressFn = Callable[[float], None]
StopFn = Callable[[], bool]


@dataclass
class Recognition:
    segments: list[Segment]
    language: str
    language_probability: float
    duration: float


def cuda_device_count() -> int:
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


def _looks_like_cuda_failure(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(word in text for word in ("cuda", "cublas", "cudnn", "gpu", "nvrtc"))


def _folder_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


class Transcriber:
    """Loads one Whisper model at a time and keeps it cached between jobs."""

    def __init__(self, models_dir: Path) -> None:
        self.models_dir = Path(models_dir)
        self._model = None
        self._key: tuple[str, str] | None = None
        self._cuda_broken = False
        self.device = "cpu"
        self.compute_type = "int8"
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- models
    @staticmethod
    def repo_id(name: str) -> str:
        from faster_whisper.utils import _MODELS

        return _MODELS.get(name, name)

    def _repo_cache(self, name: str) -> Path:
        return self.models_dir / ("models--" + self.repo_id(name).replace("/", "--"))

    def is_downloaded(self, name: str) -> bool:
        from faster_whisper.utils import download_model

        if not self._repo_cache(name).exists():
            return False
        try:
            download_model(name, cache_dir=str(self.models_dir), local_files_only=True)
            return True
        except Exception:
            return False

    def ensure_model(
        self,
        name: str,
        on_progress: ProgressFn | None = None,
        should_stop: StopFn | None = None,
    ) -> str:
        """Return the local model path, downloading it first if needed."""
        from faster_whisper.utils import download_model

        if name not in MODEL_BY_NAME:
            raise ModelError("unknown_model", f"Unknown model: {name}", model=name)
        try:
            return download_model(name, cache_dir=str(self.models_dir), local_files_only=True)
        except Exception:
            pass

        log.info("Downloading model %s", name)
        result: dict = {}
        done = threading.Event()

        def worker() -> None:
            try:
                result["path"] = download_model(name, cache_dir=str(self.models_dir))
            except Exception as exc:  # network, disk, HTTP errors
                result["error"] = exc
            finally:
                done.set()

        threading.Thread(target=worker, name=f"download-{name}", daemon=True).start()
        # huggingface_hub keeps blobs in a shared folder, so measure the whole cache growing.
        expected = MODEL_BY_NAME[name].size_mb * 1024 * 1024
        baseline = _folder_size(self.models_dir)
        while not done.wait(0.4):
            if should_stop and should_stop():
                # The download keeps going in the background and resumes next time.
                raise Cancelled()
            if on_progress:
                grown = _folder_size(self.models_dir) - baseline
                on_progress(max(0.0, min(grown / expected, 0.99)))

        if "error" in result:
            exc = result["error"]
            raise ModelError(
                "model_download_failed", f"Could not download model {name}: {exc}", model=name
            ) from exc
        if on_progress:
            on_progress(1.0)
        return result["path"]

    def load(
        self,
        name: str,
        device: str = "auto",
        on_download: ProgressFn | None = None,
        should_stop: StopFn | None = None,
    ) -> None:
        with self._lock:
            key = (name, device)
            if self._model is not None and self._key == key:
                return
            path = self.ensure_model(name, on_download, should_stop)
            self._model = None

            from faster_whisper import WhisperModel

            want_gpu = device == "cuda" or (device == "auto" and cuda_device_count() > 0)
            if want_gpu and not self._cuda_broken:
                try:
                    self._model = WhisperModel(path, device="cuda", compute_type="float16")
                    self.device, self.compute_type = "cuda", "float16"
                except Exception as exc:
                    log.warning("GPU unavailable, using CPU: %s", exc)
                    self._cuda_broken = True
            if self._model is None:
                try:
                    self._model = WhisperModel(path, device="cpu", compute_type="int8")
                except Exception as exc:
                    raise ModelError("model_load_failed", f"Could not load model {name}: {exc}") from exc
                self.device, self.compute_type = "cpu", "int8"
            self._key = key
            log.info("Model %s ready on %s (%s)", name, self.device, self.compute_type)

    # ------------------------------------------------------------ recognition
    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        vad: bool = True,
        on_segment: Callable[[Segment, float], None] | None = None,
        should_stop: StopFn | None = None,
    ) -> Recognition:
        if self._model is None:
            raise ModelError("model_not_loaded", "Model is not loaded")
        try:
            return self._run(audio, language, vad, on_segment, should_stop)
        except Cancelled:
            raise
        except Exception as exc:
            if self.device != "cuda" or not _looks_like_cuda_failure(exc):
                raise
            # Missing cuBLAS/cuDNN only shows up on the first real inference.
            log.warning("GPU failed during recognition, retrying on CPU: %s", exc)
            self._cuda_broken = True
            name = self._key[0] if self._key else "small"
            self._key = None
            self.load(name, "cpu")
            return self._run(audio, language, vad, on_segment, should_stop)

    def _run(self, audio, language, vad, on_segment, should_stop) -> Recognition:
        segments_iter, info = self._model.transcribe(
            audio,
            language=language or None,
            vad_filter=vad,
            beam_size=5,
            condition_on_previous_text=False,
        )
        duration = float(info.duration or (audio.size / 16_000) or 1.0)
        segments: list[Segment] = []
        for raw in segments_iter:
            if should_stop and should_stop():
                raise Cancelled()
            text = raw.text.strip()
            if not text:
                continue
            segment = Segment(start=float(raw.start), end=float(raw.end), text=text)
            segments.append(segment)
            if on_segment:
                on_segment(segment, min(segment.end / duration, 1.0))
        return Recognition(
            segments=segments,
            language=info.language,
            language_probability=float(info.language_probability or 0.0),
            duration=duration,
        )

    @property
    def gpu_available(self) -> bool:
        return cuda_device_count() > 0 and not self._cuda_broken
