"""Chhoti, disk-backed stores for bot settings aur probe buttons.

Bot restart hone par bhi quality buttons aur user settings kaam karte rahein —
isliye dono cheezein JSON files mein atomically save hoti hain. Koi database
ki zaroorat nahi, aur files insaan padh sakte hain.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from app.bot import texts
from app.schemas import MediaInfo

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UserPrefs:
    default_quality: str = "best"
    send_as_document: bool = False


@dataclass(slots=True)
class Probe:
    id: str
    user_id: int
    url: str
    info: MediaInfo
    created_at: float


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Store file corrupt hai, ignore kar raha hoon: %s", path)
        return {}
    return raw if isinstance(raw, dict) else {}


class UserStore:
    """Per-user preferences, keyed by Telegram user id."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._users: dict[int, UserPrefs] = {}
        self._load()

    def _load(self) -> None:
        raw = _read_json(self.path)
        for key, value in raw.get("users", {}).items():
            try:
                user_id = int(key)
                prefs = UserPrefs(
                    default_quality=str(value.get("default_quality", "best")),
                    send_as_document=bool(value.get("send_as_document", False)),
                )
            except (AttributeError, TypeError, ValueError):
                continue
            if prefs.default_quality not in texts.QUALITY_KEYS:
                prefs.default_quality = "best"
            self._users[user_id] = prefs

    def get(self, user_id: int) -> UserPrefs:
        prefs = self._users.get(user_id)
        if prefs is None:
            return UserPrefs()
        return UserPrefs(
            default_quality=prefs.default_quality,
            send_as_document=prefs.send_as_document,
        )

    def update(self, user_id: int, **changes: object) -> UserPrefs:
        prefs = self.get(user_id)
        if "default_quality" in changes:
            quality = str(changes["default_quality"])
            if quality in texts.QUALITY_KEYS:
                prefs.default_quality = quality
        if "send_as_document" in changes:
            prefs.send_as_document = bool(changes["send_as_document"])
        self._users[user_id] = prefs
        self.save()
        return prefs

    def save(self) -> None:
        payload = {
            "version": 1,
            "users": {
                str(user_id): asdict(prefs) for user_id, prefs in sorted(self._users.items())
            },
        }
        try:
            _atomic_write(self.path, payload)
        except OSError:
            logger.exception("User settings save nahi hui: %s", self.path)


class ProbeStore:
    """Short-lived probe results so inline buttons survive restarts."""

    def __init__(
        self,
        path: Path,
        *,
        ttl_minutes: int = 120,
        max_entries: int = 300,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.ttl_seconds = max(1, ttl_minutes) * 60
        self.max_entries = max(1, max_entries)
        self._clock = clock
        self._probes: dict[str, Probe] = {}
        self._load()

    def _load(self) -> None:
        raw = _read_json(self.path)
        now = self._clock()
        for probe_id, value in raw.get("probes", {}).items():
            try:
                info = MediaInfo.model_validate(value["info"])
                probe = Probe(
                    id=str(value.get("id") or probe_id),
                    user_id=int(value["user_id"]),
                    url=str(value["url"]),
                    info=info,
                    created_at=float(value["created_at"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if now - probe.created_at <= self.ttl_seconds:
                self._probes[probe.id] = probe
        self._prune()

    def put(self, user_id: int, url: str, info: MediaInfo) -> Probe:
        probe = Probe(
            id=secrets.token_hex(6),
            user_id=user_id,
            url=url,
            info=info,
            created_at=self._clock(),
        )
        self._probes[probe.id] = probe
        self._prune()
        self.save()
        return probe

    def get(self, probe_id: str) -> Probe | None:
        probe = self._probes.get(probe_id)
        if probe is None:
            return None
        if self._clock() - probe.created_at > self.ttl_seconds:
            self._probes.pop(probe_id, None)
            self.save()
            return None
        return probe

    def pop(self, probe_id: str) -> Probe | None:
        probe = self.get(probe_id)
        if probe is not None:
            self._probes.pop(probe_id, None)
            self.save()
        return probe

    def cleanup(self) -> int:
        before = len(self._probes)
        self._prune()
        removed = before - len(self._probes)
        if removed:
            self.save()
        return removed

    def _prune(self) -> None:
        now = self._clock()
        expired = [
            probe_id
            for probe_id, probe in self._probes.items()
            if now - probe.created_at > self.ttl_seconds
        ]
        for probe_id in expired:
            self._probes.pop(probe_id, None)

        if len(self._probes) > self.max_entries:
            ordered = sorted(self._probes.values(), key=lambda probe: probe.created_at)
            for probe in ordered[: len(self._probes) - self.max_entries]:
                self._probes.pop(probe.id, None)

    def save(self) -> None:
        payload = {
            "version": 1,
            "probes": {
                probe.id: {
                    "id": probe.id,
                    "user_id": probe.user_id,
                    "url": probe.url,
                    "created_at": probe.created_at,
                    "info": probe.info.model_dump(mode="json"),
                }
                for probe in self._probes.values()
            },
        }
        try:
            _atomic_write(self.path, payload)
        except OSError:
            logger.exception("Probe store save nahi hua: %s", self.path)

    def clear(self) -> None:
        self._probes.clear()
        self.save()
