"""API tests that never touch the network."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from app.config import Settings
from app.engines.base import BaseEngine
from app.main import create_app
from app.schemas import FormatOption, MediaInfo
from app.security import UnsafeURLError, normalize_url
from fastapi.testclient import TestClient


class FakeEngine(BaseEngine):
    """Deterministic engine so the tests run fully offline."""

    name = "fake"

    def can_handle(self, url: str) -> bool:
        return True

    async def probe(self, url: str) -> MediaInfo:
        return MediaInfo(
            url=url,
            title="Test clip",
            engine=self.name,
            duration=42,
            audio_available=True,
            formats=[FormatOption(id="v1080", label="1080p", height=1080)],
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
        on_progress(50.0, 1024.0, 1)
        path = target_dir / "clip.mp4"
        path.write_bytes(b"clipnest")
        on_progress(100.0, None, None)
        return path


def make_client(tmp_path: Path, *, allow_private: bool = True) -> TestClient:
    settings = Settings(
        download_dir=tmp_path / "downloads",
        allow_private_hosts=allow_private,
        rate_limit_per_10min=0,
    )
    app = create_app(settings)
    client = TestClient(app)
    app.state.engines.insert(0, FakeEngine())
    return client


@pytest.fixture
def client(tmp_path: Path):
    with make_client(tmp_path) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "fake" in body["engines"]


def test_index_page(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "ClipNest" in response.text


def test_info_returns_metadata(client: TestClient) -> None:
    response = client.post("/api/info", json={"url": "https://example.com/watch/1"})
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Test clip"
    assert body["formats"][0]["id"] == "v1080"


def test_rejects_non_http_scheme(client: TestClient) -> None:
    response = client.post("/api/info", json={"url": "file:///etc/passwd"})
    assert response.status_code == 400


def test_rejects_private_hosts(tmp_path: Path) -> None:
    with make_client(tmp_path, allow_private=False) as test_client:
        response = test_client.post("/api/info", json={"url": "http://127.0.0.1/x.mp4"})
    assert response.status_code == 400


def test_rejects_unknown_quality(client: TestClient) -> None:
    response = client.post(
        "/api/download",
        json={"url": "https://example.com/watch/1", "format_id": "drop table"},
    )
    assert response.status_code == 400


def test_download_lifecycle(client: TestClient) -> None:
    response = client.post(
        "/api/download",
        json={"url": "https://example.com/watch/1", "format_id": "v1080"},
    )
    assert response.status_code == 202
    job = response.json()
    assert job["status"] in {"queued", "running"}

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        detail = client.get(f"/api/jobs/{job['id']}").json()
        if detail["status"] in {"finished", "failed"}:
            break
        time.sleep(0.05)

    assert detail["status"] == "finished", detail
    assert detail["filename"] == "clip.mp4"
    assert detail["download_url"] == f"/api/jobs/{job['id']}/file"

    file_response = client.get(detail["download_url"])
    assert file_response.status_code == 200
    assert file_response.content == b"clipnest"


def test_unknown_job(client: TestClient) -> None:
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/jobs/nope/file").status_code == 404


def test_job_file_conflict(client: TestClient) -> None:
    response = client.post("/api/download", json={"url": "https://example.com/watch/1"})
    job_id = response.json()["id"]
    file_response = client.get(f"/api/jobs/{job_id}/file")
    # Either still in progress (409) or already finished (200).
    assert file_response.status_code in {200, 409}


def test_normalize_url_rejects_garbage() -> None:
    with pytest.raises(UnsafeURLError):
        normalize_url("not a url")
    with pytest.raises(UnsafeURLError):
        normalize_url("ftp://example.com/file")
    assert normalize_url("  https://example.com/a?b=1  ") == "https://example.com/a?b=1"
