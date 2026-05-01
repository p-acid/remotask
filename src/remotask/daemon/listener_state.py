"""Listener state file: ``~/.local/share/remotask/listener.state``.

Single-writer (the daemon), atomic write (write tmp + rename), 0600. Readers
include ``remotask telegram status`` and any future health-check tooling. The
schema follows ``data-model.md`` plus a ``last_update_id`` field used by the
listener to resume long-poll across restarts.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from remotask.core import paths

# At-most-one-write-per-second throttling unless the state changed.
_HEARTBEAT_MIN_INTERVAL = 1.0


@dataclass
class ListenerState:
    """Snapshot of listener health, persisted between heartbeats."""

    running: bool = False
    started_at: float = 0.0
    last_poll_ok_at: float = 0.0
    consecutive_failures: int = 0
    active_sessions: int = 0
    whitelist_size: int = 0
    degraded: bool = False
    last_update_id: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> ListenerState:
        data = json.loads(text)
        # Filter to known fields so a forward-compatible reader doesn't fail
        # if the daemon adds a new key in a future version.
        kwargs = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**kwargs)


def state_path() -> Path:
    return paths.data_dir() / "listener.state"


def read(path: Path | None = None) -> ListenerState | None:
    """Return the persisted state, or ``None`` if the file is missing/unparseable."""
    p = path if path is not None else state_path()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        return ListenerState.from_json(text)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def write_atomic(state: ListenerState, path: Path | None = None) -> None:
    """Serialize ``state`` to disk atomically with mode 0600."""
    p = path if path is not None else state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, state.to_json().encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    tmp.replace(p)
    p.chmod(0o600)


class HeartbeatWriter:
    """Throttled writer: writes at most once/second unless state actually changed."""

    def __init__(self, *, path: Path | None = None) -> None:
        self._path = path
        self._last_write_at = 0.0
        self._last_serialized: str | None = None

    def maybe_write(self, state: ListenerState, *, now: float) -> bool:
        """Persist ``state`` if changed or if interval elapsed; return True iff written."""
        serialized = state.to_json()
        if (
            serialized == self._last_serialized
            and now - self._last_write_at < _HEARTBEAT_MIN_INTERVAL
        ):
            return False
        write_atomic(state, self._path)
        self._last_write_at = now
        self._last_serialized = serialized
        return True
