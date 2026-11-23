"""Desktop window: a native webview hosting the HTML interface, plus the JS ↔ Python bridge."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from . import APP_NAME, REPO_URL, __version__
from .core import MODELS, JobItem, JobOptions, Pipeline, Transcriber
from .core.media import MEDIA_EXTENSIONS, collect_media, media_kind, probe_duration
from .core.transcriber import cuda_device_count
from .languages import as_dicts
from .paths import log_file, models_dir, web_dir
from .settings import Settings

log = logging.getLogger(__name__)

DARK_BG = "#161922"
LIGHT_BG = "#EEF0F4"


def file_info(path: Path) -> dict[str, Any]:
    """Describe a media file for the queue."""
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    return {
        "id": hashlib.sha1(os.path.normcase(str(path)).encode("utf-8")).hexdigest()[:12],
        "path": str(path),
        "name": path.name,
        "kind": media_kind(path),
        "size": size,
        "duration": probe_duration(path),
    }


def system_prefers_dark() -> bool:
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
        except OSError:
            return True
    return True


def open_with_system(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class Bridge:
    """Methods callable from JavaScript as ``window.pywebview.api.<name>()``.

    Attributes starting with an underscore are not exposed to the page.
    """

    def __init__(self) -> None:
        self._window = None
        self._settings = Settings.load()
        self._transcriber = Transcriber(models_dir())
        self._pipeline: Pipeline | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._drop_registered = False

    # ------------------------------------------------------------ plumbing
    def _attach(self, window) -> None:
        self._window = window
        window.events.loaded += self._on_loaded
        window.events.closing += self._on_closing

    def _emit(self, event: dict[str, Any]) -> None:
        if self._window is None:
            return
        payload = json.dumps(event, ensure_ascii=True, default=str)
        try:
            self._window.run_js(f"window.AT && window.AT.receive({payload})")
        except Exception:
            log.debug("Could not deliver event %s", event.get("type"), exc_info=True)

    def _on_loaded(self) -> None:
        if self._drop_registered:
            return
        try:
            from webview.dom import DOMEventHandler

            self._window.dom.document.events.drop += DOMEventHandler(self._on_drop, True, False)
            self._drop_registered = True
        except Exception:
            log.warning("Drag and drop is unavailable", exc_info=True)

    def _on_drop(self, event: dict) -> None:
        files = (event.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths:
            self._emit({"type": "files_added", "files": self._infos(paths)})

    def _on_closing(self) -> None:
        if self._pipeline is not None:
            self._pipeline.cancel()

    def _infos(self, paths: list[str]) -> list[dict[str, Any]]:
        return [file_info(p) for p in collect_media(paths, recursive=self._settings.recursive)]

    # --------------------------------------------------------- page API
    def init(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "settings": self._settings.to_dict(),
            "languages": as_dicts(),
            "models": [
                {
                    "name": m.name,
                    "size_mb": m.size_mb,
                    "speed": m.speed,
                    "accuracy": m.accuracy,
                    "downloaded": self._transcriber.is_downloaded(m.name),
                }
                for m in MODELS
            ],
            "gpu": cuda_device_count() > 0,
            "platform": sys.platform,
            "models_dir": str(models_dir()),
            "repo_url": REPO_URL,
        }

    def ready(self) -> None:
        log.info("Interface ready")

    def save_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        self._settings.update(patch or {})
        try:
            self._settings.save()
        except OSError:
            log.exception("Could not save settings")
        return self._settings.to_dict()

    def pick_files(self) -> list[dict[str, Any]]:
        import webview

        patterns = ";".join(f"*{ext}" for ext in sorted(MEDIA_EXTENSIONS))
        label = "Аудио и видео" if self._settings.ui_language == "ru" else "Audio and video"
        all_files = "Все файлы" if self._settings.ui_language == "ru" else "All files"
        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=True,
            file_types=(f"{label} ({patterns})", f"{all_files} (*.*)"),
        )
        return self._infos(list(result or []))

    def pick_folder(self) -> list[dict[str, Any]] | None:
        import webview

        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not result:
            return None
        return self._infos([result[0] if isinstance(result, (list, tuple)) else result])

    def pick_output_dir(self) -> str | None:
        import webview

        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else result

    def add_paths(self, paths: list[str]) -> list[dict[str, Any]]:
        return self._infos(list(paths or []))

    def start(self, items: list[dict[str, str]]) -> dict[str, Any]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return {"ok": False, "error": "busy"}
            job = [JobItem(id=str(i["id"]), path=Path(i["path"])) for i in items or [] if i.get("path")]
            if not job:
                return {"ok": False, "error": "empty"}
            options = JobOptions.from_dict(self._settings.to_dict())
            self._pipeline = Pipeline(self._transcriber, self._emit)
            self._thread = threading.Thread(
                target=self._run, args=(self._pipeline, job, options), name="job", daemon=True
            )
            self._thread.start()
            return {"ok": True}

    def _run(self, pipeline: Pipeline, job: list[JobItem], options: JobOptions) -> None:
        try:
            pipeline.run(job, options)
        except Exception as exc:  # last line of defence: the UI must leave the running state
            log.exception("Job crashed")
            self._emit({"type": "job_error", "error": {"code": "unexpected", "message": str(exc)}})
            self._emit({"type": "job_done", "done": 0, "failed": len(job), "cancelled": False, "outputs": []})

    def cancel(self) -> None:
        if self._pipeline is not None:
            self._pipeline.cancel()

    def reveal(self, path: str) -> None:
        """Show a file in the system file manager (or open the folder)."""
        if not path:
            return
        target = Path(path)
        try:
            if sys.platform == "win32" and target.is_file():
                subprocess.Popen(["explorer", "/select,", str(target)])
            elif sys.platform == "darwin" and target.exists():
                subprocess.Popen(["open", "-R", str(target)])
            else:
                open_with_system(str(target if target.is_dir() else target.parent))
        except OSError:
            log.exception("Could not reveal %s", path)

    def open_path(self, path: str) -> None:
        if path and Path(path).exists():
            try:
                open_with_system(path)
            except OSError:
                log.exception("Could not open %s", path)

    def open_url(self, url: str) -> None:
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            webbrowser.open(url)

    def set_theme(self, dark: bool) -> None:
        """Match the Windows title bar to the interface theme."""
        if sys.platform != "win32" or self._window is None:
            return
        try:
            import ctypes

            hwnd = int(self._window.native.Handle.ToInt64())
            value = ctypes.c_int(1 if dark else 0)
            # DWMWA_USE_IMMERSIVE_DARK_MODE is 20 on current Windows builds, 19 on early Windows 10.
            for attribute in (20, 19):
                ok = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
                )
                if ok == 0:
                    break
        except Exception:
            log.debug("Could not theme the title bar", exc_info=True)


def setup_logging() -> None:
    # A windowed build has no console: give libraries somewhere harmless to print.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    handler = RotatingFileHandler(log_file(), maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"


def show_fatal(message: str) -> None:
    """Last-resort error dialog when the window itself cannot be created."""
    log.error(message)
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    else:
        print(message, file=sys.stderr)


def self_test(argv: list[str]) -> int:
    """Check a (frozen) build without opening a window; used by CI.

    ``AudioTranslator --self-test speech.mp3 --report result.json [--model tiny]``
    """
    import argparse

    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("--self-test", required=True, metavar="MEDIA")
    parser.add_argument("--report", required=True)
    parser.add_argument("--model", default="tiny")
    args = parser.parse_args(argv)
    result: dict[str, Any] = {"version": __version__, "ok": False}
    try:
        result["web"] = (web_dir() / "index.html").is_file()
        from .core.media import decode_audio

        audio = decode_audio(args.self_test)
        result["samples"] = int(audio.size)
        transcriber = Transcriber(models_dir())
        transcriber.load(args.model, "cpu")
        recognition = transcriber.transcribe(audio)
        result["language"] = recognition.language
        result["text"] = " ".join(s.text for s in recognition.segments)
        import webview

        result["webview"] = webview.__name__
        if sys.platform == "win32":
            import webview.platforms.winforms  # loads pythonnet + WebView2 assemblies

            result["gui"] = "winforms"
        result["ok"] = result["web"] and bool(result["text"])
    except Exception as exc:
        log.exception("Self-test failed")
        result["error"] = repr(exc)
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


def main() -> int:
    setup_logging()
    if "--self-test" in sys.argv:
        return self_test(sys.argv[1:])
    import webview

    log.info("%s %s starting", APP_NAME, __version__)
    bridge = Bridge()
    theme = bridge._settings.theme
    dark = theme == "dark" or (theme == "system" and system_prefers_dark())
    window = webview.create_window(
        APP_NAME,
        url=str(web_dir() / "index.html"),
        js_api=bridge,
        width=1240,
        height=800,
        min_size=(900, 600),
        background_color=DARK_BG if dark else LIGHT_BG,
        text_select=True,
    )
    bridge._attach(window)
    debug = os.environ.get("AUDIOTRANSLATOR_DEBUG") == "1"
    icon = web_dir() / "assets" / "icon.png"  # used by GTK/Qt; Windows takes the .exe icon
    # The interface needs a modern engine: on Windows insist on WebView2 (Edge), never legacy MSHTML.
    gui = "edgechromium" if sys.platform == "win32" else None
    try:
        webview.start(gui=gui, debug=debug, http_server=True, private_mode=True, icon=str(icon))
    except Exception as exc:
        log.exception("Could not start the window")
        if sys.platform == "win32":
            show_fatal(
                "AudioTranslator needs Microsoft Edge WebView2 Runtime.\n"
                f"Install it from {WEBVIEW2_URL} and start the app again.\n\n{exc}"
            )
            webbrowser.open(WEBVIEW2_URL)
        else:
            show_fatal(f"Could not open the window: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
