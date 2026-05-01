from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _spawn(tmp_xdg_env: Path, *args: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(tmp_xdg_env / "config")
    env["XDG_DATA_HOME"] = str(tmp_xdg_env / "data")
    env["XDG_CACHE_HOME"] = str(tmp_xdg_env / "cache")
    return subprocess.Popen(
        [sys.executable, "-m", "remote_task", *args],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _terminate(proc: subprocess.Popen) -> None:
    """Best-effort cleanup that always returns; never leaks file handles."""
    try:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.send_signal(signal.SIGKILL)
                proc.wait(timeout=5)
    finally:
        import contextlib as _ctx
        for stream in (proc.stdout, proc.stderr, proc.stdin):
            if stream is not None:
                with _ctx.suppress(Exception):
                    stream.close()


def _wait_for_pidfile(p: Path, timeout: float = 5.0) -> int:
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        if p.exists():
            try:
                return int(p.read_text().strip())
            except ValueError:
                pass
        time.sleep(0.05)
    raise AssertionError(f"PID file {p} did not appear within {timeout}s")


def _wait_until_no_pidfile(p: Path, timeout: float = 5.0) -> None:
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        if not p.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"PID file {p} still present after {timeout}s")


def test_run_foreground_writes_pid_and_acquires_lock(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    pid_path = tmp_xdg_env / "data" / "remote-task" / "daemon.pid"
    proc = _spawn(tmp_xdg_env, "daemon", "run-foreground")
    try:
        pid = _wait_for_pidfile(pid_path)
        assert pid == proc.pid
    finally:
        _terminate(proc)
    _wait_until_no_pidfile(pid_path)


def test_second_instance_rejected(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    pid_path = tmp_xdg_env / "data" / "remote-task" / "daemon.pid"
    proc = _spawn(tmp_xdg_env, "daemon", "run-foreground")
    try:
        _wait_for_pidfile(pid_path)
        result = cli_runner("daemon", "run-foreground", expect_exit=None, timeout=5)
        assert result.returncode == 4, result.stderr
    finally:
        _terminate(proc)


def test_status_running(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    pid_path = tmp_xdg_env / "data" / "remote-task" / "daemon.pid"
    proc = _spawn(tmp_xdg_env, "daemon", "run-foreground")
    try:
        _wait_for_pidfile(pid_path)
        result = cli_runner("daemon", "status")
        assert result.returncode == 0
        out = result.stdout.lower()
        assert "running" in out
        assert str(proc.pid) in result.stdout
        assert "uptime" in out
    finally:
        _terminate(proc)


def test_status_not_running(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    result = cli_runner("daemon", "status", expect_exit=None)
    assert result.returncode == 1
    assert "not running" in result.stdout.lower()


def test_stop_graceful(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    pid_path = tmp_xdg_env / "data" / "remote-task" / "daemon.pid"
    proc = _spawn(tmp_xdg_env, "daemon", "run-foreground")
    try:
        _wait_for_pidfile(pid_path)
        result = cli_runner("daemon", "stop")
        assert result.returncode == 0
        proc.wait(timeout=5)
    finally:
        _terminate(proc)
    _wait_until_no_pidfile(pid_path)


def test_stop_under_5s(cli_runner, tmp_xdg_env: Path) -> None:
    """SC-004: stop completes within 5 seconds."""
    cli_runner("init")
    pid_path = tmp_xdg_env / "data" / "remote-task" / "daemon.pid"
    proc = _spawn(tmp_xdg_env, "daemon", "run-foreground")
    try:
        _wait_for_pidfile(pid_path)
        start = time.perf_counter()
        cli_runner("daemon", "stop")
        elapsed = time.perf_counter() - start
        proc.wait(timeout=5)
        assert elapsed < 5.0, f"stop took {elapsed:.3f}s"
    finally:
        _terminate(proc)


def test_stale_pid_cleanup_via_status(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    pid_path = tmp_xdg_env / "data" / "remote-task" / "daemon.pid"
    pid_path.write_text("99999999")
    result = cli_runner("daemon", "status", expect_exit=None)
    assert result.returncode == 1
    assert "not running" in result.stdout.lower()
    assert not pid_path.exists()


def test_start_background_spawn(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    pid_path = tmp_xdg_env / "data" / "remote-task" / "daemon.pid"
    result = cli_runner("daemon", "start", timeout=10)
    assert result.returncode == 0
    pid = _wait_for_pidfile(pid_path)
    assert pid > 0

    # Verify status sees the running process.
    status = cli_runner("daemon", "status")
    assert status.returncode == 0

    # Cleanup.
    cli_runner("daemon", "stop")
    _wait_until_no_pidfile(pid_path)
