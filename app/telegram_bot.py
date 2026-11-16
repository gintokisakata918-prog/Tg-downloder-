"""Telegram bot frontend for ClipNest.

Link bhejo, quality chuno, file seedha chat mein aa jaati hai. Yeh bot wahi
engines aur JobManager use karta hai jo web app use karta hai — koi code
duplicate nahi.

Chalane ke liye::

    CLIPNEST_TELEGRAM_BOT_TOKEN=12345:abc uv run --extra bot python -m app.telegram_bot
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import secrets
import time
from collections import deque

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import Settings, get_settings
from app.engines import DirectEngine, EngineError, YtdlpEngine
from app.engines.ytdlp import validate_format_id
from app.jobs import FINISHED_STATES, Job, JobManager
from app.schemas import MediaInfo
from app.security import UnsafeURLError, ensure_public_url

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
AUDIO_SUFFIXES = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac"}

# Telegram edits ko rate limit karta hai; 4 second safe hai.
PROGRESS_INTERVAL = 4.0
PENDING_LIMIT = 200

WELCOME = (
    "🎬 ClipNest bot\n\n"
    "Mujhe koi bhi video link bhejein (YouTube, Instagram, X, Facebook, TikTok, "
    "Vimeo ya direct .mp4 link). Main quality options dikhaunga, aap chunenge, "
    "aur file yahin chat mein bhej dunga.\n\n"
    "/id — apna Telegram user ID dekhein\n"
    "/help — madad\n\n"
    "⚖️ Sirf wahi content download karein jiska aapko haq hai."
)

HELP = (
    "Kaise use karein:\n"
    "1. Link chat mein paste karke bhejein.\n"
    "2. Title aur quality buttons dikhenge.\n"
    "3. Quality (144p se 4K) ya 🎵 MP3 chunein.\n"
    "4. Progress live update hoga, phir file aa jayegi.\n\n"
    "🛑 Chal raha download rokne ke liye message ke neeche Cancel dabayein.\n"
    "⚠️ Telegram par ek file max 50 MB tak hi jaati hai — badi video ke liye "
    "chhoti quality chunein.\n\n"
    "⚖️ Sirf apna, Creative Commons ya public domain content download karein."
)


# --------------------------------------------------------------------- helpers


def extract_url(text: str) -> str | None:
    """Message text se pehla HTTP(S) link nikaalo."""
    match = URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(").,;!\"'")


def format_size(num: float | None) -> str:
    if not num or num <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} GB"


def format_duration(seconds: float | None) -> str:
    if not seconds or seconds < 0:
        return "-"
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def parse_allowed_users(raw: str) -> set[int]:
    """`"123, 456;789"` jaisi string ko user-id set mein badlo."""
    allowed: set[int] = set()
    for chunk in (raw or "").replace(";", ",").replace(" ", ",").split(","):
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            allowed.add(int(chunk))
    return allowed


def progress_bar(percent: float, width: int = 12) -> str:
    filled = max(0, min(width, round(percent / 100 * width)))
    return "█" * filled + "░" * (width - filled)


# ------------------------------------------------------------------------- bot


class ClipNestBot:
    """Handlers + job tracking for the Telegram frontend."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.manager = JobManager(
            settings,
            [DirectEngine(settings), YtdlpEngine(settings)],
        )
        self._pending: dict[str, tuple[str, MediaInfo]] = {}
        self._hits: dict[int, deque[float]] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------ application

    def build_application(self) -> Application:
        token = (self.settings.telegram_bot_token or "").strip()
        if not token:
            raise RuntimeError(
                "CLIPNEST_TELEGRAM_BOT_TOKEN set nahi hai. "
                "BotFather se token le kar .env mein daalein."
            )

        application = (
            Application.builder()
            .token(token)
            .connect_timeout(30)
            .read_timeout(60)
            # Bade file uploads ke liye zyada waqt.
            .write_timeout(600)
            .pool_timeout(60)
            .post_init(self._post_init)
            .post_shutdown(self._post_shutdown)
            .build()
        )

        application.add_handler(CommandHandler("start", self.cmd_start))
        application.add_handler(CommandHandler("help", self.cmd_help))
        application.add_handler(CommandHandler("id", self.cmd_id))
        application.add_handler(CallbackQueryHandler(self.on_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        return application

    async def _post_init(self, application: Application) -> None:
        self.settings.download_dir.mkdir(parents=True, exist_ok=True)
        application.bot_data["janitor"] = asyncio.create_task(self._janitor())
        me = await application.bot.get_me()
        logger.info("ClipNest bot @%s chalu hai", me.username)

    async def _post_shutdown(self, application: Application) -> None:
        task = application.bot_data.get("janitor")
        if isinstance(task, asyncio.Task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _janitor(self, interval_seconds: int = 300) -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                removed = await asyncio.to_thread(self.manager.cleanup_expired)
                if removed:
                    logger.info("Janitor ne %s purani job(s) delete ki", removed)
            except Exception:
                logger.exception("Janitor tick fail hua")

    # ---------------------------------------------------------------- access

    def _allowed(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        allowlist = parse_allowed_users(self.settings.telegram_allowed_users)
        return not allowlist or user_id in allowlist

    def _rate_ok(self, user_id: int) -> bool:
        limit = self.settings.rate_limit_per_10min
        if limit <= 0:
            return True
        now = time.monotonic()
        hits = self._hits.setdefault(user_id, deque())
        while hits and now - hits[0] > 600:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    async def _guard(self, update: Update) -> bool:
        """Allowlist + rate limit; reject karne par message bhej deta hai."""
        user = update.effective_user
        message = update.effective_message
        if not self._allowed(user.id if user else None):
            if message:
                await message.reply_text(
                    "⛔ Yeh bot private hai. Apne user ID ke saath admin se allow karwayein."
                )
            return False
        if user and not self._rate_ok(user.id):
            if message:
                await message.reply_text(
                    "🚦 Bahut zyada requests. 10 minute mein "
                    f"{self.settings.rate_limit_per_10min} allowed hain - "
                    "thodi der baad try karein."
                )
            return False
        return True

    # -------------------------------------------------------------- commands

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message:
            await update.effective_message.reply_text(WELCOME)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message:
            await update.effective_message.reply_text(HELP)

    async def cmd_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if update.effective_message and user:
            await update.effective_message.reply_text(f"Aapka user ID: {user.id}")

    # ------------------------------------------------------------- link probe

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None or not message.text:
            return
        if not await self._guard(update):
            return

        raw = extract_url(message.text)
        if raw is None:
            await message.reply_text("🔗 Mujhe ek video link bhejein (http:// ya https://).")
            return

        try:
            url = await ensure_public_url(raw, allow_private=self.settings.allow_private_hosts)
        except UnsafeURLError as exc:
            await message.reply_text(f"❌ {exc}")
            return

        engine = self.manager.engine_for(url)
        if engine is None:
            await message.reply_text("❌ Is link ke liye koi engine available nahi hai.")
            return

        await context.bot.send_chat_action(message.chat_id, ChatAction.TYPING)
        try:
            info = await engine.probe(url)
        except EngineError as exc:
            await message.reply_text(f"❌ {exc}")
            return
        except Exception:
            logger.exception("Probe fail hua: %s", url)
            await message.reply_text("❌ Link check nahi ho paya. Dobara koshish karein.")
            return

        probe_id = secrets.token_hex(4)
        self._pending[probe_id] = (url, info)
        self._trim_pending()

        caption = self._info_caption(info)
        markup = self._quality_keyboard(probe_id, info)
        try:
            if info.thumbnail:
                await message.reply_photo(
                    photo=info.thumbnail, caption=caption, reply_markup=markup
                )
            else:
                await message.reply_text(caption, reply_markup=markup)
        except TelegramError:
            # Thumbnail Telegram accept nahi karta (URL ya size issue) — text se kaam chalao.
            await message.reply_text(caption, reply_markup=markup)

    @staticmethod
    def _info_caption(info: MediaInfo) -> str:
        lines = [f"🎬 {info.title}"]
        meta = []
        if info.uploader:
            meta.append(f"👤 {info.uploader}")
        if info.duration:
            meta.append(f"⏱ {format_duration(info.duration)}")
        if meta:
            lines.append(" · ".join(meta))
        if info.formats:
            lines.append("\nQuality chunein:")
        else:
            lines.append("\nQuality list khali hai — original file try karein:")
        return "\n".join(lines)[:1000]

    @staticmethod
    def _quality_keyboard(probe_id: str, info: MediaInfo) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        current: list[InlineKeyboardButton] = []
        for option in info.formats[:8]:
            label = option.label
            if option.filesize:
                label += f" · {format_size(option.filesize)}"
            current.append(
                InlineKeyboardButton(label[:60], callback_data=f"q:{probe_id}:{option.id}")
            )
            if len(current) == 3:
                rows.append(current)
                current = []
        if current:
            rows.append(current)
        rows.append(
            [
                InlineKeyboardButton("🎵 MP3 (audio)", callback_data=f"a:{probe_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"x:{probe_id}"),
            ]
        )
        return InlineKeyboardMarkup(rows)

    def _trim_pending(self) -> None:
        while len(self._pending) > PENDING_LIMIT:
            self._pending.pop(next(iter(self._pending)), None)

    # -------------------------------------------------------------- callbacks

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        await query.answer()

        user = update.effective_user
        if not self._allowed(user.id if user else None):
            await self._edit_message(query, "⛔ Yeh bot private hai.")
            return

        data = query.data or ""
        kind, _, rest = data.partition(":")

        if kind in {"q", "a", "x"}:
            probe_id, _, format_id = rest.partition(":")
            pending = self._pending.pop(probe_id, None)
            if pending is None:
                await self._edit_message(query, "⌛ Yeh link purana ho gaya. Link dobara bhejein.")
                return
            url, info = pending

            if kind == "x":
                await self._edit_message(query, "🛑 Cancel kar diya.")
                return

            if user and not self._rate_ok(user.id):
                await self._edit_message(query, "🚦 Rate limit — thodi der baad try karein.")
                return

            audio_only = kind == "a"
            try:
                chosen = None if audio_only else validate_format_id(format_id)
            except EngineError as exc:
                await self._edit_message(query, f"❌ {exc}")
                return

            job = self.manager.create(url, format_id=chosen, audio_only=audio_only)
            label = "MP3 (audio)" if audio_only else (format_id or "best")
            status_message = await self._edit_message(
                query,
                self._progress_text(info.title, job, label),
                reply_markup=self._cancel_keyboard(job),
            )
            if status_message is not None:
                self._spawn(self._track(context.bot, status_message, job, info.title, label))
            return

        if kind == "c":
            job = self.manager.get(rest)
            if job is None:
                await self._edit_message(query, "⌛ Job purana ho gaya.")
                return
            self.manager.cancel(job.id)
            await self._edit_message(query, "🛑 Cancel kar diya, thoda waqt lagega.")
            return

    async def _edit_message(
        self,
        query,
        text: str,
        markup: InlineKeyboardMarkup | None = None,
    ) -> Message | None:
        """Card update karo — photo card ke liye caption edit use hota hai."""
        message = query.message
        if message is None:
            return None
        try:
            await message.edit_text(text, reply_markup=markup)
            return message
        except TelegramError:
            pass
        with contextlib.suppress(TelegramError):
            await message.edit_caption(caption=text[:1000], reply_markup=markup)
            return message
        with contextlib.suppress(TelegramError):
            return await message.chat.send_message(text, reply_markup=markup)
        return None

    @staticmethod
    async def _safe_edit(message: Message, text: str, markup: InlineKeyboardMarkup) -> None:
        """Progress edit; photo message ho to caption badal deta hai."""
        try:
            await message.edit_text(text, reply_markup=markup)
        except TelegramError:
            with contextlib.suppress(TelegramError):
                await message.edit_caption(caption=text[:1000], reply_markup=markup)

    @staticmethod
    def _cancel_keyboard(job: Job, probe_id: str | None = None) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🛑 Cancel", callback_data=f"c:{job.id}")]]
        )

    @staticmethod
    def _progress_text(title: str, job: Job, label: str) -> str:
        lines = [
            f"⬇️ {title[:120]}",
            f"{progress_bar(job.progress)} {job.progress:.0f}%",
        ]
        detail = [f"🎚 {label}"]
        if job.speed:
            detail.append(f"⚡ {format_size(job.speed)}/s")
        if job.eta:
            detail.append(f"⏳ {format_duration(job.eta)}")
        lines.append(" · ".join(detail))
        if job.status == "queued":
            lines.append("⏸ Queue mein hai…")
        return "\n".join(lines)

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # --------------------------------------------------------------- progress

    async def _track(
        self,
        bot: Bot,
        message: Message,
        job: Job,
        title: str,
        label: str,
    ) -> None:
        try:
            while job.status not in FINISHED_STATES:
                await asyncio.sleep(PROGRESS_INTERVAL)
                if job.status in FINISHED_STATES:
                    break
                await self._safe_edit(
                    message, self._progress_text(title, job, label), self._cancel_keyboard(job)
                )

            if job.status == "finished":
                await self._safe_edit(
                    message,
                    f"✅ {title[:120]}\nDownload poora hua — bhej raha hoon…",
                    InlineKeyboardMarkup([]),
                )
                await self._deliver(bot, message.chat_id, job)
            elif job.status == "cancelled":
                await self._safe_edit(
                    message, "🛑 Download cancel ho gaya.", InlineKeyboardMarkup([])
                )
            else:
                await self._safe_edit(
                    message,
                    f"❌ Fail hua: {job.error or 'unknown error'}\n"
                    "Link ya quality badal kar try karein.",
                    InlineKeyboardMarkup([]),
                )
        finally:
            self.manager.remove(job.id)

    async def _deliver(self, bot: Bot, chat_id: int, job: Job) -> None:
        if not job.filename:
            await bot.send_message(chat_id, "❌ File ka naam nahi mila.")
            return
        path = job.directory / job.filename
        if not path.is_file():
            await bot.send_message(chat_id, "❌ File delete ho chuki hai. Dobara bhejein.")
            return

        size = path.stat().st_size
        limit = self.settings.telegram_max_upload_mb * 1024 * 1024
        if size > limit:
            await bot.send_message(
                chat_id,
                f"⚠️ File {format_size(size)} ki hai — Telegram par "
                f"{self.settings.telegram_max_upload_mb} MB tak hi bhej sakta hoon.\n"
                "Chhoti quality (jaise 480p) chun kar dobara bhejein.",
            )
            return

        caption = (job.title or path.stem)[:900]
        suffix = path.suffix.lower()
        try:
            with path.open("rb") as handle:
                if suffix in VIDEO_SUFFIXES:
                    await bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)
                    await bot.send_video(
                        chat_id,
                        video=handle,
                        filename=path.name,
                        caption=caption,
                        supports_streaming=True,
                    )
                elif suffix in AUDIO_SUFFIXES:
                    await bot.send_chat_action(chat_id, ChatAction.UPLOAD_VOICE)
                    await bot.send_audio(chat_id, audio=handle, filename=path.name, caption=caption)
                else:
                    await bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)
                    await bot.send_document(
                        chat_id, document=handle, filename=path.name, caption=caption
                    )
        except TelegramError as exc:
            logger.warning("File bhejne mein dikkat: %s", exc)
            await bot.send_message(
                chat_id, f"❌ File bhej nahi paya: {exc.message or exc.__class__.__name__}"
            )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    bot = ClipNestBot(settings)
    application = bot.build_application()
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
