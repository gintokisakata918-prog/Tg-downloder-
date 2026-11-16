"""Offline tests for the Telegram bot helpers (no network, no token)."""

from __future__ import annotations

import pytest

pytest.importorskip("telegram", reason="install the `bot` extra to run these tests")

from app.telegram_bot import (
    extract_url,
    format_duration,
    format_size,
    parse_allowed_users,
    progress_bar,
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
