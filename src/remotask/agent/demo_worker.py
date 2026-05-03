"""Placeholder agent worker for the 003 e2e-demo feature.

Spawned by the daemon as a child subprocess in the per-session git worktree.
Writes the small line protocol from
``CHANGELOG.md#v003`` (feature summary) to stdout:

* ``PROGRESS i/N <iso8601>`` at the start of each iteration
* ``FINAL <i> natural`` after all iterations complete
* ``FINAL <i> operator_stop`` when interrupted by SIGUSR1

Configuration from environment variables:

* ``REMOTASK_DEMO_ITERATIONS`` (default 5)
* ``REMOTASK_DEMO_INTERVAL_SECONDS`` (default 30.0)
* ``REMOTASK_DEMO_IGNORE_SIGUSR1`` — test-only knob; when truthy, the worker
  installs SIG_IGN for SIGUSR1 instead of the cooperative handler. Used by
  ``tests/integration/test_operator_stop_forced.py`` to exercise the daemon's
  forced-kill escalation path.

This module is the production worker entry point referenced by
``daemon.worker._default_worker_argv()``. It is also runnable directly as
``python -m remotask.agent.demo_worker``.
"""
from __future__ import annotations

import os
import signal
import sys
import time
from datetime import UTC, datetime

# Defaults are intentionally module-level constants so tests can monkeypatch
# them easily if needed (env vars are the recommended override surface).
DEFAULT_ITERATIONS = 5
DEFAULT_INTERVAL_SECONDS = 30.0
# Granularity for the inter-iteration sleep — keeps the worker responsive to
# SIGUSR1 mid-sleep without burning CPU. ≤ 0.5s slices = ≤ 0.5s lag from a
# stop request to its observation.
_SLEEP_SLICE_SECONDS = 0.5

_stop_requested = False


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _read_iterations() -> int:
    raw = os.environ.get("REMOTASK_DEMO_ITERATIONS")
    if raw is None or raw.strip() == "":
        return DEFAULT_ITERATIONS
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_ITERATIONS
    return max(1, min(n, 1_000_000))


def _read_interval_seconds() -> float:
    raw = os.environ.get("REMOTASK_DEMO_INTERVAL_SECONDS")
    if raw is None or raw.strip() == "":
        return DEFAULT_INTERVAL_SECONDS
    try:
        v = float(raw)
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS
    return max(0.05, min(v, 600.0))


def _iso8601_utc() -> str:
    """Return the current UTC time as a compact ISO-8601 string."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sigusr1_handler(signum: int, frame: object) -> None:  # noqa: ARG001
    """Cooperative stop handler — set the flag and return promptly.

    No I/O, no allocation that might re-enter — Python's signal handler runs on
    the main thread between bytecode instructions, but anything fancy invites
    re-entrancy bugs.
    """
    global _stop_requested
    _stop_requested = True


def _install_signal_handler() -> None:
    if _truthy_env("REMOTASK_DEMO_IGNORE_SIGUSR1"):
        # Test-only path. Force the daemon to fall back to its forced-kill
        # ladder (US3 escalation).
        signal.signal(signal.SIGUSR1, signal.SIG_IGN)
        return
    signal.signal(signal.SIGUSR1, _sigusr1_handler)


def _emit(line: str) -> None:
    """Write a single protocol line to stdout and flush immediately.

    Flush after every line so the daemon's streaming parser sees the line as
    soon as we produce it — otherwise stdout buffering would batch progress
    posts in a way the operator would notice.
    """
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _sliced_sleep(total_seconds: float) -> bool:
    """Sleep up to ``total_seconds`` in ≤ 0.5s slices; abort early on stop.

    Returns True when the full duration elapsed, False when stop was observed
    mid-sleep.
    """
    remaining = total_seconds
    while remaining > 0:
        if _stop_requested:
            return False
        slice_s = min(_SLEEP_SLICE_SECONDS, remaining)
        time.sleep(slice_s)
        remaining -= slice_s
    return True


def main() -> int:
    _install_signal_handler()
    iterations = _read_iterations()
    interval = _read_interval_seconds()

    for i in range(1, iterations + 1):
        if _stop_requested:
            _emit(f"FINAL {i - 1 if i > 1 else 0} operator_stop")
            return 0
        _emit(f"PROGRESS {i}/{iterations} {_iso8601_utc()}")
        if i < iterations:
            completed = _sliced_sleep(interval)
            if not completed:
                _emit(f"FINAL {i} operator_stop")
                return 0

    _emit(f"FINAL {iterations} natural")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
