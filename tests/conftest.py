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
