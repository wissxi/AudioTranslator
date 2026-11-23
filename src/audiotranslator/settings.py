"""User settings stored as JSON in the app data folder."""

from __future__ import annotations

import json
import locale
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .core.exporters import FORMATS
from .core.transcriber import DEFAULT_MODEL, MODEL_BY_NAME
from .core.translation import PROVIDERS
from .languages import is_supported
from .paths import settings_file

log = logging.getLogger(__name__)


def system_ui_language() -> str:
    for value in (os.environ.get("LANG", ""), (locale.getlocale()[0] or "")):
        lowered = value.lower()
        if lowered.startswith(("ru", "russian", "uk", "ukrainian", "be", "belarusian", "kk", "kazakh")):
            return "ru"
    if os.name == "nt":
        try:
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            # Russian, Ukrainian, Belarusian, Kazakh
            if lang_id in (0x19, 0x22, 0x23, 0x3F):
                return "ru"
        except Exception:
            pass
    return "en"


@dataclass
class Settings:
    model: str = DEFAULT_MODEL
    device: str = "auto"
    source_language: str = ""
    target_language: str = "ru"
    provider: str = "google"
    deepl_key: str = ""
    fallback: bool = True
    formats: list[str] = field(default_factory=lambda: ["txt", "srt"])
    report: bool = True
    include_original: bool = True
    output_dir: str = ""
    vad: bool = True
    recursive: bool = True
    ui_language: str = ""  # "" = follow the system on first launch
    theme: str = "system"  # system | light | dark

    def normalized(self) -> Settings:
        s = self
        if s.model not in MODEL_BY_NAME:
            s.model = DEFAULT_MODEL
        if s.device not in ("auto", "cpu", "cuda"):
            s.device = "auto"
        if s.source_language and not is_supported(s.source_language):
            s.source_language = ""
        if s.target_language and not is_supported(s.target_language):
            s.target_language = "ru"
        if s.provider not in PROVIDERS:
            s.provider = "google"
        s.formats = [f for f in dict.fromkeys(s.formats) if f in FORMATS]
        if s.ui_language not in ("ru", "en"):
            s.ui_language = system_ui_language()
        if s.theme not in ("system", "light", "dark"):
            s.theme = "system"
        return s

    def update(self, patch: dict[str, Any]) -> Settings:
        known = {f.name: f for f in fields(self)}
        for key, value in (patch or {}).items():
            if key not in known:
                continue
            current = getattr(self, key)
            if isinstance(current, bool):
                value = bool(value)
            elif isinstance(current, list):
                value = list(value or [])
            elif isinstance(current, str):
                value = "" if value is None else str(value)
            setattr(self, key, value)
        return self.normalized()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or settings_file()
        settings = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                settings.update(data)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log.warning("Ignoring unreadable settings file %s: %s", path, exc)
        return settings.normalized()

    def save(self, path: Path | None = None) -> None:
        path = path or settings_file()
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
