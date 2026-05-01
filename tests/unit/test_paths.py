from __future__ import annotations

from pathlib import Path

import pytest

from remotask.core import paths


def test_config_dir_respects_xdg_config_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgcfg"))
    assert paths.config_dir() == tmp_path / "xdgcfg" / "remotask"


def test_data_dir_respects_xdg_data_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdgdata"))
    assert paths.data_dir() == tmp_path / "xdgdata" / "remotask"


def test_cache_dir_respects_xdg_cache_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdgcache"))
    assert paths.cache_dir() == tmp_path / "xdgcache" / "remotask"


def test_default_fallback_when_xdg_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.config_dir() == tmp_path / ".config" / "remotask"
    assert paths.data_dir() == tmp_path / ".local" / "share" / "remotask"
    assert paths.cache_dir() == tmp_path / ".cache" / "remotask"


def test_xdg_overrides_take_precedence_over_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When both XDG_*_HOME and HOME are set, XDG_*_HOME wins."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    assert paths.config_dir() == tmp_path / "xdg-cfg" / "remotask"
    assert paths.data_dir() == tmp_path / "xdg-data" / "remotask"
    assert paths.cache_dir() == tmp_path / "xdg-cache" / "remotask"


def test_derived_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "d"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    assert paths.pid_path() == tmp_path / "d" / "remotask" / "daemon.pid"
    assert paths.log_dir() == tmp_path / "d" / "remotask" / "logs"
    assert paths.db_path() == tmp_path / "d" / "remotask" / "state.db"
    assert paths.config_path() == tmp_path / "c" / "remotask" / "config.toml"


def test_returns_pathlib_objects(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    for fn in (paths.config_dir, paths.data_dir, paths.cache_dir,
               paths.log_dir, paths.pid_path, paths.db_path, paths.config_path):
        assert isinstance(fn(), Path)
