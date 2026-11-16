"""File delivery: Telegram ko sahi method, thumbnail aur fallbacks ke saath."""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from telegram import Bot
from telegram.constants import ChatAction
from telegram.error import TelegramError

from app.bot import texts
from app.config import Settings
from app.jobs import Job

logger = logging.getLogger(__name__)

VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
AUDIO_SUFFIXES = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac"}
THUMBNAIL_MAX_BYTES = 200 * 1024


@dataclass(slots=True)
class DeliveryResult:
    ok: bool
    size: int = 0
    error: str | None = None
    too_big: bool = False
    sent_as: str | None = None


async def deliver(
    bot: Bot,
    job: Job,
    *,
    settings: Settings,
    send_as_document: bool = False,
) -> DeliveryResult:
    """Job ki finished file bhejo; video fail ho to document fallback."""
    if not job.filename:
        return DeliveryResult(ok=False, error="File ka naam nahi mila.")
    if job.chat_id is None:
        return DeliveryResult(ok=False, error="Chat id missing hai.")

    path = job.directory / job.filename
    if not path.is_file():
        return DeliveryResult(ok=False, error="File delete ho chuki hai.")

    size = path.stat().st_size
    limit = settings.telegram_upload_limit_bytes
    if size > limit:
        return DeliveryResult(ok=False, too_big=True, size=size)

    caption = _caption(job)
    suffix = path.suffix.lower()
    timeout = {
        "read_timeout": settings.telegram_upload_timeout_seconds,
        "write_timeout": settings.telegram_upload_timeout_seconds,
    }
    common = {
        "chat_id": job.chat_id,
        "caption": caption,
        "message_thread_id": job.thread_id,
        **timeout,
    }

    if suffix in VIDEO_SUFFIXES and not send_as_document:
        thumbnail = (
            await _make_thumbnail(path, job.directory)
            if settings.telegram_generate_thumbnail
            else None
        )
        try:
            await bot.send_chat_action(job.chat_id, ChatAction.UPLOAD_VIDEO)
            await bot.send_video(
                video=str(path),
                filename=path.name,
                thumbnail=str(thumbnail) if thumbnail else None,
                duration=job.duration,
                supports_streaming=True,
                **common,
            )
            return DeliveryResult(ok=True, size=size, sent_as="video")
        except TelegramError as exc:
            if _is_too_big(exc):
                return DeliveryResult(ok=False, size=size, too_big=True, error=str(exc))
            logger.warning("Video send fail (%s) — document fallback", exc)

    if (job.audio_only or suffix in AUDIO_SUFFIXES) and not send_as_document:
        try:
            await bot.send_chat_action(job.chat_id, ChatAction.UPLOAD_VOICE)
            await bot.send_audio(
                audio=str(path),
                filename=path.name,
                title=texts.truncate(job.title or path.stem, 64),
                duration=job.duration,
                **common,
            )
            return DeliveryResult(ok=True, size=size, sent_as="audio")
        except TelegramError as exc:
            if _is_too_big(exc):
                return DeliveryResult(ok=False, size=size, too_big=True, error=str(exc))
            logger.warning("Audio send fail (%s) — document fallback", exc)

    try:
        await bot.send_chat_action(job.chat_id, ChatAction.UPLOAD_DOCUMENT)
        await bot.send_document(document=str(path), filename=path.name, **common)
        return DeliveryResult(ok=True, size=size, sent_as="document")
    except TelegramError as exc:
        too_big = _is_too_big(exc)
        logger.warning("Document send fail: %s", exc)
        return DeliveryResult(
            ok=False,
            size=size,
            too_big=too_big,
            error=str(exc) or exc.__class__.__name__,
        )


def _caption(job: Job) -> str:
    title = texts.truncate(job.title or "ClipNest download", 700)
    meta: list[str] = []
    if job.label:
        meta.append(f"🎚 {job.label}")
    if job.duration:
        meta.append(f"⏱ {texts.format_duration(job.duration)}")
    if job.filesize:
        meta.append(f"📦 {texts.format_size(job.filesize)}")
    if meta:
        return f"{title}\n{' · '.join(meta)}"
    return title


def _is_too_big(exc: TelegramError) -> bool:
    message = str(exc).lower()
    return "too big" in message or "file is too large" in message


async def _make_thumbnail(video: Path, directory: Path) -> Path | None:
    """ffmpeg se 320px JPEG thumbnail banao (Telegram limit 200 KB)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None

    target = directory / "thumbnail.jpg"
    if target.is_file() and 0 < target.stat().st_size <= THUMBNAIL_MAX_BYTES:
        return target

    for seek in ("1", "0"):
        command = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-ss",
            seek,
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            "scale=320:-2",
            "-q:v",
            "5",
            str(target),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
        except OSError:
            return None
        if (
            process.returncode == 0
            and target.is_file()
            and 0 < target.stat().st_size <= THUMBNAIL_MAX_BYTES
        ):
            return target

    target.unlink(missing_ok=True)
    return None
