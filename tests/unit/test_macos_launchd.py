from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from remote_task.platform import macos_launchd


def _parse(rendered: str) -> dict:
    return plistlib.loads(rendered.encode("utf-8"))


def test_render_basic(tmp_path: Path) -> None:
    rendered = macos_launchd.render_plist(
        label="kr.mission-driven.remote-task",
        remote_task_path="/Users/samuel/.local/bin/remote-task",
        env={
            "PATH": "/opt/homebrew/bin:/usr/bin",
            "HOME": "/Users/samuel",
            "LANG": "en_US.UTF-8",
            "XDG_CONFIG_HOME": "/Users/samuel/.config",
            "XDG_DATA_HOME": "/Users/samuel/.local/share",
            "XDG_CACHE_HOME": "/Users/samuel/.cache",
        },
    )
    parsed = _parse(rendered)
    assert parsed["Label"] == "kr.mission-driven.remote-task"
    assert parsed["ProgramArguments"] == [
        "/Users/samuel/.local/bin/remote-task",
        "daemon",
        "run-foreground",
    ]
    assert parsed["RunAtLoad"] is True
    assert parsed["ThrottleInterval"] == 10


def test_render_keep_alive_dict() -> None:
    rendered = macos_launchd.render_plist(
        label="kr.mission-driven.remote-task",
        remote_task_path="/usr/local/bin/remote-task",
        env={
            "PATH": "/usr/bin",
            "HOME": "/Users/x",
            "LANG": "en_US.UTF-8",
            "XDG_CONFIG_HOME": "/Users/x/.config",
            "XDG_DATA_HOME": "/Users/x/.local/share",
            "XDG_CACHE_HOME": "/Users/x/.cache",
        },
    )
    parsed = _parse(rendered)
    keep_alive = parsed["KeepAlive"]
    assert isinstance(keep_alive, dict)
    assert keep_alive["SuccessfulExit"] is False
    assert keep_alive["Crashed"] is True


def test_render_path_env_preserved() -> None:
    rendered = macos_launchd.render_plist(
        label="kr.mission-driven.remote-task",
        remote_task_path="/usr/local/bin/remote-task",
        env={
            "PATH": "/opt/claude:/usr/bin",
            "HOME": "/Users/x",
            "LANG": "en_US.UTF-8",
            "XDG_CONFIG_HOME": "/Users/x/.config",
            "XDG_DATA_HOME": "/Users/x/.local/share",
            "XDG_CACHE_HOME": "/Users/x/.cache",
        },
    )
    parsed = _parse(rendered)
    assert "/opt/claude" in parsed["EnvironmentVariables"]["PATH"]


def test_label_validation_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        macos_launchd.validate_label("not a valid label")
    with pytest.raises(ValueError):
        macos_launchd.validate_label("")


def test_label_validation_accepts_reverse_domain() -> None:
    macos_launchd.validate_label("kr.mission-driven.remote-task")
    macos_launchd.validate_label("com.example.app")


def test_detect_environment_includes_required_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/opt/homebrew/bin:/usr/bin")
    monkeypatch.setenv("HOME", "/Users/test")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/Users/test/.config")
    monkeypatch.setenv("XDG_DATA_HOME", "/Users/test/.local/share")
    monkeypatch.setenv("XDG_CACHE_HOME", "/Users/test/.cache")
    env = macos_launchd.detect_environment()
    for k in ("PATH", "HOME", "LANG", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        assert k in env


def test_default_lang_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/Users/x")
    env = macos_launchd.detect_environment()
    assert env["LANG"] == "en_US.UTF-8"
