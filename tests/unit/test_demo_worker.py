"""Unit tests for ``remotask.agent.demo_worker``.

Pins the placeholder workload's behaviour: env-var configuration, default
values, the ``PROGRESS`` / ``FINAL`` line shapes, and the cooperative
``SIGUSR1`` handler.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from remotask.agent import demo_worker

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_worker(env_overrides: dict[str, str], timeout: float = 10.0) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env.update(env_overrides)
    proc = subprocess.run(
        [sys.executable, "-m", "remotask.agent.demo_worker"],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestEnvDefaults:
    def test_iterations_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("REMOTASK_DEMO_ITERATIONS", raising=False)
        assert demo_worker._read_iterations() == demo_worker.DEFAULT_ITERATIONS

    def test_iterations_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REMOTASK_DEMO_ITERATIONS", "12")
        assert demo_worker._read_iterations() == 12

    def test_iterations_clamps_floor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REMOTASK_DEMO_ITERATIONS", "0")
        assert demo_worker._read_iterations() == 1

    def test_iterations_invalid_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REMOTASK_DEMO_ITERATIONS", "not-a-number")
        assert demo_worker._read_iterations() == demo_worker.DEFAULT_ITERATIONS

    def test_interval_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("REMOTASK_DEMO_INTERVAL_SECONDS", raising=False)
        assert demo_worker._read_interval_seconds() == demo_worker.DEFAULT_INTERVAL_SECONDS

    def test_interval_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REMOTASK_DEMO_INTERVAL_SECONDS", "0.05")
        assert demo_worker._read_interval_seconds() == pytest.approx(0.05)


class TestIso8601Helper:
    def test_format_shape(self) -> None:
        ts = demo_worker._iso8601_utc()
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts)


class TestSubprocessNaturalCompletion:
    """Exercise the worker as a real subprocess to lock in stdout shape."""

    def test_two_iteration_run_emits_progress_then_natural_final(self) -> None:
        rc, stdout, stderr = _run_worker(
            {
                "REMOTASK_DEMO_ITERATIONS": "2",
                "REMOTASK_DEMO_INTERVAL_SECONDS": "0.05",
            },
            timeout=5.0,
        )
        assert rc == 0, f"stderr: {stderr}"
        lines = [ln for ln in stdout.splitlines() if ln.strip()]
        # PROGRESS 1/2, PROGRESS 2/2, FINAL 2 natural — in that order.
        assert len(lines) == 3
        assert re.fullmatch(r"PROGRESS 1/2 \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", lines[0])
        assert re.fullmatch(r"PROGRESS 2/2 \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", lines[1])
        assert lines[2] == "FINAL 2 natural"


class TestSubprocessSigusr1Handler:
    def test_sigusr1_triggers_operator_stop_final(self) -> None:
        # Run with a long interval, send SIGUSR1 mid-sleep, expect operator_stop FINAL.
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
        env["REMOTASK_DEMO_ITERATIONS"] = "10"
        env["REMOTASK_DEMO_INTERVAL_SECONDS"] = "5.0"  # plenty of headroom

        proc = subprocess.Popen(
            [sys.executable, "-m", "remotask.agent.demo_worker"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            # Wait until at least the first PROGRESS line shows up so we know
            # the handler is installed and the loop is running.
            deadline = time.time() + 5.0
            while time.time() < deadline:
                # Peek at non-blocking output by polling — easiest is: small sleep
                # then send the signal. We rely on subprocess line buffering.
                time.sleep(0.2)
                if proc.poll() is not None:
                    break
                # Send the signal once; the worker should wake within ≤ 0.5s.
                import signal

                proc.send_signal(signal.SIGUSR1)
                break

            stdout, stderr = proc.communicate(timeout=5.0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate(timeout=2.0)

        assert proc.returncode == 0, f"stderr: {stderr}"
        lines = [ln for ln in stdout.splitlines() if ln.strip()]
        # At least one PROGRESS line, then a FINAL ... operator_stop line.
        progress_lines = [ln for ln in lines if ln.startswith("PROGRESS ")]
        final_lines = [ln for ln in lines if ln.startswith("FINAL ")]
        assert len(progress_lines) >= 1, lines
        assert len(final_lines) == 1, lines
        assert final_lines[0].endswith(" operator_stop"), lines


class TestSubprocessIgnoreSigusr1:
    """The test-only ``REMOTASK_DEMO_IGNORE_SIGUSR1`` path used by US3 forced-kill tests."""

    def test_ignored_signal_does_not_stop_worker(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
        env["REMOTASK_DEMO_ITERATIONS"] = "2"
        env["REMOTASK_DEMO_INTERVAL_SECONDS"] = "0.1"
        env["REMOTASK_DEMO_IGNORE_SIGUSR1"] = "1"

        proc = subprocess.Popen(
            [sys.executable, "-m", "remotask.agent.demo_worker"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Send SIGUSR1 right away; the worker should shrug it off and run to
        # natural completion.
        time.sleep(0.05)
        import signal

        proc.send_signal(signal.SIGUSR1)
        stdout, stderr = proc.communicate(timeout=5.0)

        assert proc.returncode == 0, f"stderr: {stderr}"
        lines = [ln for ln in stdout.splitlines() if ln.strip()]
        assert lines[-1] == "FINAL 2 natural"
