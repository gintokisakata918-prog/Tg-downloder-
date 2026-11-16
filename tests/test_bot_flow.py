"""End-to-end-ish bot flow test with fakes — no Telegram network calls."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("telegram", reason="install the `bot` extra to run these tests")

from app.bot.core import ClipNestBot
from app.config import Settings
from app.engines.base import BaseEngine
from app.schemas import FormatOption, MediaInfo


class FakeEngine(BaseEngine):
    name = "fake"

    def can_handle(self, url: str) -> bool:
        return True

    async def probe(self, url: str) -> MediaInfo:
        return MediaInfo(
            url=url,
            title="Flow test clip",
            engine=self.name,
            duration=42,
            uploader="Tester",
            formats=[FormatOption(id="v720", label="720p", height=720, filesize=5 * 1024 * 1024)],
        )

    async def download(
        self,
        url: str,
        target_dir: Path,
        cancel,
        on_progress,
        *,
        format_id: str | None = None,
        audio_only: bool = False,
    ) -> Path:
        assert format_id == "v720"
        assert audio_only is False
        path = target_dir / "flow.mp4"
        path.write_bytes(b"fake video bytes")
        on_progress(100.0, None, None)
        return path


def make_update(*, text: str | None = None, callback: str | None = None):
    message = MagicMock()
    message.chat_id = 42
    message.message_thread_id = None
    message.text = text
    message.reply_text = AsyncMock()
    message.reply_photo = AsyncMock()
    message.edit_text = AsyncMock()
    message.edit_caption = AsyncMock()
    message.delete = AsyncMock()
    placeholder = MagicMock()
    placeholder.edit_text = AsyncMock()
    placeholder.delete = AsyncMock()
    placeholder.reply_text = AsyncMock()
    message.reply_text.return_value = placeholder

    user = MagicMock()
    user.id = 7

    update = MagicMock()
    update.effective_user = user
    update.effective_message = message
    update.effective_chat.type = "private"

    if callback is not None:
        query = MagicMock()
        query.data = callback
        query.message = message
        query.answer = AsyncMock()
        update.callback_query = query
    else:
        update.callback_query = None

    return update, message, placeholder


def test_probe_then_download_flow(tmp_path: Path) -> None:
    settings = Settings(
        download_dir=tmp_path / "downloads",
        allow_private_hosts=True,
        rate_limit_per_10min=0,
        max_concurrent_downloads=1,
        telegram_generate_thumbnail=False,
        telegram_progress_interval_seconds=1.5,
        telegram_users_file=tmp_path / "users.json",
        telegram_probes_file=tmp_path / "probes.json",
    )
    bot = ClipNestBot(settings)
    bot.manager.engines.insert(0, FakeEngine())

    async def scenario() -> None:
        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_chat_action = AsyncMock()
        context.bot.send_video = AsyncMock()
        context.bot.send_audio = AsyncMock()
        context.bot.send_document = AsyncMock()
        context.bot.send_message = AsyncMock()

        update, _message, placeholder = make_update(text="http://127.0.0.1/clip.mp4")
        await bot.on_text(update, context)

        assert bot.probes._probes, "probe store mein result hona chahiye"
        probe_id = next(iter(bot.probes._probes))
        caption = placeholder.edit_text.call_args.args[0]
        assert "Flow test clip" in caption
        markup = placeholder.edit_text.call_args.kwargs["reply_markup"]

        callback = next(
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data and button.callback_data.startswith("q:")
        )
        assert probe_id in callback

        update2, message2, _ = make_update(callback=callback)
        await bot.on_callback(update2, context)

        job_id = next(iter(bot._job_owner))
        await asyncio.sleep(1.8)

        context.bot.send_video.assert_awaited()
        assert context.bot.send_video.await_args.kwargs["filename"] == "flow.mp4"
        assert bot.manager.get(job_id) is None, "success ke baad job cleanup hona chahiye"
        # Update card par final success text aana chahiye.
        edited = [call.args[0] for call in message2.edit_text.await_args_list]
        assert any("File bhej di gayi" in text for text in edited)

    asyncio.run(scenario())
