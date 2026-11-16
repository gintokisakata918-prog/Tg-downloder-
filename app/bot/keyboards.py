"""Inline aur reply keyboards for the Telegram bot."""

from __future__ import annotations

from collections.abc import Iterable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from app.bot import texts
from app.schemas import MediaInfo


def cb(kind: str, *parts: object) -> str:
    """Build callback data, e.g. ``cb("q", probe_id, "v720")``."""
    return ":".join([kind, *(str(part) for part in parts)])


def parse_callback(data: str | None) -> tuple[str, list[str]]:
    """Split callback data into ``(kind, args)`` without raising."""
    kind, _, rest = (data or "").partition(":")
    return kind, [part for part in rest.split(":") if part]


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [texts.MENU_LINK, texts.MENU_STATUS],
            [texts.MENU_SETTINGS, texts.MENU_HELP],
            [texts.MENU_CANCEL],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Video link yahan paste karein…",
    )


def quality_keyboard(
    probe_id: str,
    info: MediaInfo,
    *,
    limit_bytes: int,
    default_quality: str = "best",
    quality_limit: int = 8,
) -> InlineKeyboardMarkup:
    default_id, default_audio = texts.quality_from_pref(default_quality)
    default_label = (
        "MP3 (audio)"
        if default_audio
        else (_format_label(info, default_id) if default_id else "Best available")
    )

    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                f"⚡ Quick — {default_label}",
                callback_data=cb("d", probe_id),
            )
        ]
    ]

    current: list[InlineKeyboardButton] = []
    for option in info.formats[: max(1, quality_limit)]:
        current.append(
            InlineKeyboardButton(
                texts.quality_label(option, limit_bytes=limit_bytes, default_id=default_id),
                callback_data=cb("q", probe_id, option.id),
            )
        )
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)

    last_row = []
    if info.audio_available:
        last_row.append(InlineKeyboardButton("🎵 MP3 (audio)", callback_data=cb("a", probe_id)))
    last_row.append(InlineKeyboardButton("❌ Cancel", callback_data=cb("x", probe_id)))
    rows.append(last_row)
    return InlineKeyboardMarkup(rows)


def settings_keyboard(default_quality: str, send_as_document: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    for key, label in texts.QUALITY_CHOICES:
        marker = "✅ " if key == default_quality else ""
        current.append(
            InlineKeyboardButton(f"{marker}{label}", callback_data=cb("set", "quality", key))
        )
        if len(current) == 3:
            rows.append(current)
            current = []
    if current:
        rows.append(current)

    doc_marker = "✅ On" if send_as_document else "Off"
    rows.append(
        [InlineKeyboardButton(f"📎 Document mode: {doc_marker}", callback_data=cb("set", "doc"))]
    )
    rows.append([InlineKeyboardButton("✔️ Band karein", callback_data=cb("set", "close"))])
    return InlineKeyboardMarkup(rows)


def cancel_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🛑 Cancel", callback_data=cb("c", job_id))]]
    )


def retry_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔁 Retry", callback_data=cb("r", job_id))],
            [InlineKeyboardButton("🔗 Naya link", callback_data=cb("link"))],
        ]
    )


def done_keyboard() -> InlineKeyboardMarkup:
    return new_link_keyboard()


def new_link_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔗 Naya link bhejein", callback_data=cb("link"))]]
    )


def empty_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([])


def _format_label(info: MediaInfo, format_id: str | None) -> str:
    if not format_id:
        return "Best available"
    for option in info.formats:
        if option.id == format_id:
            return option.label
    return format_id


def button_rows(buttons: Iterable[InlineKeyboardButton], per_row: int = 2) -> list[list]:
    """Chhota helper for tests/custom keyboards."""
    rows: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    for button in buttons:
        current.append(button)
        if len(current) == per_row:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    return rows
