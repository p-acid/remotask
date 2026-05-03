"""Stand-in for the ``claude-agent-sdk`` worker subprocess.

The real worker entrypoint will drive ``claude-agent-sdk`` to do useful work.
For tests we need something deterministic and fast that exercises every path
the runtime cares about — exit code, stdout protocol for the PR URL, hangs,
crashes — without actually running an LLM.

Modes (selected via the ``FAKE_AGENT_MODE`` env var):

- ``success_with_pr`` (default) — emit a ``PR_URL=<url>`` line to stdout and
  exit 0.
- ``success_no_pr`` — emit nothing of interest and exit 0.
- ``exit_nonzero`` — write an error to stderr and exit 1.
- ``hang`` — sleep forever; used to test the per-session timeout watchdog.
- ``step_then_pr`` (007) — emit one ``STEP <body>`` line, one
  ``EVENT agent.tool_use {...}`` line, then a ``PR_URL=<url>`` line and a
  ``FINAL 1 natural`` line. Exercises the daemon's 007 STEP/EVENT pipeline
  without going through the real claude-agent-sdk.

Other knobs:

- ``FAKE_AGENT_PR_URL`` — the URL to emit in ``success_with_pr`` mode.
  Defaults to a synthetic GitHub URL.
- ``FAKE_AGENT_DELAY_SECONDS`` — seconds to sleep before producing output.
  Defaults to 0.

When invoked as a script (``python -m tests.fakes.fake_agent``) the entrypoint
runs ``main()``. The ``worker_command()`` helper is used by tests/runtime to
build the subprocess argv pointing at this script.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

DEFAULT_PR_URL = "https://github.com/example/repo/pull/42"


def main() -> int:
    mode = os.environ.get("FAKE_AGENT_MODE", "success_with_pr")
    delay = float(os.environ.get("FAKE_AGENT_DELAY_SECONDS", "0") or 0)
    if delay > 0:
        time.sleep(delay)

    if mode == "success_with_pr":
        pr_url = os.environ.get("FAKE_AGENT_PR_URL", DEFAULT_PR_URL)
        # The worker contract: a single line ``PR_URL=<url>`` on stdout.
        sys.stdout.write(f"PR_URL={pr_url}\n")
        sys.stdout.flush()
        return 0
    if mode == "success_no_pr":
        sys.stdout.write("worker finished without opening a PR\n")
        sys.stdout.flush()
        return 0
    if mode == "exit_nonzero":
        msg = os.environ.get("FAKE_AGENT_ERROR", "fake agent failure")
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()
        return 1
    if mode == "hang":
        # Block until the parent SIGKILLs us. Sleep in chunks so SIGTERM can
        # land between iterations and Python can run signal handlers.
        while True:
            time.sleep(0.1)
    if mode == "step_then_pr":
        pr_url = os.environ.get("FAKE_AGENT_PR_URL", DEFAULT_PR_URL)
        # Normalise the body so it always satisfies the daemon STEP regex
        # (`^STEP (.{1,500})$`): collapse newlines, strip whitespace, cap at
        # 500 chars, fall back to the default if empty after sanitisation.
        raw_body = os.environ.get(
            "FAKE_AGENT_STEP_BODY", "Bash: gh pr create --draft"
        )
        step_body = " ".join(raw_body.splitlines()).strip()[:500]
        if not step_body:
            step_body = "Bash: gh pr create --draft"
        sys.stdout.write(f"STEP {step_body}\n")
        sys.stdout.write('EVENT agent.tool_use {"tool":"Bash","iter":1}\n')
        sys.stdout.write(f"PR_URL={pr_url}\n")
        sys.stdout.write("FINAL 1 natural\n")
        sys.stdout.flush()
        return 0
    sys.stderr.write(f"unknown FAKE_AGENT_MODE={mode!r}\n")
    return 2


def worker_command(
    *,
    mode: str = "success_with_pr",
    pr_url: str | None = None,
    delay_seconds: float | None = None,
    error_message: str | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Return ``(argv, env)`` to spawn the fake agent as a subprocess.

    Tests use this to construct the worker command without hard-coding paths.
    Returns argv and env separately so the caller can merge env into its own.
    """
    argv = [sys.executable, "-m", "tests.fakes.fake_agent"]
    env: dict[str, str] = {"FAKE_AGENT_MODE": mode}
    if pr_url is not None:
        env["FAKE_AGENT_PR_URL"] = pr_url
    if delay_seconds is not None:
        env["FAKE_AGENT_DELAY_SECONDS"] = str(delay_seconds)
    if error_message is not None:
        env["FAKE_AGENT_ERROR"] = error_message
    return argv, env


def script_path() -> Path:
    """Absolute path of this file (used to add ``tests/`` to PYTHONPATH if needed)."""
    return Path(__file__).resolve()


if __name__ == "__main__":
    raise SystemExit(main())
