"""Listener command file: ``~/.local/share/remotask/listener.cmd``.

The CLI side (``remotask telegram start|stop``) writes this file then signals
the daemon with SIGUSR1. The daemon reads the file in its signal handler and
applies the command iff the ``seq`` is greater than the last-applied value
(which keeps rapid re-issues of the same command idempotent).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from remotask.core import paths

Command = Literal["start", "stop"]


@dataclass
class ListenerCmd:
    seq: int
    command: Command

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> ListenerCmd:
        data = json.loads(text)
        cmd = data["command"]
        if cmd not in ("start", "stop"):
            raise ValueError(f"unknown command {cmd!r}; expected start|stop")
        return cls(seq=int(data["seq"]), command=cmd)


def cmd_path() -> Path:
    return paths.data_dir() / "listener.cmd"


def read(path: Path | None = None) -> ListenerCmd | None:
    """Return the pending command, or ``None`` when the file is absent/invalid."""
    p = path if path is not None else cmd_path()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        return ListenerCmd.from_json(text)
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def write(cmd: ListenerCmd, path: Path | None = None) -> None:
    """Write ``cmd`` to disk atomically with mode 0600."""
    p = path if path is not None else cmd_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, cmd.to_json().encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    tmp.replace(p)
    p.chmod(0o600)


def next_seq(after: int) -> int:
    """Return the next sequence number to use after ``after``."""
    return after + 1
