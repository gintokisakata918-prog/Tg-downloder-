"""Offline tests for the Telegram bot helpers (no network, no token)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("telegram", reason="install the `bot` extra to run these tests")

from app.bot import keyboards, texts
from app.bot.core import ClipNestBot
from app.config import Settings
from app.jobs import Job
from app.schemas import FormatOption, MediaInfo
from app.telegram_bot import (
    extract_url,
    format_duration,
    format_size,
    parse_allowed_users,
    progress_bar,
)


def sample_info() -> MediaInfo:
    return MediaInfo(
        url="https://example.com/watch/1",
        title="<b>Test</b> & clip",
        engine="yt-dlp",
        duration=125,
        uploader="Tester",
        formats=[
            FormatOption(id="v1080", label="1080p", height=1080, filesize=200 * 1024 * 1024),
            FormatOption(id="v720", label="720p", height=720, filesize=20 * 1024 * 1024),
        ],
    )


def test_extract_url_finds_link_inside_text() -> None:
    text = "yeh dekho https://example.com/watch/1?x=1, mazedaar hai!"
    assert extract_url(text) == "https://example.com/watch/1?x=1"


def test_extract_url_ignores_plain_text() -> None:
    assert extract_url("koi link nahi hai") is None
    assert extract_url("") is None


def test_format_size() -> None:
    assert format_size(0) == "0 B"
    assert format_size(512) == "512 B"
    assert format_size(1536) == "1.5 KB"
    assert format_size(5 * 1024 * 1024) == "5.0 MB"


def test_format_duration() -> None:
    assert format_duration(42) == "0:42"
    assert format_duration(3 * 3600 + 61) == "3:01:01"
    assert format_duration(None) == "-"


def test_parse_allowed_users() -> None:
    assert parse_allowed_users("123, 456;789") == {123, 456, 789}
    assert parse_allowed_users("") == set()
    assert parse_allowed_users("abc, 42") == {42}


def test_progress_bar_bounds() -> None:
    assert progress_bar(0) == "░" * 12
    assert progress_bar(100) == "█" * 12
    assert len(progress_bar(50)) == 12


def test_quality_from_pref() -> None:
    assert texts.quality_from_pref("best") == (None, False)
    assert texts.quality_from_pref("720") == ("v720", False)
    assert texts.quality_from_pref("audio") == (None, True)
    assert texts.quality_from_pref("garbage") == (None, False)


def test_quality_label_marks_oversized() -> None:
    info = sample_info()
    small = texts.quality_label(info.formats[1], limit_bytes=50 * 1024 * 1024)
    big = texts.quality_label(info.formats[0], limit_bytes=50 * 1024 * 1024)
    assert "20.0 MB" in small
    assert "⚠️" not in small
    assert "⚠️" in big
    assert len(big) <= 60


def test_info_caption_escapes_user_text() -> None:
    caption = texts.info_caption(
        sample_info(), limit_mb=50, default_quality="720", strict_size=True
    )
    assert "&lt;b&gt;Test&lt;/b&gt; &amp; clip" in caption
    assert "<b><b>" not in caption
    assert "720p" in caption


def test_callback_roundtrip() -> None:
    data = keyboards.cb("q", "abc123", "v720")
    assert data == "q:abc123:v720"
    assert keyboards.parse_callback(data) == ("q", ["abc123", "v720"])
    assert keyboards.parse_callback("link") == ("link", [])
    assert keyboards.parse_callback(None) == ("", [])


def test_progress_text_shows_queue_position(tmp_path: Path) -> None:
    job = Job(id="abc", url="https://example.com/a.mp4", directory=tmp_path)
    job.title = "Test clip"
    job.status = "queued"
    job.progress = 0
    text = texts.progress_text(job, "720p", queue_position=3)
    assert "Test clip" in text
    assert "position 3" in text


def test_build_application_requires_token(tmp_path: Path) -> None:
    settings = Settings(
        telegram_bot_token=None,
        download_dir=tmp_path / "downloads",
        telegram_users_file=tmp_path / "users.json",
        telegram_probes_file=tmp_path / "probes.json",
    )
    with pytest.raises(RuntimeError):
        ClipNestBot(settings).build_application()


def test_build_application_with_token(tmp_path: Path) -> None:
    settings = Settings(
        telegram_bot_token="123456:AAExampleToken",
        download_dir=tmp_path / "downloads",
        telegram_users_file=tmp_path / "users.json",
        telegram_probes_file=tmp_path / "probes.json",
        rate_limit_per_10min=0,
    )
    bot = ClipNestBot(settings)
    application = bot.build_application()
    assert application.bot.token == settings.telegram_bot_token
    assert {handler.__class__.__name__ for handler in application.handlers[0]} == {
        "CommandHandler",
        "CallbackQueryHandler",
        "MessageHandler",
    }
