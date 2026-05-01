from __future__ import annotations

import os
from pathlib import Path

import pytest

from remotask.core import lifecycle


def test_acquire_writes_pid(tmp_path: Path) -> None:
    pid_path = tmp_path / "daemon.pid"
    with lifecycle.Lifecycle(pid_path):
        content = pid_path.read_text().strip()
        assert int(content) == os.getpid()
    assert not pid_path.exists()


def test_second_instance_rejected(tmp_path: Path) -> None:
    pid_path = tmp_path / "daemon.pid"
    with lifecycle.Lifecycle(pid_path), pytest.raises(lifecycle.LockHeldError):
        lifecycle.Lifecycle(pid_path).__enter__()


def test_is_running_after_acquire(tmp_path: Path) -> None:
    pid_path = tmp_path / "daemon.pid"
    with lifecycle.Lifecycle(pid_path):
        running, pid = lifecycle.is_running(pid_path)
        assert running is True
        assert pid == os.getpid()


def test_is_running_when_no_pid_file(tmp_path: Path) -> None:
    pid_path = tmp_path / "daemon.pid"
    running, pid = lifecycle.is_running(pid_path)
    assert running is False
    assert pid is None


def test_is_running_stale_pid_cleanup(tmp_path: Path) -> None:
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("99999999")
    running, pid = lifecycle.is_running(pid_path)
    assert running is False
    # stale file should be cleaned
    assert not pid_path.exists()


def test_is_running_invalid_content_cleanup(tmp_path: Path) -> None:
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("not-a-number")
    running, pid = lifecycle.is_running(pid_path)
    assert running is False
    assert not pid_path.exists()
