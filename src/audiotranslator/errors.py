"""Error types shared by the engine, the CLI and the GUI.

Every error carries a stable ``code`` so the interface can show a localized
message, plus an English ``message`` used in logs and the CLI.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for expected, user-facing failures."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class MediaError(AppError):
    """A media file could not be read or decoded."""


class ModelError(AppError):
    """A speech recognition model could not be downloaded or loaded."""


class TranslationError(AppError):
    """A translation service failed."""


class Cancelled(Exception):
    """Raised inside the pipeline when the user stops the job."""
