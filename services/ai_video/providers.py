from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class GenerationRequest:
    prompt: str
    duration_seconds: int | None = None
    aspect_ratio: str | None = None


class VideoGenerationProvider(ABC):
    @abstractmethod
    async def generate(self, request: GenerationRequest, output_path: str) -> str:
        """Generate video and return the produced path."""


class VideoGenerationUnavailable(RuntimeError):
    pass
