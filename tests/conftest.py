from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class CliResult:
    returncode: int
    stdout: str
    stderr: str


@pytest.fixture(autouse=True)
def _reset_task_source_adapter_cache():
    """Drop the ``get_active_adapter`` singleton between tests (008)."""
    try:
        from remotask.task_sources import reset_cache

        reset_cache()
    except ImportError:
        pass
    yield
    try:
        from remotask.task_sources import reset_cache

        reset_cache()
    except ImportError:
        pass


@pytest.fixture
def tmp_xdg_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate XDG paths to a tmp directory."""
    config_home = tmp_path / "config"
    data_home = tmp_path / "data"
    cache_home = tmp_path / "cache"
    for p in (config_home, data_home, cache_home):
        p.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    return tmp_path


_TESTS_DIR = Path(__file__).parent


@pytest.fixture
def cli_runner(tmp_xdg_env: Path) -> Callable[..., CliResult]:
    """Run remotask via subprocess with isolated XDG env."""

    def run(
        *args: str,
        expect_exit: int | None = 0,
        timeout: float = 30.0,
        extra_env: dict[str, str] | None = None,
    ) -> CliResult:
        cmd = [sys.executable, "-m", "remotask", *args]
        env = os.environ.copy()
        env["XDG_CONFIG_HOME"] = str(tmp_xdg_env / "config")
        env["XDG_DATA_HOME"] = str(tmp_xdg_env / "data")
        env["XDG_CACHE_HOME"] = str(tmp_xdg_env / "cache")
        # Ensure subprocess inherits coverage instrumentation when running
        # under pytest-cov (sitecustomize.py in tests/ activates it).
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{_TESTS_DIR}{os.pathsep}{existing_pp}".rstrip(os.pathsep)
        if extra_env:
            env.update(extra_env)
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        result = CliResult(proc.returncode, proc.stdout, proc.stderr)
        if expect_exit is not None and result.returncode != expect_exit:
            raise AssertionError(
                f"expected exit={expect_exit}, got {result.returncode}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    return run


@pytest.fixture
def mock_gh_issue_view(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Intercept ``subprocess.run(["gh", "issue", "view", ...])`` calls (008 AT4 / AT7).

    Returns a ``set_response(json_payload)`` configurator. Tests call it once
    to install the desired ``gh issue view --json ...`` output, then any
    code path that shells out to ``gh issue view ...`` receives the canned
    response without hitting the real GitHub API.
    """
    state: dict[str, object] = {"payload": None}

    def _set_response(payload: dict) -> None:
        import json as _json

        state["payload"] = _json.dumps(payload)

    real_run = subprocess.run

    def _fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        if (
            isinstance(cmd, (list, tuple))
            and len(cmd) >= 3
            and cmd[0] == "gh"
            and cmd[1] == "issue"
            and cmd[2] == "view"
        ):
            stdout = state["payload"] or "{}"
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=stdout, stderr=""
            )
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    return _set_response
