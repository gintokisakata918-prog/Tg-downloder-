"""ClipNest HTTP API and static frontend."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import BASE_DIR, Settings, get_settings
from app.engines import DirectEngine, EngineError, YtdlpEngine
from app.engines.ytdlp import validate_format_id
from app.jobs import Job, JobManager
from app.schemas import DownloadRequest, InfoRequest, JobView, MediaInfo
from app.security import UnsafeURLError, ensure_public_url

logger = logging.getLogger(__name__)
STATIC_DIR = BASE_DIR / "static"


class RateLimiter:
    """Small in-memory sliding-window limiter, keyed by client address."""

    def __init__(self, limit: int, window_seconds: int = 600) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


def _job_view(job: Job) -> JobView:
    return JobView(
        id=job.id,
        status=job.status,
        progress=job.progress,
        speed=job.speed,
        eta=job.eta,
        title=job.title,
        filename=job.filename,
        filesize=job.filesize,
        error=job.error,
        created_at=job.created_at,
        download_url=f"/api/jobs/{job.id}/file" if job.status == "finished" else None,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engines = [DirectEngine(settings), YtdlpEngine(settings)]
    manager = JobManager(settings, engines)
    limiter = RateLimiter(settings.rate_limit_per_10min)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.download_dir.mkdir(parents=True, exist_ok=True)
        janitor = asyncio.create_task(_janitor(manager))
        try:
            yield
        finally:
            janitor.cancel()
            with suppress(asyncio.CancelledError):
                await janitor

    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        description="Self-hosted video downloader.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.manager = manager
    app.state.engines = engines
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def check_rate(request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        if not limiter.allow(client):
            raise HTTPException(429, "Bahut zyada requests. Thodi der baad koshish karein.")

    async def validated_url(raw: str) -> str:
        try:
            return await ensure_public_url(raw, allow_private=settings.allow_private_hosts)
        except UnsafeURLError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "engines": [engine.name for engine in engines],
            "active_jobs": manager.active_count(),
        }

    @app.post("/api/info", response_model=MediaInfo)
    async def info(payload: InfoRequest, request: Request) -> MediaInfo:
        check_rate(request)
        url = await validated_url(payload.url)
        engine = manager.engine_for(url)
        if engine is None:
            raise HTTPException(400, "Is link ke liye koi engine available nahi hai.")
        try:
            return await engine.probe(url)
        except EngineError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            logger.exception("Probe failed for %s", url)
            raise HTTPException(502, "Link check nahi ho paya. Dobara koshish karein.") from exc

    @app.post("/api/download", response_model=JobView, status_code=202)
    async def download(payload: DownloadRequest, request: Request) -> JobView:
        check_rate(request)
        url = await validated_url(payload.url)
        if manager.engine_for(url) is None:
            raise HTTPException(400, "Is link ke liye koi engine available nahi hai.")
        try:
            format_id = validate_format_id(payload.format_id)
        except EngineError as exc:
            raise HTTPException(400, str(exc)) from exc
        if format_id and payload.audio_only:
            format_id = None
        job = manager.create(url, format_id=format_id, audio_only=payload.audio_only)
        return _job_view(job)

    @app.get("/api/jobs/{job_id}", response_model=JobView)
    async def job_detail(job_id: str) -> JobView:
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(404, "Job nahi mila (purana ho kar delete ho gaya ho sakta hai).")
        return _job_view(job)

    @app.get("/api/jobs/{job_id}/file")
    async def job_file(job_id: str) -> FileResponse:
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(404, "Job nahi mila.")
        if job.status != "finished" or not job.filename:
            raise HTTPException(409, "File abhi ready nahi hai.")
        path = job.directory / job.filename
        if not path.is_file():
            raise HTTPException(404, "File delete ho chuki hai.")
        return FileResponse(path, filename=job.filename, media_type="application/octet-stream")

    @app.post("/api/jobs/{job_id}/cancel", response_model=JobView)
    async def job_cancel(job_id: str) -> JobView:
        job = manager.cancel(job_id)
        if job is None:
            raise HTTPException(404, "Job nahi mila.")
        return _job_view(job)

    @app.delete("/api/jobs/{job_id}", status_code=204)
    async def job_delete(job_id: str) -> None:
        if not manager.remove(job_id):
            raise HTTPException(404, "Job nahi mila.")

    return app


async def _janitor(manager: JobManager, interval_seconds: int = 300) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            removed = await asyncio.to_thread(manager.cleanup_expired)
            if removed:
                logger.info("Janitor removed %s expired job(s)", removed)
        except Exception:
            logger.exception("Janitor tick failed")


app = create_app()
