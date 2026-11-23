import json

import pytest

from audiotranslator import cli
from audiotranslator.settings import Settings


# ---------------------------------------------------------------- settings
def test_defaults_are_valid(app_home):
    s = Settings.load()
    assert s.model == "small" and s.target_language == "ru"
    assert s.ui_language in ("ru", "en")


def test_normalize_rejects_bad_values():
    s = Settings().update(
        {
            "model": "huge",
            "device": "tpu",
            "source_language": "xx",
            "target_language": "zz",
            "provider": "bing",
            "formats": ["srt", "srt", "pdf", "txt"],
            "theme": "neon",
            "ui_language": "de",
            "unknown": 1,
        }
    )
    assert s.model == "small" and s.device == "auto"
    assert s.source_language == "" and s.target_language == "ru"
    assert s.provider == "google" and s.formats == ["srt", "txt"]
    assert s.theme == "system" and s.ui_language in ("ru", "en")


def test_update_coerces_types():
    s = Settings().update({"vad": 0, "output_dir": None, "formats": None})
    assert s.vad is False and s.output_dir == "" and s.formats == []


def test_save_and_load_roundtrip(app_home):
    s = Settings().update({"model": "tiny", "target_language": "de", "ui_language": "en"})
    s.save()
    again = Settings.load()
    assert (again.model, again.target_language, again.ui_language) == ("tiny", "de", "en")


def test_corrupt_settings_file_is_ignored(app_home):
    app_home.mkdir(parents=True, exist_ok=True)
    (app_home / "settings.json").write_text("{not json", encoding="utf-8")
    assert Settings.load().model == "small"


# --------------------------------------------------------------------- CLI
def test_cli_lists(capsys):
    assert cli.main(["--list-models"]) == 0
    assert "large-v3-turbo" in capsys.readouterr().out
    assert cli.main(["--list-languages"]) == 0
    assert "ru  Russian" in capsys.readouterr().out


def test_cli_rejects_bad_input(tmp_path, capsys):
    assert cli.main([]) == 2
    assert cli.main([str(tmp_path), "-t", "xx"]) == 2
    assert cli.main([str(tmp_path), "-f", "pdf"]) == 2
    assert cli.main([str(tmp_path)]) == 1
    assert "no audio or video files" in capsys.readouterr().err


def test_cli_runs_pipeline(tmp_path, monkeypatch, capsys):
    from audiotranslator.core import pipeline as pl
    from conftest import FakeTranscriber, write_wav

    class Upper:
        id = "upper"
        max_chars = 4500
        max_items = 100
        min_interval = 0

        def measure(self, text):
            return len(text)

        def translate_batch(self, lines, source, target):
            return [line.upper() for line in lines]

    monkeypatch.setattr(pl, "make_chain", lambda *a, **k: [Upper()])
    monkeypatch.setattr(cli, "Transcriber", lambda *_: FakeTranscriber())
    write_wav(tmp_path / "talk.wav")
    code = cli.main([str(tmp_path), "-t", "de", "-f", "srt", "--no-original", "--no-report", "-q"])
    assert code == 0
    assert (tmp_path / "talk.de.srt").read_text(encoding="utf-8").count("HELLO THERE.") == 1
    assert "Done: 1 of 1" in capsys.readouterr().out


# ------------------------------------------------------------------ bridge
@pytest.fixture
def bridge(app_home):
    from audiotranslator.app import Bridge

    return Bridge()


def test_bridge_init(bridge):
    info = bridge.init()
    assert info["version"]
    assert next(m["name"] for m in info["models"]) == "tiny"
    assert all(m["downloaded"] is False for m in info["models"])
    assert {"code": "ru", "en": "Russian", "ru": "Русский", "native": "Русский"} in info["languages"]
    json.dumps(info)  # must be serializable for the page


def test_bridge_save_settings(bridge, app_home):
    saved = bridge.save_settings({"target_language": "de", "formats": ["vtt"]})
    assert saved["target_language"] == "de" and saved["formats"] == ["vtt"]
    assert json.loads((app_home / "settings.json").read_text(encoding="utf-8"))["target_language"] == "de"


def test_bridge_add_paths(bridge, tmp_path):
    from conftest import write_wav

    write_wav(tmp_path / "a.wav")
    (tmp_path / "readme.txt").write_text("x")
    infos = bridge.add_paths([str(tmp_path)])
    assert [i["name"] for i in infos] == ["a.wav"]
    assert infos[0]["kind"] == "audio" and infos[0]["duration"] == pytest.approx(1.0, abs=0.05)
    assert infos[0]["id"] == bridge.add_paths([str(tmp_path / "a.wav")])[0]["id"]


def test_bridge_does_not_expose_internals(bridge):
    public = {name for name in dir(bridge) if not name.startswith("_")}
    assert public == {
        "init",
        "ready",
        "save_settings",
        "pick_files",
        "pick_folder",
        "pick_output_dir",
        "add_paths",
        "start",
        "cancel",
        "reveal",
        "open_path",
        "open_url",
        "set_theme",
    }


def test_bridge_start_runs_job_and_emits(bridge, tmp_path, monkeypatch):
    from conftest import FakeTranscriber, write_wav

    events = []
    bridge._transcriber = FakeTranscriber()
    bridge._emit = events.append
    bridge.save_settings({"target_language": "", "formats": ["txt"], "report": False})
    path = write_wav(tmp_path / "a.wav")
    assert bridge.start([{"id": "x", "path": str(path)}]) == {"ok": True}
    bridge._thread.join(10)
    assert events[-1]["type"] == "job_done" and events[-1]["done"] == 1
    assert (tmp_path / "a.txt").exists()
    assert bridge.start([]) == {"ok": False, "error": "empty"}


def test_bridge_start_applies_page_settings(bridge, tmp_path):
    from conftest import FakeTranscriber, write_wav

    bridge._transcriber = FakeTranscriber()
    bridge._emit = lambda event: None
    path = write_wav(tmp_path / "a.wav")
    page = {**bridge.init()["settings"], "target_language": "", "formats": ["json"], "report": False}
    assert bridge.start([{"id": "x", "path": str(path)}], page) == {"ok": True}
    bridge._thread.join(10)
    assert (tmp_path / "a.json").exists() and not (tmp_path / "a.txt").exists()


def test_bridge_open_url_only_web(bridge, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    bridge.open_url("file:///etc/passwd")
    bridge.open_url("https://github.com/wissxi/AudioTranslator")
    assert opened == ["https://github.com/wissxi/AudioTranslator"]
