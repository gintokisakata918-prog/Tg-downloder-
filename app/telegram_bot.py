"""Telegram bot entry point.

Asli implementation `app.bot` package mein hai:

- `app.bot.core` — handlers, queue, progress, delivery
- `app.bot.texts` — Hindi/Hinglish messages + formatting helpers
- `app.bot.keyboards` — inline/reply keyboards
- `app.bot.store` — restart-safe user settings aur probe buttons
- `app.bot.delivery` — video/audio/document upload with fallbacks

Yeh module purane import paths (`app.telegram_bot`) ko compatible rakhta hai::

    CLIPNEST_TELEGRAM_BOT_TOKEN=12345:abc uv run --extra bot python -m app.telegram_bot
    # ya
    uv run clipnest-bot
"""

from __future__ import annotations

from app.bot.core import ClipNestBot, main
from app.bot.texts import (
    extract_url,
    format_duration,
    format_size,
    parse_allowed_users,
    progress_bar,
)

__all__ = [
    "ClipNestBot",
    "extract_url",
    "format_duration",
    "format_size",
    "main",
    "parse_allowed_users",
    "progress_bar",
]


if __name__ == "__main__":
    main()
