"""SC-008: data integrity under concurrent init / daemon spawn."""
from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

CONCURRENCY_REPS = int(os.environ.get("STRESS_REPS", "100"))


def _spawn_init(env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "remotask", "init"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.integration
def test_init_concurrent_repeats(tmp_xdg_env: Path) -> None:
    """Repeated concurrent init runs must not corrupt config or DB."""
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(tmp_xdg_env / "config")
    env["XDG_DATA_HOME"] = str(tmp_xdg_env / "data")
    env["XDG_CACHE_HOME"] = str(tmp_xdg_env / "cache")

    success = 0
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_spawn_init, env) for _ in range(CONCURRENCY_REPS)]
        for fut in as_completed(futures):
            r = fut.result()
            if r.returncode == 0:
                success += 1
            else:
                failures.append(r.stderr or r.stdout)

    config_path = tmp_xdg_env / "config" / "remotask" / "config.toml"
    db_path = tmp_xdg_env / "data" / "remotask" / "state.db"
    assert config_path.exists()
    assert db_path.exists()
    # config still parseable
    cfg = tomllib.loads(config_path.read_text())
    assert isinstance(cfg["daemon"]["auth_token"], str)
    assert len(cfg["daemon"]["auth_token"]) >= 32
    # config remains 0600
    assert (config_path.stat().st_mode & 0o777) == 0o600
    # at least one run succeeded; failures (if any) should be benign
    assert success >= 1
    assert success + len(failures) == CONCURRENCY_REPS


@pytest.mark.integration
def test_daemon_concurrent_spawn(tmp_xdg_env: Path, cli_runner) -> None:
    """Many concurrent `daemon run-foreground` attempts → exactly one succeeds."""
    cli_runner("init")
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(tmp_xdg_env / "config")
    env["XDG_DATA_HOME"] = str(tmp_xdg_env / "data")
    env["XDG_CACHE_HOME"] = str(tmp_xdg_env / "cache")

    procs: list[subprocess.Popen] = []
    try:
        for _ in range(8):
            procs.append(
                subprocess.Popen(
                    [sys.executable, "-m", "remotask", "daemon", "run-foreground"],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        # Give them a moment to race for the lock. 5s is generous: the slowest
        # losers spend most of the budget on Python import setup before they
        # ever attempt the lock (the daemon stack pulls in httpx, structlog,
        # claude-agent-sdk, etc. on cold start). A 1s budget was prone to
        # false-positive "alive" counts on a busy laptop.
        deadline = time.perf_counter() + 5.0
        while time.perf_counter() < deadline:
            alive = [p for p in procs if p.poll() is None]
            if len(alive) <= 1:
                break
            time.sleep(0.1)

        alive = [p for p in procs if p.poll() is None]
        assert len(alive) == 1, (
            f"expected exactly one survivor; got {len(alive)} alive, "
            f"{len(procs) - len(alive)} exited"
        )
        # Survivor must own the PID file.
        pid_path = tmp_xdg_env / "data" / "remotask" / "daemon.pid"
        assert pid_path.exists()
        assert int(pid_path.read_text().strip()) == alive[0].pid
    finally:
        for p in procs:
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.send_signal(signal.SIGKILL)
                p.wait(timeout=5)
            for stream in (p.stdout, p.stderr, p.stdin):
                if stream is not None:
                    with contextlib.suppress(Exception):
                        stream.close()
