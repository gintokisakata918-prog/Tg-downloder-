"""Pydantic models shared by the API and the download engines."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

JobStatus = Literal["queued", "running", "finished", "failed", "cancelled"]


class FormatOption(BaseModel):
    """A single selectable quality."""

    id: str
    label: str
    ext: str = "mp4"
    kind: Literal["video", "audio"] = "video"
    height: int | None = None
    filesize: int | None = None


class MediaInfo(BaseModel):
    """Metadata returned by the probe step."""

    url: str
    title: str
    engine: str
    thumbnail: str | None = None
    duration: int | None = None
    uploader: str | None = None
    audio_available: bool = False
    formats: list[FormatOption] = Field(default_factory=list)


class InfoRequest(BaseModel):
    url: str = Field(min_length=3, max_length=2048)


class DownloadRequest(InfoRequest):
    format_id: str | None = Field(default=None, max_length=64)
    audio_only: bool = False


class JobView(BaseModel):
    """Public representation of a download job."""

    id: str
    status: JobStatus
    progress: float = 0.0
    speed: float | None = None
    eta: int | None = None
    title: str | None = None
    filename: str | None = None
    filesize: int | None = None
    error: str | None = None
    created_at: float
    download_url: str | None = None
