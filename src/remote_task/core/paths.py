"""XDG-compliant path resolution for remote-task."""
from __future__ import annotations

from pathlib import Path

from platformdirs import PlatformDirs

_APP = "remote-task"


def _dirs() -> PlatformDirs:
    return PlatformDirs(_APP, appauthor=False, roaming=False)


def config_dir() -> Path:
    return Path(_dirs().user_config_dir)


def data_dir() -> Path:
    return Path(_dirs().user_data_dir)


def cache_dir() -> Path:
    return Path(_dirs().user_cache_dir)


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
