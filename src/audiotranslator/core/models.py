"""Plain data structures passed between the engine stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Segment:
    """One recognized phrase with its timing and (optional) translation."""

    start: float
    end: float
    text: str
    translation: str = ""

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text,
            "translation": self.translation,
        }


@dataclass
class Transcript:
    """Everything produced for a single media file."""

    source: Path
    language: str
    language_probability: float
    duration: float
    segments: list[Segment] = field(default_factory=list)
    target_language: str | None = None
    translation_provider: str | None = None
    translation_error: str | None = None

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.segments if s.text).strip()

    @property
    def translated_text(self) -> str:
        return " ".join(s.translation for s in self.segments if s.translation).strip()

    @property
    def has_translation(self) -> bool:
        return any(s.translation for s in self.segments)

    def to_dict(self) -> dict:
        return {
            "source": str(self.source),
            "language": self.language,
            "language_probability": round(self.language_probability, 3),
            "duration": round(self.duration, 3),
            "target_language": self.target_language,
            "translation_provider": self.translation_provider,
            "translation_error": self.translation_error,
            "segments": [s.to_dict() for s in self.segments],
        }
