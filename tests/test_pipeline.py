import json
import threading
from pathlib import Path

from audiotranslator.core import pipeline as pl
from audiotranslator.core import translation as tr
from audiotranslator.core.pipeline import JobItem, JobOptions, Pipeline
from conftest import FakeTranscriber, write_wav


class Upper(tr.Provider):
    id = "upper"

    def translate_batch(self, lines, source, target):
        return [f"[{target}] {line.upper()}" for line in lines]


class Broken(tr.Provider):
    id = "broken"

    def translate_batch(self, lines, source, target):
        raise tr.TranslationError("quota_exceeded", "limit reached")


def run(tmp_path, monkeypatch, provider=Upper, transcriber=None, files=None, **opts):
    monkeypatch.setattr(pl, "make_chain", lambda *a, **k: [provider()])
    files = files or [write_wav(tmp_path / "a.wav"), write_wav(tmp_path / "b.wav")]
    events = []
    pipe = Pipeline(transcriber or FakeTranscriber(), events.append)
    options = JobOptions(**{"formats": ("txt", "srt", "json"), **opts})
    summary = pipe.run([JobItem(str(i), f) for i, f in enumerate(files)], options)
    return summary, events


def kinds(events):
    return [e["type"] for e in events]


def test_full_job(tmp_path, monkeypatch):
    summary, events = run(tmp_path, monkeypatch, target_language="ru", ui_language="en")
    assert summary.done == 2 and summary.failed == 0 and not summary.cancelled
    assert kinds(events)[:3] == ["job_started", "model_loading", "model_ready"]
    assert kinds(events)[-1] == "job_done"
    assert kinds(events).count("segment") == 6

    done = [e for e in events if e["type"] == "file_done"]
    assert done[0]["segments"][0]["translation"] == "[ru] HELLO THERE."
    names = sorted(Path(p).name for p in done[0]["outputs"])
    assert names == ["a.en.srt", "a.json", "a.ru.srt", "a.txt"]

    data = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    assert data["language"] == "en" and data["target_language"] == "ru"
    assert summary.report and (tmp_path / "translations.txt").exists()

    progress = [e["progress"] for e in events if e["type"] == "file_progress" and e["id"] == "0"]
    assert progress == sorted(progress)


def test_waveform_event(tmp_path, monkeypatch):
    _, events = run(tmp_path, monkeypatch)
    audio = [e for e in events if e["type"] == "file_audio"]
    assert len(audio) == 2 and audio[0]["duration"] > 0 and len(audio[0]["waveform"]) > 10


def test_no_translation(tmp_path, monkeypatch):
    summary, events = run(tmp_path, monkeypatch, target_language="", report=False)
    done = next(e for e in events if e["type"] == "file_done")
    assert done["target_language"] is None
    assert all(s["translation"] == "" for s in done["segments"])
    assert sorted(Path(p).name for p in done["outputs"]) == ["a.en.srt", "a.json", "a.txt"]
    assert summary.report is None


def test_same_language_skips_translation(tmp_path, monkeypatch):
    _, events = run(tmp_path, monkeypatch, target_language="en")
    assert any(e["type"] == "log" and e.get("code") == "same_language" for e in events)
    done = next(e for e in events if e["type"] == "file_done")
    assert done["target_language"] is None


def test_translation_failure_keeps_original(tmp_path, monkeypatch):
    summary, events = run(tmp_path, monkeypatch, provider=Broken, target_language="ru")
    assert summary.done == 2
    done = next(e for e in events if e["type"] == "file_done")
    assert done["translation_error"] == "limit reached"
    warnings = [e for e in events if e["type"] == "log" and e.get("code") == "quota_exceeded"]
    assert len(warnings) == 2
    assert (tmp_path / "a.en.srt").exists() and not (tmp_path / "a.ru.srt").exists()


def test_bad_file_does_not_stop_the_job(tmp_path, monkeypatch):
    bad = tmp_path / "bad.mp3"
    bad.write_text("not audio")
    good = write_wav(tmp_path / "good.wav")
    summary, events = run(tmp_path, monkeypatch, files=[bad, good])
    assert summary.done == 1 and summary.failed == 1
    errors = [e for e in events if e["type"] == "file_error"]
    assert errors[0]["id"] == "0" and errors[0]["error"]["code"] in ("decode_failed", "no_audio")


def test_custom_output_dir(tmp_path, monkeypatch):
    out = tmp_path / "results"
    summary, _ = run(tmp_path, monkeypatch, output_dir=str(out))
    assert (out / "a.txt").exists() and (out / "translations.txt").exists()
    assert summary.report == str(out / "translations.txt")


def test_cancel_mid_job(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(pl, "make_chain", lambda *a, **k: [Upper()])
    pipe = Pipeline(FakeTranscriber(), events.append)

    def listener(event):
        events.append(event)
        if event["type"] == "segment":
            pipe.cancel()

    pipe.emit = listener
    files = [write_wav(tmp_path / "a.wav"), write_wav(tmp_path / "b.wav")]
    summary = pipe.run([JobItem(str(i), f) for i, f in enumerate(files)], JobOptions())
    assert summary.cancelled and summary.done == 0
    assert "file_cancelled" in kinds(events)
    assert events[-1]["type"] == "job_done" and events[-1]["cancelled"] is True
    assert not (tmp_path / "a.txt").exists()
    assert not (tmp_path / "translations.txt").exists()


def test_model_error_stops_job(tmp_path, monkeypatch):
    from audiotranslator.errors import ModelError

    class NoModel(FakeTranscriber):
        def load(self, *a, **k):
            raise ModelError("model_download_failed", "offline")

    summary, events = run(tmp_path, monkeypatch, transcriber=NoModel())
    assert summary.failed == 2 and summary.done == 0
    assert any(e["type"] == "job_error" and e["error"]["code"] == "model_download_failed" for e in events)


def test_job_options_from_dict():
    options = JobOptions.from_dict({"model": "tiny", "formats": ["srt", "bogus"], "theme": "dark"})
    assert options.model == "tiny" and options.formats == ("srt",)


def test_pipeline_is_reusable_after_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "make_chain", lambda *a, **k: [Upper()])
    pipe = Pipeline(FakeTranscriber())
    pipe.cancel()
    summary = pipe.run([JobItem("0", write_wav(tmp_path / "a.wav"))], JobOptions(formats=()))
    assert summary.done == 1


def test_events_from_worker_thread(tmp_path, monkeypatch):
    """The GUI runs jobs on a thread; make sure nothing assumes the main thread."""
    monkeypatch.setattr(pl, "make_chain", lambda *a, **k: [Upper()])
    events = []
    pipe = Pipeline(FakeTranscriber(), events.append)
    worker = threading.Thread(
        target=pipe.run, args=([JobItem("0", write_wav(tmp_path / "a.wav"))], JobOptions())
    )
    worker.start()
    worker.join(10)
    assert events[-1]["type"] == "job_done" and events[-1]["done"] == 1
