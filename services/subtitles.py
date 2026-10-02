"""Provider boundary for speech recognition and subtitle translation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class SubtitleProvider(ABC):
    @abstractmethod
    async def transcribe(self, media_path: str | Path, *, language: str | None = None) -> str:
        """Return subtitles in SRT or VTT form. Implementations own their API credentials."""

    @abstractmethod
    async def translate(self, subtitle_text: str, *, target_language: str) -> str:
        """Translate SRT/VTT while preserving timestamps."""


class SubtitleProviderUnavailable(RuntimeError):
    pass
