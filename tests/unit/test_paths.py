from __future__ import annotations

from pathlib import Path

import pytest

from remote_task.core import paths


def test_config_dir_respects_xdg_config_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgcfg"))
    assert paths.config_dir() == tmp_path / "xdgcfg" / "remote-task"


def test_data_dir_respects_xdg_data_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdgdata"))
    assert paths.data_dir() == tmp_path / "xdgdata" / "remote-task"


def test_cache_dir_respects_xdg_cache_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdgcache"))
    assert paths.cache_dir() == tmp_path / "xdgcache" / "remote-task"


def test_default_fallback_when_xdg_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = paths.config_dir()
    data = paths.data_dir()
    assert cfg.is_relative_to(tmp_path)
    assert data.is_relative_to(tmp_path)
    assert cfg.name == "remote-task"
    assert data.name == "remote-task"


def test_derived_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "d"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    assert paths.pid_path() == tmp_path / "d" / "remote-task" / "daemon.pid"
    assert paths.log_dir() == tmp_path / "d" / "remote-task" / "logs"
    assert paths.db_path() == tmp_path / "d" / "remote-task" / "state.db"
    assert paths.config_path() == tmp_path / "c" / "remote-task" / "config.toml"


def test_returns_pathlib_objects(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    for fn in (paths.config_dir, paths.data_dir, paths.cache_dir,
               paths.log_dir, paths.pid_path, paths.db_path, paths.config_path):
        assert isinstance(fn(), Path)
