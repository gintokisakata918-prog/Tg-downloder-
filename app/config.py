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
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    @field_validator("download_dir", "cookies_file")
    @classmethod
    def _resolve_path(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        path = Path(value).expanduser()
        return path if path.is_absolute() else (BASE_DIR / path)

    @property
    def max_filesize_bytes(self) -> int:
        return self.max_filesize_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
