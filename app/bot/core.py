"""ClipNest ka Telegram bot: handlers, jobs, progress aur delivery."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import shutil
import time
from collections import deque
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any

from telegram import Bot, BotCommand, InlineKeyboardMarkup, Message, Update
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

from app import __version__
from app.bot import keyboards, texts
from app.bot.delivery import deliver
from app.bot.store import ProbeStore, UserStore
from app.config import Settings, get_settings
from app.engines import DirectEngine, EngineError, YtdlpEngine
from app.engines.ytdlp import validate_format_id
from app.jobs import FINISHED_STATES, Job, JobManager
from app.security import UnsafeURLError, ensure_public_url

logger = logging.getLogger(__name__)

JANITOR_INTERVAL = 300


@dataclass(slots=True)
class RetrySpec:
    url: str
    format_id: str | None
    audio_only: bool
    title: str
    label: str


class ClipNestBot:
    """Telegram handlers + job tracking for one bot process."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.manager = JobManager(
            settings,
            [DirectEngine(settings), YtdlpEngine(settings)],
        )
        self.users = UserStore(settings.telegram_users_file)
        self.probes = ProbeStore(
            settings.telegram_probes_file,
            ttl_minutes=settings.telegram_probe_ttl_minutes,
            max_entries=300,
        )
        self._hits: dict[int, deque[float]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._user_jobs: dict[int, set[str]] = {}
        self._job_owner: dict[str, int] = {}
        self._retry_specs: dict[str, RetrySpec] = {}
        self._allowed_ids = settings.telegram_allowed_user_ids
        self._started_at = time.time()

    # ------------------------------------------------------------ application

    def build_application(self) -> Application:
        token = (self.settings.telegram_bot_token or "").strip()
        if not token:
            raise RuntimeError(
                "CLIPNEST_TELEGRAM_BOT_TOKEN set nahi hai. "
                "BotFather se token le kar .env mein daalein."
            )

        builder = (
            Application.builder()
            .token(token)
            .connect_timeout(30)
            .read_timeout(60)
            # Bade uploads ke liye zyada waqt.
            .write_timeout(self.settings.telegram_upload_timeout_seconds)
            .pool_timeout(60)
        )
        if self.settings.telegram_local_mode:
            builder = (
                builder.base_url(self.settings.telegram_bot_api_url)
                .base_file_url(self.settings.telegram_file_api_url)
                .local_mode(True)
            )

        application = builder.post_init(self._post_init).post_shutdown(self._post_shutdown).build()

        application.add_handler(CommandHandler("start", self.cmd_start))
        application.add_handler(CommandHandler("help", self.cmd_help))
        application.add_handler(CommandHandler("id", self.cmd_id))
        application.add_handler(CommandHandler("settings", self.cmd_settings))
        application.add_handler(CommandHandler("status", self.cmd_status))
        application.add_handler(CommandHandler("cancel", self.cmd_cancel))
        application.add_handler(CommandHandler("privacy", self.cmd_privacy))
        application.add_handler(CallbackQueryHandler(self.on_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        application.add_handler(MessageHandler(filters.CAPTION, self.on_text))
        application.add_error_handler(self.on_error)
        return application

    async def _post_init(self, application: Application) -> None:
        settings = self.settings
        settings.download_dir.mkdir(parents=True, exist_ok=True)
        settings.telegram_users_file.parent.mkdir(parents=True, exist_ok=True)
        settings.telegram_probes_file.parent.mkdir(parents=True, exist_ok=True)

        application.bot_data["janitor"] = asyncio.create_task(self._janitor())

        me = await application.bot.get_me()
        with contextlib.suppress(TelegramError):
            await application.bot.set_my_commands(
                [
                    BotCommand("start", "Bot shuru karein"),
                    BotCommand("settings", "Default quality / document mode"),
                    BotCommand("status", "Active downloads aur queue"),
                    BotCommand("cancel", "Apne downloads cancel karein"),
                    BotCommand("id", "Apna Telegram user ID"),
                    BotCommand("privacy", "Privacy aur data info"),
                    BotCommand("help", "Madad"),
                ]
            )

        limit_note = f"{settings.telegram_max_upload_mb} MB" + (
            " (local Bot API)" if settings.telegram_local_mode else " (cloud limit)"
        )
        logger.info("ClipNest bot @%s chalu hai · upload limit %s", me.username, limit_note)
        if settings.telegram_max_upload_mb > 50 and not settings.telegram_local_mode:
            logger.warning(
                "telegram_max_upload_mb=%s set hai lekin local Bot API server nahi — "
                "Telegram cloud 50 MB se badi file reject karega.",
                settings.telegram_max_upload_mb,
            )

    async def _post_shutdown(self, application: Application) -> None:
        task = application.bot_data.get("janitor")
        if isinstance(task, asyncio.Task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        cancelled = self.manager.cancel_all()
        if cancelled:
            logger.info("Shutdown par %s active download cancel kiye", cancelled)

        for running in list(self._tasks):
            running.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self.users.save()
        self.probes.save()

    async def _janitor(self, interval_seconds: int = JANITOR_INTERVAL) -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                removed = await asyncio.to_thread(self.manager.cleanup_expired)
                probes = self.probes.cleanup()
                if removed or probes:
                    logger.info("Janitor: %s job(s), %s probe(s) delete hue", removed, probes)
                for job_id in list(self._retry_specs):
                    if self.manager.get(job_id) is None:
                        self._retry_specs.pop(job_id, None)
            except Exception:
                logger.exception("Janitor tick fail hua")

    # ---------------------------------------------------------------- access

    def _allowed(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        return not self._allowed_ids or user_id in self._allowed_ids

    def _rate_ok(self, user_id: int, *, consume: bool) -> bool:
        limit = self.settings.rate_limit_per_10min
        if limit <= 0:
            return True
        now = time.monotonic()
        hits = self._hits.setdefault(user_id, deque())
        while hits and now - hits[0] > 600:
            hits.popleft()
        if len(hits) >= limit:
            return False
        if consume:
            hits.append(now)
        return True

    async def _guard(self, update: Update) -> bool:
        user = update.effective_user
        message = update.effective_message
        if not self._allowed(user.id if user else None):
            if message:
                await message.reply_text(texts.PRIVATE_ONLY)
            return False
        if user and not self._rate_ok(user.id, consume=False):
            if message:
                await message.reply_text(
                    texts.RATE_LIMITED.format(limit=self.settings.rate_limit_per_10min)
                )
            return False
        return True

    # -------------------------------------------------------------- commands

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        message = update.effective_message
        if message is None:
            return
        markup = keyboards.main_menu() if self._is_private(update) else None
        await message.reply_text(
            texts.WELCOME,
            parse_mode="HTML",
            reply_markup=markup,
            disable_web_page_preview=True,
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        if update.effective_message:
            await update.effective_message.reply_text(
                texts.HELP, parse_mode="HTML", disable_web_page_preview=True
            )

    async def cmd_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        user = update.effective_user
        message = update.effective_message
        if user and message:
            chat_id = update.effective_chat.id if update.effective_chat else "-"
            await message.reply_text(
                f"🆔 User ID: <code>{user.id}</code>\n"
                f"💬 Chat ID: <code>{chat_id}</code>\n\n"
                "Allowlist ke liye user ID admin ko bhejein.",
                parse_mode="HTML",
            )

    async def cmd_privacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        if update.effective_message:
            await update.effective_message.reply_text(
                texts.PRIVACY, parse_mode="HTML", disable_web_page_preview=True
            )

    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        user = update.effective_user
        message = update.effective_message
        if user is None or message is None:
            return
        prefs = self.users.get(user.id)
        await message.reply_text(
            texts.settings_text(prefs.default_quality, prefs.send_as_document),
            parse_mode="HTML",
            reply_markup=keyboards.settings_keyboard(prefs.default_quality, prefs.send_as_document),
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        user = update.effective_user
        message = update.effective_message
        if user is None or message is None:
            return

        jobs = [
            job
            for job_id in self._user_jobs.get(user.id, set())
            if (job := self.manager.get(job_id)) is not None and job.status in {"queued", "running"}
        ]
        jobs.sort(key=lambda job: job.created_at)

        try:
            disk_free = shutil.disk_usage(self.settings.download_dir).free
        except OSError:
            disk_free = None

        body = texts.status_text(
            version=__version__,
            uptime_seconds=time.time() - self._started_at,
            active_jobs=self.manager.active_count(),
            my_jobs=len(jobs),
            ttl_minutes=self.settings.job_ttl_minutes,
            disk_free=disk_free,
            limit_mb=self.settings.telegram_max_upload_mb,
            local_mode=self.settings.telegram_local_mode,
        )
        if jobs:
            body += "\n\n<b>Aapke jobs</b>"
            for job in jobs:
                position = self.manager.queue_position(job.id)
                suffix = f" · queue {position}" if position > 1 else ""
                title = texts.truncate(job.title or "Download", 45)
                body += f"\n• {texts.escape_html(title)} — {job.status} {job.progress:.0f}%{suffix}"
        await message.reply_text(body, parse_mode="HTML")

    async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        user = update.effective_user
        message = update.effective_message
        if user is None or message is None:
            return

        cancelled = 0
        for job_id in list(self._user_jobs.get(user.id, set())):
            job = self.manager.get(job_id)
            if job is None or job.status in FINISHED_STATES:
                continue
            self.manager.cancel(job_id)
            cancelled += 1

        if cancelled:
            await message.reply_text(f"🛑 {cancelled} download cancel kar diya. Thoda waqt lagega.")
        else:
            await message.reply_text("📭 Aapka koi active download nahi hai.")

    # ------------------------------------------------------------- link probe

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None:
            return
        text = (message.text or message.caption or "").strip()
        if not text:
            return
        if not await self._guard(update):
            return

        if self._is_private(update):
            if text == texts.MENU_HELP:
                await self.cmd_help(update, context)
                return
            if text == texts.MENU_SETTINGS:
                await self.cmd_settings(update, context)
                return
            if text == texts.MENU_STATUS:
                await self.cmd_status(update, context)
                return
            if text == texts.MENU_CANCEL:
                await self.cmd_cancel(update, context)
                return
            if text == texts.MENU_LINK:
                await message.reply_text(
                    "🔗 Video ka link paste karke bhejein — main quality options dikhaunga."
                )
                return

        user = update.effective_user
        if user is None:
            return
        if not self._rate_ok(user.id, consume=True):
            await message.reply_text(
                texts.RATE_LIMITED.format(limit=self.settings.rate_limit_per_10min)
            )
            return

        raw = texts.extract_url(text)
        if raw is None:
            await message.reply_text(texts.NO_LINK, parse_mode="HTML")
            return

        try:
            url = await ensure_public_url(raw, allow_private=self.settings.allow_private_hosts)
        except UnsafeURLError as exc:
            await message.reply_text(f"❌ {texts.escape_html(str(exc))}", parse_mode="HTML")
            return

        engine = self.manager.engine_for(url)
        if engine is None:
            await message.reply_text(texts.NO_ENGINE)
            return

        placeholder = await message.reply_text(texts.PROBE_STARTED)
        await context.bot.send_chat_action(message.chat_id, ChatAction.TYPING)

        try:
            info = await asyncio.wait_for(
                engine.probe(url),
                timeout=max(45, self.settings.request_timeout_seconds + 45),
            )
        except TimeoutError:
            await self._replace_placeholder(
                placeholder, "⏱ Link check mein bahut waqt laga. Dobara koshish karein."
            )
            return
        except EngineError as exc:
            await self._replace_placeholder(placeholder, f"❌ {texts.escape_html(str(exc))}")
            return
        except Exception:
            logger.exception("Probe fail hua: %s", url)
            await self._replace_placeholder(placeholder, texts.PROBE_FAILED)
            return

        probe = self.probes.put(user.id, url, info)
        prefs = self.users.get(user.id)
        caption = texts.info_caption(
            info,
            limit_mb=self.settings.telegram_max_upload_mb,
            default_quality=prefs.default_quality,
            strict_size=self.settings.telegram_strict_size,
        )
        markup = keyboards.quality_keyboard(
            probe.id,
            info,
            limit_bytes=self.settings.telegram_upload_limit_bytes,
            default_quality=prefs.default_quality,
            quality_limit=self.settings.telegram_quality_limit,
        )

        sent = None
        if info.thumbnail:
            try:
                sent = await message.reply_photo(
                    photo=info.thumbnail,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            except TelegramError:
                sent = None

        if sent is not None:
            with contextlib.suppress(TelegramError):
                await placeholder.delete()
            return

        try:
            await placeholder.edit_text(caption, parse_mode="HTML", reply_markup=markup)
        except TelegramError:
            await message.reply_text(caption, parse_mode="HTML", reply_markup=markup)

    async def _replace_placeholder(self, placeholder: Message, text: str) -> None:
        try:
            await placeholder.edit_text(text, parse_mode="HTML")
        except TelegramError:
            with contextlib.suppress(TelegramError):
                await placeholder.reply_text(text, parse_mode="HTML")

    # -------------------------------------------------------------- callbacks

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return

        user = update.effective_user
        if not self._allowed(user.id if user else None):
            await self._answer(query, texts.PRIVATE_ONLY, alert=True)
            return
        if user is None:
            return

        kind, args = keyboards.parse_callback(query.data)

        if kind == "link":
            await self._answer(query, "Chat mein link paste karke bhejein 🔗")
            return

        if kind in {"q", "a", "d", "x"}:
            await self._handle_quality(query, context.bot, user.id, kind, args)
            return

        if kind == "c":
            await self._handle_cancel(query, user.id, args)
            return

        if kind == "r":
            await self._handle_retry(query, context.bot, user.id, args)
            return

        if kind == "set":
            await self._handle_settings(query, user.id, args)
            return

        await self._answer(query, texts.UNKNOWN_BUTTON, alert=True)

    async def _handle_quality(
        self,
        query: Any,
        bot: Bot,
        user_id: int,
        kind: str,
        args: list[str],
    ) -> None:
        if not args:
            await self._answer(query, texts.UNKNOWN_BUTTON, alert=True)
            return

        probe_id = args[0]
        probe = self.probes.get(probe_id)
        if probe is None:
            await self._answer(query)
            await self._edit_message(query, texts.PROBE_GONE, keyboards.empty_keyboard())
            return
        if probe.user_id != user_id:
            await self._answer(query, texts.NOT_YOURS, alert=True)
            return

        if kind == "x":
            self.probes.pop(probe_id)
            await self._answer(query)
            await self._edit_message(query, "🛑 Cancel kar diya.", keyboards.empty_keyboard())
            return

        if not self._rate_ok(user_id, consume=True):
            await self._answer(
                query,
                texts.RATE_LIMITED.format(limit=self.settings.rate_limit_per_10min),
                alert=True,
            )
            return

        info = probe.info
        try:
            if kind == "a":
                format_id, audio_only = None, True
                label = "MP3 (audio)"
            elif kind == "d":
                prefs = self.users.get(user_id)
                format_id, audio_only = texts.quality_from_pref(prefs.default_quality)
                if audio_only and not info.audio_available:
                    format_id, audio_only = None, False
                label = "MP3 (audio)" if audio_only else self._format_label(info, format_id)
            else:
                if len(args) < 2:
                    await self._answer(query, texts.UNKNOWN_BUTTON, alert=True)
                    return
                format_id = validate_format_id(args[1])
                audio_only = False
                label = self._format_label(info, format_id)
        except EngineError as exc:
            await self._answer(query)
            await self._edit_message(query, f"❌ {texts.escape_html(str(exc))}")
            return

        if self.settings.telegram_strict_size and not audio_only:
            option = self._find_format(info, format_id)
            if option and option.filesize:
                estimated = int(option.filesize * 1.10)
                if estimated > self.settings.telegram_upload_limit_bytes:
                    await self._answer(query)
                    await self._edit_message(
                        query,
                        texts.too_big_text(
                            estimated,
                            self.settings.telegram_max_upload_mb,
                            self.settings.telegram_local_mode,
                        ),
                        keyboards.empty_keyboard(),
                    )
                    return

        self.probes.pop(probe_id)
        message = query.message
        if message is None:
            await self._answer(query, texts.UNKNOWN_BUTTON, alert=True)
            return

        await self._answer(query)
        job = self._create_job(
            user_id=user_id,
            chat_id=message.chat_id,
            thread_id=message.message_thread_id,
            url=probe.url,
            format_id=format_id,
            audio_only=audio_only,
            title=info.title,
            label=label,
            thumbnail=info.thumbnail,
            duration=info.duration,
        )
        await self._edit_message(
            query,
            texts.progress_text(job, label),
            keyboards.cancel_keyboard(job.id),
        )
        self._spawn(self._track(bot, message, job, label))

    async def _handle_cancel(self, query: Any, user_id: int, args: list[str]) -> None:
        if not args:
            await self._answer(query, texts.UNKNOWN_BUTTON, alert=True)
            return
        job = self.manager.get(args[0])
        if job is None:
            await self._answer(query)
            await self._edit_message(query, "⌛ Job purana ho gaya.", keyboards.empty_keyboard())
            return
        if job.user_id not in {None, user_id}:
            await self._answer(query, "🔒 Yeh job aapka nahi hai.", alert=True)
            return
        await self._answer(query)
        self.manager.cancel(job.id)
        await self._edit_message(
            query,
            f"🛑 {texts.truncate(job.title or 'Download', 80)} cancel kar diya.",
            keyboards.empty_keyboard(),
        )

    async def _handle_retry(self, query: Any, bot: Bot, user_id: int, args: list[str]) -> None:
        if not args:
            await self._answer(query, texts.UNKNOWN_BUTTON, alert=True)
            return
        job_id = args[0]
        old = self.manager.get(job_id)
        spec = self._retry_specs.get(job_id)
        if old is None or spec is None:
            await self._answer(query)
            await self._edit_message(
                query,
                "⌛ Retry window khatam ho gayi. Link dobara bhejein.",
                keyboards.empty_keyboard(),
            )
            return
        if old.user_id not in {None, user_id}:
            await self._answer(query, "🔒 Yeh job aapka nahi hai.", alert=True)
            return
        if old.status not in FINISHED_STATES:
            await self._answer(query, "⏳ Job abhi chal raha hai.", alert=True)
            return
        if not self._rate_ok(user_id, consume=True):
            await self._answer(
                query,
                texts.RATE_LIMITED.format(limit=self.settings.rate_limit_per_10min),
                alert=True,
            )
            return

        message = query.message
        if message is None:
            await self._answer(query, texts.UNKNOWN_BUTTON, alert=True)
            return
        await self._answer(query)
        self.manager.remove(old.id)
        self._retry_specs.pop(job_id, None)

        job = self._create_job(
            user_id=user_id,
            chat_id=message.chat_id,
            thread_id=message.message_thread_id,
            url=spec.url,
            format_id=spec.format_id,
            audio_only=spec.audio_only,
            title=spec.title,
            label=spec.label,
        )
        await self._edit_message(
            query,
            texts.progress_text(job, spec.label),
            keyboards.cancel_keyboard(job.id),
        )
        self._spawn(self._track(bot, message, job, spec.label))

    async def _handle_settings(self, query: Any, user_id: int, args: list[str]) -> None:
        if not args:
            await self._answer(query)
            return
        action = args[0]
        prefs = self.users.get(user_id)

        if action == "quality" and len(args) >= 2:
            prefs = self.users.update(user_id, default_quality=args[1])
        elif action == "doc":
            prefs = self.users.update(user_id, send_as_document=not prefs.send_as_document)
        elif action == "close":
            await self._answer(query)
            await self._edit_message(query, "✅ Settings save ho gayi.")
            return
        else:
            await self._answer(query, texts.UNKNOWN_BUTTON, alert=True)
            return

        await self._answer(query)
        await self._edit_message(
            query,
            texts.settings_text(prefs.default_quality, prefs.send_as_document),
            keyboards.settings_keyboard(prefs.default_quality, prefs.send_as_document),
        )

    # ---------------------------------------------------------------- jobs

    def _create_job(
        self,
        *,
        user_id: int,
        chat_id: int,
        thread_id: int | None,
        url: str,
        format_id: str | None,
        audio_only: bool,
        title: str,
        label: str,
        thumbnail: str | None = None,
        duration: int | None = None,
    ) -> Job:
        job = self.manager.create(
            url,
            format_id=format_id,
            audio_only=audio_only,
            user_id=user_id,
            chat_id=chat_id,
            thread_id=thread_id,
            label=label,
            thumbnail=thumbnail,
            duration=duration,
        )
        job.title = title
        self._job_owner[job.id] = user_id
        self._user_jobs.setdefault(user_id, set()).add(job.id)
        self._retry_specs[job.id] = RetrySpec(
            url=url,
            format_id=format_id,
            audio_only=audio_only,
            title=title,
            label=label,
        )
        return job

    async def _track(self, bot: Bot, message: Message, job: Job, label: str) -> None:
        interval = max(1.5, self.settings.telegram_progress_interval_seconds)
        try:
            while job.status not in FINISHED_STATES:
                await asyncio.sleep(interval)
                if job.status in FINISHED_STATES:
                    break
                position = self.manager.queue_position(job.id)
                await self._safe_edit(
                    message,
                    texts.progress_text(job, label, position),
                    keyboards.cancel_keyboard(job.id),
                )

            if job.status == "finished":
                await self._safe_edit(
                    message, texts.uploading_text(job), keyboards.empty_keyboard()
                )
                result = await deliver(
                    bot,
                    job,
                    settings=self.settings,
                    send_as_document=self._send_as_document(job),
                )
                if result.ok:
                    await self._safe_edit(
                        message, texts.delivered_text(job), keyboards.done_keyboard()
                    )
                    self._retry_specs.pop(job.id, None)
                    self.manager.remove(job.id)
                elif result.too_big:
                    await self._safe_edit(
                        message,
                        texts.too_big_text(
                            result.size or job.filesize or 0,
                            self.settings.telegram_max_upload_mb,
                            self.settings.telegram_local_mode,
                        ),
                        keyboards.new_link_keyboard(),
                    )
                else:
                    await self._safe_edit(
                        message,
                        texts.upload_failed_text(result.error),
                        keyboards.retry_keyboard(job.id),
                    )
            elif job.status == "cancelled":
                await self._safe_edit(
                    message,
                    texts.cancelled_text(job),
                    keyboards.retry_keyboard(job.id),
                )
            else:
                await self._safe_edit(
                    message,
                    texts.failed_text(job),
                    keyboards.retry_keyboard(job.id),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Job %s track karte waqt error", job.id)
            await self._safe_edit(
                message,
                texts.UNEXPECTED,
                keyboards.retry_keyboard(job.id),
            )
        finally:
            self._finish_job(job.id)

    def _finish_job(self, job_id: str) -> None:
        owner = self._job_owner.pop(job_id, None)
        if owner is not None:
            jobs = self._user_jobs.get(owner)
            if jobs is not None:
                jobs.discard(job_id)
                if not jobs:
                    self._user_jobs.pop(owner, None)

    def _send_as_document(self, job: Job) -> bool:
        if job.user_id is None:
            return False
        return self.users.get(job.user_id).send_as_document

    # -------------------------------------------------------------- message

    async def _edit_message(
        self,
        query: Any,
        text: str,
        markup: InlineKeyboardMarkup | None = None,
    ) -> Message | None:
        """Card update karo — photo card ke liye caption edit use hota hai."""
        message = query.message
        if message is None:
            return None
        if markup is None:
            markup = keyboards.empty_keyboard()
        try:
            await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
            return message
        except TelegramError as exc:
            if "not modified" in str(exc).lower():
                return message
        with contextlib.suppress(TelegramError):
            await message.edit_caption(caption=text, parse_mode="HTML", reply_markup=markup)
            return message
        with contextlib.suppress(TelegramError):
            return await message.chat.send_message(
                text,
                parse_mode="HTML",
                reply_markup=markup,
                message_thread_id=message.message_thread_id,
            )
        return None

    @staticmethod
    async def _safe_edit(message: Message, text: str, markup: InlineKeyboardMarkup) -> None:
        """Progress edit; photo message ho to caption badal deta hai."""
        try:
            await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
            return
        except TelegramError as exc:
            if "not modified" in str(exc).lower():
                return
        with contextlib.suppress(TelegramError):
            await message.edit_caption(caption=text, parse_mode="HTML", reply_markup=markup)

    async def _answer(self, query: Any, text: str | None = None, *, alert: bool = False) -> None:
        with contextlib.suppress(TelegramError):
            await query.answer(text=text, show_alert=alert)

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _find_format(info: Any, format_id: str | None):
        if not format_id:
            return None
        return next((option for option in info.formats if option.id == format_id), None)

    @classmethod
    def _format_label(cls, info: Any, format_id: str | None) -> str:
        option = cls._find_format(info, format_id)
        if option:
            return option.label
        if format_id and format_id.startswith("v") and format_id[1:].isdigit():
            return f"{format_id[1:]}p (or best)"
        return "Best available"

    @staticmethod
    def _is_private(update: Update) -> bool:
        return bool(update.effective_chat and update.effective_chat.type == "private")

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        error = context.error
        if isinstance(error, TelegramError) and "not modified" in str(error).lower():
            return
        logger.error(
            "Update process karte waqt error: %s",
            error,
            exc_info=(type(error), error, error.__traceback__) if error else None,
        )
        if isinstance(update, Update) and update.effective_message:
            with contextlib.suppress(TelegramError):
                await update.effective_message.reply_text(texts.UNEXPECTED)


def _run(application: Application, settings: Settings) -> None:
    if settings.telegram_webhook_enabled:
        base = (settings.telegram_webhook_url or "").rstrip("/")
        secret = (settings.telegram_webhook_secret or "").strip()
        if not base.startswith("https://"):
            raise SystemExit("CLIPNEST_TELEGRAM_WEBHOOK_URL https:// se shuru hona chahiye.")
        if secret and not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret):
            raise SystemExit(
                "CLIPNEST_TELEGRAM_WEBHOOK_SECRET mein sirf A-Z, a-z, 0-9, _ aur - allowed hain."
            )
        path = secret or "clipnest"
        logger.info("Webhook mode: %s/%s", base, path)
        application.run_webhook(
            listen=settings.telegram_webhook_listen,
            port=settings.telegram_webhook_port,
            url_path=path,
            webhook_url=f"{base}/{path}",
            secret_token=secret or None,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        return
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings()
    try:
        application = ClipNestBot(settings).build_application()
    except RuntimeError as exc:
        raise SystemExit(f"❌ {exc}") from exc
    _run(application, settings)
