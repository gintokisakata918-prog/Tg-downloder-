"""Engine backed by yt-dlp: supports thousands of sites plus generic pages."""

from __future__ import annotations

import asyncio
import re
import shutil
import threading
from pathlib import Path

import yt_dlp

from app.config import Settings
from app.engines.base import BaseEngine, DownloadCancelled, EngineError, ProgressCallback
from app.schemas import FormatOption, MediaInfo

FORMAT_ID_PATTERN = re.compile(r"^v(\d{2,4})$")
PARTIAL_SUFFIXES = {".part", ".ytdl", ".temp"}


def parse_height(format_id: str | None) -> int | None:
    """Turn a public format id like ``v1080`` into a pixel height."""
    if not format_id:
        return None
    match = FORMAT_ID_PATTERN.match(format_id)
    if not match:
        raise EngineError("Quality selection valid nahi hai.")
    height = int(match.group(1))
    if not 144 <= height <= 4320:
        raise EngineError("Quality selection valid nahi hai.")
    return height


def validate_format_id(format_id: str | None) -> str | None:
    if format_id is None or format_id in {"", "original"}:
        return None
    if not FORMAT_ID_PATTERN.match(format_id):
        raise EngineError("Quality selection valid nahi hai.")
    return format_id


class YtdlpEngine(BaseEngine):
    """Wraps yt-dlp and reports progress back to the job manager."""

    name = "yt-dlp"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.has_ffmpeg = shutil.which("ffmpeg") is not None

    def can_handle(self, url: str) -> bool:
        return True

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
        return await asyncio.to_thread(
            self._download_sync, url, target_dir, cancel, on_progress, format_id, audio_only
        )

    # ------------------------------------------------------------------ probe

    def _base_options(self) -> dict:
        options: dict = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "noprogress": True,
            "cachedir": False,
            "socket_timeout": self.settings.request_timeout_seconds,
            "retries": 3,
            "extractor_retries": 2,
            "user_agent": self.settings.user_agent,
        }
        if self.settings.cookies_file and self.settings.cookies_file.is_file():
            options["cookiefile"] = str(self.settings.cookies_file)
        return options

    def _probe_sync(self, url: str) -> MediaInfo:
        try:
            with yt_dlp.YoutubeDL(self._base_options()) as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            raise EngineError(self._clean_error(exc)) from exc

        if not info:
            raise EngineError("Is link se koi media nahi mila.")
        if info.get("_type") == "playlist":
            entries = [entry for entry in (info.get("entries") or []) if entry]
            if not entries:
                raise EngineError("Playlist khali hai.")
            info = entries[0]

        duration = info.get("duration")
        if duration and duration > self.settings.max_duration_seconds:
            raise EngineError("Video allowed duration se lambi hai.")

        return MediaInfo(
            url=info.get("webpage_url") or url,
            title=(info.get("title") or "Untitled").strip()[:200],
            engine=self.name,
            thumbnail=info.get("thumbnail"),
            duration=int(duration) if duration else None,
            uploader=info.get("uploader") or info.get("channel"),
            audio_available=True,
            formats=self._video_formats(info),
        )

    def _video_formats(self, info: dict) -> list[FormatOption]:
        best_by_height: dict[int, tuple[float, FormatOption]] = {}
        for fmt in info.get("formats") or []:
            if not fmt.get("height") or fmt.get("vcodec") in (None, "none"):
                continue
            height = int(fmt["height"])
            if height > 4320:
                continue
            size = fmt.get("filesize") or fmt.get("filesize_approx")
            option = FormatOption(
                id=f"v{height}",
                label=f"{height}p",
                ext="mp4",
                kind="video",
                height=height,
                filesize=int(size) if size else None,
            )
            score = float(fmt.get("tbr") or 0)
            if height not in best_by_height or score > best_by_height[height][0]:
                best_by_height[height] = (score, option)

        formats = [option for _, option in best_by_height.values()]
        formats.sort(key=lambda item: item.height or 0, reverse=True)
        return formats

    # --------------------------------------------------------------- download

    def _download_sync(
        self,
        url: str,
        target_dir: Path,
        cancel: threading.Event,
        on_progress: ProgressCallback,
        format_id: str | None,
        audio_only: bool,
    ) -> Path:
        height = parse_height(format_id)
        max_bytes = self.settings.max_filesize_bytes

        if audio_only:
            selector = "bestaudio/best"
        elif height:
            if self.has_ffmpeg:
                selector = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
            else:
                selector = f"best[height<={height}]"
        elif self.has_ffmpeg:
            selector = "bestvideo+bestaudio/best"
        else:
            selector = "best"

        def progress_hook(data: dict) -> None:
            if cancel.is_set():
                raise DownloadCancelled
            status = data.get("status")
            if status == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                if total and total > max_bytes:
                    raise EngineError("File size limit se badi hai.")
                downloaded = data.get("downloaded_bytes") or 0
                percent = (downloaded / total * 100) if total else 0.0
                on_progress(percent, data.get("speed"), data.get("eta"))
            elif status == "finished":
                on_progress(99.0, None, None)

        def postprocessor_hook(data: dict) -> None:
            if cancel.is_set():
                raise DownloadCancelled
            if data.get("status") == "started":
                on_progress(99.0, None, None)

        options = self._base_options()
        options.update(
            {
                "format": selector,
                "outtmpl": str(target_dir / "%(title).140B [%(id)s].%(ext)s"),
                "overwrites": True,
                "continuedl": True,
                "concurrent_fragment_downloads": 3,
                "progress_hooks": [progress_hook],
                "postprocessor_hooks": [postprocessor_hook],
            }
        )
        if audio_only:
            if self.has_ffmpeg:
                options["postprocessors"] = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ]
        else:
            options["merge_output_format"] = "mp4"

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])
        except DownloadCancelled:
            raise
        except yt_dlp.utils.DownloadError as exc:
            if cancel.is_set():
                raise DownloadCancelled from exc
            raise EngineError(self._clean_error(exc)) from exc

        if cancel.is_set():
            raise DownloadCancelled

        files = [
            path
            for path in target_dir.iterdir()
            if path.is_file() and path.suffix.lower() not in PARTIAL_SUFFIXES
        ]
        if not files:
            raise EngineError("Download ke baad file nahi mili.")

        result = max(files, key=lambda path: path.stat().st_mtime)
        on_progress(100.0, None, None)
        return result

    @staticmethod
    def _clean_error(exc: Exception) -> str:
        message = str(exc).replace("ERROR:", "").strip()
        message = message.splitlines()[0] if message else exc.__class__.__name__
        lowered = message.lower()
        if "isn't available to everyone" in lowered or "not available to everyone" in lowered:
            return (
                "Instagram ne is Reel ka access restrict kiya hai. Agar aapko is content "
                "ko dekhne ki permission hai, apne logged-in Instagram session ki cookies "
                "Colab mein cookies.txt ke roop mein upload karke dobara try karein. "
                "Private ya restricted content bina permission access nahi kiya ja sakta."
            )
        return f"Link process nahi hua: {message[:300]}"
