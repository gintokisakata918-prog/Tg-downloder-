"""Engine for direct media links (e.g. https://host/clip.mp4)."""

from __future__ import annotations

import asyncio
import re
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from app.config import Settings
from app.engines.base import BaseEngine, DownloadCancelled, EngineError, ProgressCallback
from app.schemas import FormatOption, MediaInfo

MEDIA_EXTENSIONS = {
    ".mp4",
    ".webm",
    ".mov",
    ".m4v",
    ".mkv",
    ".avi",
    ".mp3",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wav",
    ".flac",
}

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac"}
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._\- ()\[\]\u0900-\u097F]+")


def _filename_from_headers(resp: httpx.Response, url: str) -> str:
    disposition = resp.headers.get("content-disposition", "")
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition, re.IGNORECASE)
    name = unquote(match.group(1)).strip() if match else unquote(Path(urlparse(url).path).name)
    name = SAFE_FILENAME.sub("_", name).strip("._ ") or "download"
    return name[:120]


def _total_bytes(resp: httpx.Response) -> int | None:
    content_range = resp.headers.get("content-range", "")
    if "/" in content_range:
        tail = content_range.rsplit("/", 1)[-1].strip()
        if tail.isdigit():
            return int(tail)
    length = resp.headers.get("content-length", "")
    return int(length) if length.isdigit() else None


class DirectEngine(BaseEngine):
    """Streams files that are already served as plain media."""

    name = "direct"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.max_bytes = settings.max_filesize_bytes
        self._headers = {"User-Agent": settings.user_agent}

    def can_handle(self, url: str) -> bool:
        suffix = Path(urlparse(url).path).suffix.lower()
        return suffix in MEDIA_EXTENSIONS

    async def probe(self, url: str) -> MediaInfo:
        return await asyncio.to_thread(self._probe_sync, url)

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
        return await asyncio.to_thread(self._download_sync, url, target_dir, cancel, on_progress)

    def _probe_sync(self, url: str) -> MediaInfo:
        try:
            with (
                httpx.Client(
                    follow_redirects=True,
                    timeout=self.settings.request_timeout_seconds,
                    headers=self._headers,
                ) as client,
                client.stream("GET", url, headers={"Range": "bytes=0-0"}) as resp,
            ):
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "").split(";")[0].lower()
                total = _total_bytes(resp)
                filename = _filename_from_headers(resp, url)
        except httpx.HTTPError as exc:
            raise EngineError(f"Yeh link open nahi hua: {exc.__class__.__name__}") from exc

        if content_type and not (
            content_type.startswith(("video/", "audio/", "application/octet-stream"))
        ):
            raise EngineError("Yeh direct media file nahi lagti.")

        suffix = Path(filename).suffix.lower()
        audio_only = suffix in AUDIO_EXTENSIONS
        stem = Path(filename).stem or "download"
        return MediaInfo(
            url=url,
            title=stem,
            engine=self.name,
            audio_available=audio_only,
            formats=[
                FormatOption(
                    id="original",
                    label=f"Original ({suffix.lstrip('.') or 'file'})",
                    ext=suffix.lstrip(".") or "bin",
                    kind="audio" if audio_only else "video",
                    filesize=total,
                )
            ],
        )

    def _download_sync(
        self,
        url: str,
        target_dir: Path,
        cancel: threading.Event,
        on_progress: ProgressCallback,
    ) -> Path:
        try:
            with (
                httpx.Client(
                    follow_redirects=True,
                    timeout=self.settings.request_timeout_seconds,
                    headers=self._headers,
                ) as client,
                client.stream("GET", url) as resp,
            ):
                resp.raise_for_status()
                filename = _filename_from_headers(resp, url)
                path = target_dir / filename
                total = _total_bytes(resp)
                if total and total > self.max_bytes:
                    raise EngineError("File size limit se badi hai.")

                done = 0
                started = time.monotonic()
                last_update = 0.0
                with path.open("wb") as handle:
                    for chunk in resp.iter_bytes(chunk_size=256 * 1024):
                        if cancel.is_set():
                            raise DownloadCancelled
                        handle.write(chunk)
                        done += len(chunk)
                        if done > self.max_bytes:
                            raise EngineError("File size limit se badi hai.")
                        now = time.monotonic()
                        if now - last_update >= 0.3:
                            elapsed = max(now - started, 0.001)
                            speed = done / elapsed
                            percent = (done / total * 100) if total else 0.0
                            eta = int((total - done) / speed) if total and speed else None
                            on_progress(percent, speed, eta)
                            last_update = now
        except httpx.HTTPError as exc:
            raise EngineError(f"Download fail hua: {exc.__class__.__name__}") from exc

        on_progress(100.0, None, None)
        return path
