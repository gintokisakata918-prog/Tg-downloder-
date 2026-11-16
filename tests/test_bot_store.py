"""Offline tests for the disk-backed bot stores (no Telegram, no network)."""

from __future__ import annotations

from pathlib import Path

from app.bot.store import ProbeStore, UserStore
from app.schemas import FormatOption, MediaInfo


def sample_info() -> MediaInfo:
    return MediaInfo(
        url="https://example.com/watch/1",
        title="Test clip",
        engine="fake",
        duration=42,
        uploader="Tester",
        formats=[FormatOption(id="v720", label="720p", height=720, filesize=10 * 1024 * 1024)],
    )


def test_user_store_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    store = UserStore(path)
    assert store.get(111).default_quality == "best"
    assert store.get(111).send_as_document is False

    store.update(111, default_quality="720", send_as_document=True)

    reloaded = UserStore(path)
    prefs = reloaded.get(111)
    assert prefs.default_quality == "720"
    assert prefs.send_as_document is True
    # Doosre user par koi asar nahi.
    assert reloaded.get(222).default_quality == "best"


def test_user_store_ignores_invalid_quality(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "users.json")
    store.update(7, default_quality="720")
    store.update(7, default_quality="drop table")
    assert store.get(7).default_quality == "720"


def test_user_store_survives_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    path.write_text("{not json", encoding="utf-8")
    store = UserStore(path)
    assert store.get(1).default_quality == "best"


def test_probe_store_persists_and_expires(tmp_path: Path) -> None:
    path = tmp_path / "probes.json"
    now = [1_000.0]
    store = ProbeStore(path, ttl_minutes=1, clock=lambda: now[0])
    probe = store.put(5, "https://example.com/watch/1", sample_info())

    reloaded = ProbeStore(path, ttl_minutes=1, clock=lambda: now[0])
    found = reloaded.get(probe.id)
    assert found is not None
    assert found.user_id == 5
    assert found.info.title == "Test clip"

    now[0] += 61
    assert reloaded.get(probe.id) is None


def test_probe_store_pop_is_single_use(tmp_path: Path) -> None:
    store = ProbeStore(tmp_path / "probes.json", clock=lambda: 10.0)
    probe = store.put(1, "https://example.com/a.mp4", sample_info())
    assert store.pop(probe.id) is not None
    assert store.get(probe.id) is None


def test_probe_store_caps_entries(tmp_path: Path) -> None:
    now = [0.0]
    store = ProbeStore(tmp_path / "probes.json", max_entries=3, clock=lambda: now[0])
    ids = []
    for index in range(5):
        now[0] = float(index)
        ids.append(store.put(index, f"https://example.com/{index}", sample_info()).id)
    assert store.get(ids[0]) is None
    assert store.get(ids[1]) is None
    assert store.get(ids[-1]) is not None
