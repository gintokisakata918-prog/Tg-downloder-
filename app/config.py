"""Application settings, loaded from environment variables or a .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration.

    Every field can be overridden with a `CLIPNEST_`-prefixed environment
    variable (or a line in `.env`).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CLIPNEST_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ClipNest"
    download_dir: Path = BASE_DIR / "downloads"
    max_concurrent_downloads: int = 2
    job_ttl_minutes: int = 60
    max_duration_seconds: int = 3 * 60 * 60
    max_filesize_mb: int = 2048
    allow_private_hosts: bool = False
    cookies_file: Path | None = None
    request_timeout_seconds: int = 30
    rate_limit_per_10min: int = 20

    # ---- Telegram bot ----
    telegram_bot_token: str | None = None
    telegram_allowed_users: str = ""
    telegram_max_upload_mb: int = 50
    # Local Bot API server (https://github.com/tdlib/telegram-bot-api).
    # Example: http://127.0.0.1:8081 — isse 50 MB ki limit badh jaati hai.
    telegram_api_base_url: str | None = None
    # Webhook mode (production). Khali = long polling.
    telegram_webhook_url: str | None = None
    telegram_webhook_secret: str = ""
    telegram_webhook_listen: str = "0.0.0.0"
    telegram_webhook_port: int = 8080
    # Per-user settings aur probe buttons disk par — restart ke baad bhi kaam karein.
    telegram_users_file: Path = BASE_DIR / "data" / "bot_users.json"
    telegram_probes_file: Path = BASE_DIR / "data" / "bot_probes.json"
    telegram_probe_ttl_minutes: int = 120
    telegram_progress_interval_seconds: float = 4.0
    telegram_upload_timeout_seconds: int = 1800
    telegram_quality_limit: int = 8
    telegram_generate_thumbnail: bool = True
    # True = estimated size upload limit se badi ho to download shuru hi na karein.
    telegram_strict_size: bool = False

    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    @field_validator(
        "download_dir",
        "cookies_file",
        "telegram_users_file",
        "telegram_probes_file",
    )
    @classmethod
    def _resolve_path(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        path = Path(value).expanduser()
        return path if path.is_absolute() else (BASE_DIR / path)

    @field_validator("telegram_api_base_url", "telegram_webhook_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().rstrip("/")
        return cleaned or None

    @property
    def max_filesize_bytes(self) -> int:
        return self.max_filesize_mb * 1024 * 1024

    @property
    def telegram_local_mode(self) -> bool:
        return bool(self.telegram_api_base_url)

    @property
    def telegram_bot_api_url(self) -> str | None:
        if not self.telegram_api_base_url:
            return None
        return f"{self.telegram_api_base_url}/bot"

    @property
    def telegram_file_api_url(self) -> str | None:
        if not self.telegram_api_base_url:
            return None
        return f"{self.telegram_api_base_url}/file/bot"

    @property
    def telegram_upload_limit_bytes(self) -> int:
        return max(1, self.telegram_max_upload_mb) * 1024 * 1024

    @property
    def telegram_webhook_enabled(self) -> bool:
        return bool(self.telegram_webhook_url)

    @property
    def telegram_allowed_user_ids(self) -> set[int]:
        """Comma-separated user IDs; khali set ka matlab sab allowed."""
        return {
            int(chunk.strip())
            for chunk in self.telegram_allowed_users.replace(";", ",").split(",")
            if chunk.strip().lstrip("-").isdigit()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
