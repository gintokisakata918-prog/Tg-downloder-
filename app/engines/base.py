"""Download engine interface and shared exceptions."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from app.schemas import MediaInfo

# progress (0-100), speed (bytes/sec), eta (seconds)
ProgressCallback = Callable[[float, float | None, int | None], None]


class EngineError(Exception):
    """A link could not be probed or downloaded."""


class DownloadCancelled(EngineError):
    """The user cancelled a running download."""


class BaseEngine(ABC):
    """A pluggable way to inspect and fetch media from a URL."""

    name: str = "base"

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Return True if this engine should be used for `url`."""

    @abstractmethod
    async def probe(self, url: str) -> MediaInfo:
        """Fetch metadata and available formats without downloading."""

    @abstractmethod
    async def download(
        self,
        url: str,
        target_dir: Path,
        cancel: threading.Event,
        on_progress: ProgressCallback,
        *,
        format_id: str | None = None,
        audio_only: bool = False,
    ) -> Path:
        """Download the media and return the path of the finished file."""
