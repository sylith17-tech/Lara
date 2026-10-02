"""Optional future text-to-video provider interfaces; no provider is enabled."""

from .providers import VideoGenerationProvider, VideoGenerationUnavailable

__all__ = ["VideoGenerationProvider", "VideoGenerationUnavailable"]
