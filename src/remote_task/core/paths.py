"""XDG Base Directory paths for remote-task.

Honors ``XDG_*_HOME`` environment variables when set; otherwise falls back
to the XDG defaults under ``$HOME``. This is enforced on every platform
(macOS included) per PRD §6.3 and constitution decision D12 — see
``specs/001-cli-bootstrap/research.md`` for rationale.
"""
from __future__ import annotations

import os
from pathlib import Path

_APP = "remote-task"


def _xdg(env_var: str, default_relative: str) -> Path:
    """Resolve an XDG base directory.

    1. ``$<env_var>`` if set (e.g. ``XDG_CONFIG_HOME``)
    2. ``$HOME / default_relative`` otherwise
    """
    base = os.environ.get(env_var)
    if base:
        return Path(base)
    return Path.home() / default_relative


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / _APP


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / _APP


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / _APP


def log_dir() -> Path:
    return data_dir() / "logs"


def db_path() -> Path:
    return data_dir() / "state.db"


def config_path() -> Path:
    return config_dir() / "config.toml"


def pid_path() -> Path:
    return data_dir() / "daemon.pid"


def sock_path() -> Path:
    return data_dir() / "daemon.sock"
