"""In-memory download job manager.

Jobs live for the lifetime of the process; finished files are cleaned up by a
periodic janitor once their TTL expires.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

from app.config import Settings
from app.engines.base import BaseEngine, DownloadCancelled, EngineError
from app.schemas import JobStatus

logger = logging.getLogger(__name__)

FINISHED_STATES: set[JobStatus] = {"finished", "failed", "cancelled"}


@dataclass
class Job:
    id: str
    url: str
    directory: Path
    format_id: str | None = None
    audio_only: bool = False
    status: JobStatus = "queued"
    progress: float = 0.0
    speed: float | None = None
    eta: int | None = None
    title: str | None = None
    filename: str | None = None
    filesize: int | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cancel: Event = field(default_factory=Event)


class JobManager:
    def __init__(self, settings: Settings, engines: list[BaseEngine]) -> None:
        self.settings = settings
        self.engines = engines
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_downloads))

    # ---------------------------------------------------------------- public

    def engine_for(self, url: str) -> BaseEngine | None:
        return next((engine for engine in self.engines if engine.can_handle(url)), None)

    def create(self, url: str, *, format_id: str | None = None, audio_only: bool = False) -> Job:
        job_id = secrets.token_hex(6)
        directory = self.settings.download_dir / job_id
        directory.mkdir(parents=True, exist_ok=True)
        job = Job(
            id=job_id,
            url=url,
            directory=directory,
            format_id=format_id,
            audio_only=audio_only,
        )
        self._jobs[job_id] = job
        task = asyncio.create_task(self._run(job), name=f"clipnest-job-{job_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def active_count(self) -> int:
        return sum(1 for job in self._jobs.values() if job.status in {"queued", "running"})

    def cancel(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        job.cancel.set()
        if job.status == "queued":
            job.status = "cancelled"
            job.updated_at = time.time()
            shutil.rmtree(job.directory, ignore_errors=True)
        return job

    def remove(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        job.cancel.set()
        if job.status in FINISHED_STATES:
            shutil.rmtree(job.directory, ignore_errors=True)
            self._jobs.pop(job_id, None)
        return True

    def cleanup_expired(self) -> int:
        cutoff = time.time() - self.settings.job_ttl_minutes * 60
        removed = 0
        for job_id, job in list(self._jobs.items()):
            if job.updated_at < cutoff and job.status in FINISHED_STATES:
                shutil.rmtree(job.directory, ignore_errors=True)
                self._jobs.pop(job_id, None)
                removed += 1
        if self.settings.download_dir.is_dir():
            for directory in self.settings.download_dir.iterdir():
                if not directory.is_dir() or directory.name in self._jobs:
                    continue
                try:
                    if directory.stat().st_mtime < cutoff:
                        shutil.rmtree(directory, ignore_errors=True)
                        removed += 1
                except OSError:
                    continue
        return removed

    # --------------------------------------------------------------- internal

    async def _run(self, job: Job) -> None:
        try:
            async with self._semaphore:
                if job.cancel.is_set():
                    job.status = "cancelled"
                    return
                engine = self.engine_for(job.url)
                if engine is None:
                    raise EngineError("Is link ke liye koi engine available nahi hai.")

                job.status = "running"
                job.updated_at = time.time()

                def on_progress(percent: float, speed: float | None, eta: int | None) -> None:
                    job.progress = round(min(max(percent, 0.0), 100.0), 1)
                    job.speed = speed
                    job.eta = eta
                    job.updated_at = time.time()

                path = await engine.download(
                    job.url,
                    job.directory,
                    job.cancel,
                    on_progress,
                    format_id=job.format_id,
                    audio_only=job.audio_only,
                )
                if job.cancel.is_set():
                    raise DownloadCancelled
                if not path.is_file():
                    raise EngineError("Downloaded file missing hai.")

                job.filename = path.name
                job.title = path.stem
                job.filesize = path.stat().st_size
                job.progress = 100.0
                job.status = "finished"
        except DownloadCancelled:
            job.status = "cancelled"
            shutil.rmtree(job.directory, ignore_errors=True)
        except EngineError as exc:
            if job.cancel.is_set():
                job.status = "cancelled"
                shutil.rmtree(job.directory, ignore_errors=True)
            else:
                job.status = "failed"
                job.error = str(exc)[:400]
                logger.warning("Job %s failed: %s", job.id, exc)
        except Exception as exc:
            job.status = "failed"
            job.error = "Unexpected error. Dobara koshish karein."
            logger.exception("Job %s crashed", job.id, exc_info=exc)
        finally:
            job.updated_at = time.time()
            job.speed = None
            job.eta = None
