"""``remotask telegram`` subcommand group.

CLI front for the listener: ``start``, ``stop``, ``status``. The CLI is
deliberately thin — every command writes a tiny JSON file (``listener.cmd``),
signals SIGUSR1 to the daemon, and polls ``listener.state`` for the result.
The daemon side is in ``remotask.daemon.runtime`` (SIGUSR1 handler) and
``remotask.daemon.listener_cmd`` (file shape).

Exit codes follow ``contracts/cli-commands.md``:

- 0  — success
- 3  — daemon not running
- 4  — daemon did not flip the listener.state in time
- 5  — config prevents start (precondition failed)
"""
from __future__ import annotations

import json
import os
import signal
import time
from datetime import UTC, datetime

import typer

from remotask.core import config as rt_config
from remotask.core import lifecycle, paths
from remotask.daemon import listener_cmd, listener_state
from remotask.daemon.runtime import (
    ListenerPreconditionError,
    validate_listener_preconditions,
)

app = typer.Typer(
    name="telegram",
    help="Control the Telegram listener subsystem of the running daemon.",
    no_args_is_help=True,
)

_POLL_DEADLINE = 5.0
_POLL_INTERVAL = 0.05
_STALE_AFTER_SECONDS = 30.0


def _daemon_pid() -> int | None:
    running, pid = lifecycle.is_running(paths.pid_path())
    return pid if running else None


def _next_seq() -> int:
    """Next monotonic seq based on whatever cmd is currently on disk."""
    existing = listener_cmd.read()
    return listener_cmd.next_seq(existing.seq) if existing is not None else 1


def _send_command(command: str) -> int:
    """Write listener.cmd, signal the daemon, return the seq used."""
    seq = _next_seq()
    listener_cmd.write(listener_cmd.ListenerCmd(seq=seq, command=command))  # type: ignore[arg-type]
    pid = _daemon_pid()
    if pid is None:
        typer.secho(
            "daemon is not running. Start it with `remotask daemon start`.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=3)
    try:
        os.kill(pid, signal.SIGUSR1)
    except ProcessLookupError as e:
        typer.secho(
            f"daemon process {pid} not responding", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=3) from e
    return seq


def _wait_for_state(predicate, *, timeout: float = _POLL_DEADLINE) -> bool:
    """Poll ``listener.state`` until ``predicate(state)`` is True or timeout."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        st = listener_state.read()
        if st is not None and predicate(st):
            return True
        time.sleep(_POLL_INTERVAL)
    return False


@app.command("start")
def start() -> None:
    """Tell the running daemon to begin polling Telegram."""
    # Pre-check: load config, verify preconditions. Done CLI-side too so the
    # operator gets a precise error without having to grep daemon.log.
    try:
        cfg = rt_config.load(paths.config_path())
        validate_listener_preconditions(cfg, config_path=paths.config_path())
    except ListenerPreconditionError as e:
        typer.secho(
            f"cannot start listener: {e.field}: {e.reason}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=5) from e
    except Exception as e:
        typer.secho(f"cannot read config: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=5) from e

    _send_command("start")
    flipped = _wait_for_state(lambda s: s.running)
    if not flipped:
        typer.secho(
            "daemon did not start the listener within the timeout",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=4)

    st = listener_state.read()
    whitelist_size = st.whitelist_size if st is not None else 0
    last_poll = _humanize_relative(st.last_poll_ok_at) if st is not None else "just now"
    typer.echo(f"listener started (whitelist={whitelist_size}, last_poll={last_poll})")


@app.command("stop")
def stop() -> None:
    """Tell the running daemon to stop accepting new triggers."""
    _send_command("stop")
    flipped = _wait_for_state(lambda s: not s.running)
    if not flipped:
        typer.secho(
            "daemon did not stop the listener within the timeout",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=4)
    st = listener_state.read()
    active = st.active_sessions if st is not None else 0
    typer.echo(f"listener stopped (active sessions left running: {active})")


@app.command("status")
def status(json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON.")) -> None:
    """Show listener state."""
    st = listener_state.read()
    if st is None:
        typer.secho(
            "listener state unavailable (daemon never started?)",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    if json_out:
        typer.echo(st.to_json())
        return

    now = time.time()
    stale = (now - max(st.last_poll_ok_at, st.started_at)) > _STALE_AFTER_SECONDS
    stale_marker = "  (stale)" if stale else ""
    typer.echo(f"listener:        {'running' if st.running else 'stopped'}")
    typer.echo(f"since:           {_format_iso(st.started_at)}")
    typer.echo(f"last poll:       {_format_iso(st.last_poll_ok_at)}{stale_marker}")
    typer.echo(f"degraded:        {'yes' if st.degraded else 'no'}")
    typer.echo(f"active sessions: {st.active_sessions}")
    typer.echo(f"whitelist size:  {st.whitelist_size}")


# ---- formatting helpers ---------------------------------------------------


def _format_iso(epoch: float) -> str:
    if not epoch:
        return "(never)"
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat()


def _humanize_relative(epoch: float) -> str:
    if not epoch:
        return "just now"
    age = max(0, int(time.time() - epoch))
    if age < 5:
        return "just now"
    if age < 60:
        return f"{age}s ago"
    return f"{age // 60}m ago"


# ---- noqa: F401 keeps json importable for future structured-error use ----


def _ensure_json_importable() -> None:  # pragma: no cover
    json.dumps({"_": True})
