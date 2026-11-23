"""Filesystem locations used by the application."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def data_dir() -> Path:
    """Per-user folder for settings and downloaded models.

    Override with the ``AUDIOTRANSLATOR_HOME`` environment variable.
    """
    override = os.environ.get("AUDIOTRANSLATOR_HOME")
    if override:
        path = Path(override).expanduser()
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or Path.home()
        path = Path(base) / APP_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
        path = Path(base) / APP_NAME.lower()
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_file() -> Path:
    return data_dir() / "settings.json"


def log_file() -> Path:
    return data_dir() / "audiotranslator.log"


def web_dir() -> Path:
    """Folder with the bundled user interface (works from source and from PyInstaller)."""
    return Path(__file__).resolve().parent / "web"
