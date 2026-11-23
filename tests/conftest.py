from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from audiotranslator.core.models import Segment
from audiotranslator.core.transcriber import Recognition

DATA = Path(__file__).parent / "data"


def pytest_addoption(parser):
    parser.addoption("--slow", action="store_true", help="run tests that download a Whisper model")


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: downloads a model and runs real recognition")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--slow"):
        return
    skip = pytest.mark.skip(reason="needs --slow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def app_home(tmp_path, monkeypatch):
    """Keep settings and models of every test inside a temporary folder."""
    home = tmp_path / "home"
    monkeypatch.setenv("AUDIOTRANSLATOR_HOME", str(home))
    return home


def write_wav(path: Path, seconds: float = 1.0, rate: int = 44_100, freq: float = 440.0) -> Path:
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    tone = (0.4 * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2")
    stereo = np.stack([tone, tone], axis=1)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(stereo.tobytes())
    return path


@pytest.fixture
def wav_file(tmp_path) -> Path:
    return write_wav(tmp_path / "tone.wav", seconds=1.5)


class FakeTranscriber:
    """Stands in for Whisper: returns fixed segments, honours cancellation."""

    def __init__(self, segments=None, language="en"):
        self.segments = (
            segments
            if segments is not None
            else [
                (0.0, 2.0, "Hello there."),
                (2.5, 5.0, "This is a test."),
                (8.0, 9.5, "Goodbye."),
            ]
        )
        self.language = language
        self.device = "cpu"
        self.compute_type = "int8"
        self.loaded = None
        self.calls = 0

    def is_downloaded(self, name):
        return True

    def load(self, name, device="auto", on_download=None, should_stop=None):
        self.loaded = (name, device)

    def transcribe(self, audio, language=None, vad=True, on_segment=None, should_stop=None):
        from audiotranslator.errors import Cancelled

        self.calls += 1
        out = []
        for start, end, text in self.segments:
            if should_stop and should_stop():
                raise Cancelled()
            seg = Segment(start, end, text)
            out.append(seg)
            if on_segment:
                on_segment(seg, end / 10)
        return Recognition(out, language or self.language, 0.99, 10.0)
