"""End-to-end recognition with a real Whisper model (run with ``pytest --slow``).

The sample is John F. Kennedy's 1961 inaugural address (public domain).
"""

import pytest

from audiotranslator.core import JobItem, JobOptions, Pipeline, Transcriber
from audiotranslator.paths import models_dir
from conftest import DATA

pytestmark = pytest.mark.slow


def test_tiny_model_recognizes_jfk(tmp_path):
    sample = tmp_path / "jfk.mp3"
    sample.write_bytes((DATA / "jfk.mp3").read_bytes())
    events = []
    pipeline = Pipeline(Transcriber(models_dir()), events.append)
    options = JobOptions(model="tiny", device="cpu", target_language="", formats=("srt",), report=False)
    summary = pipeline.run([JobItem("1", sample)], options)

    assert summary.done == 1, events
    done = next(e for e in events if e["type"] == "file_done")
    text = " ".join(s["text"] for s in done["segments"]).lower()
    assert done["language"] == "en"
    assert "ask not what your country can do for you" in text
    assert (tmp_path / "jfk.en.srt").exists()
