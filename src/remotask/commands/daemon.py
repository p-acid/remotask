"""daemon — lifecycle commands."""
from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import typer

from remotask.core import lifecycle, paths
from remotask.daemon import stub_runtime

app = typer.Typer(
    name="daemon",
    help="Manage the remotask daemon process (run-foreground/start/stop/status/logs).",
    no_args_is_help=True,
)

_STOP_TIMEOUT_SEC = 5.0
_POLL_INTERVAL = 0.05


@app.command("run-foreground")
def run_foreground() -> None:
    """Run the daemon in the foreground (used by launchd)."""
    try:
        stub_runtime.run()
    except lifecycle.LockHeldError as e:
        running, pid = lifecycle.is_running(paths.pid_path())
        msg = f"daemon already running (pid {pid})" if running else str(e)
        typer.secho(msg, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=4) from e


@app.command("start")
def start() -> None:
    """Spawn the daemon in the background."""
    running, pid = lifecycle.is_running(paths.pid_path())
    if running:
        typer.secho(f"daemon already running (pid {pid})", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=4)

    log_dir = paths.log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    out_path = log_dir / "daemon.stdout.log"
    err_path = log_dir / "daemon.stderr.log"

    with out_path.open("ab") as out_fd, err_path.open("ab") as err_fd:
        subprocess.Popen(
            [sys.executable, "-m", "remotask", "daemon", "run-foreground"],
            stdout=out_fd,
            stderr=err_fd,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=os.environ.copy(),
        )

    # Wait briefly for the child to write its PID file.
    deadline = time.perf_counter() + 5.0
    while time.perf_counter() < deadline:
        running, pid = lifecycle.is_running(paths.pid_path())
        if running:
            typer.echo(f"✓ daemon started (pid {pid})")
            return
        time.sleep(_POLL_INTERVAL)
    typer.secho("daemon spawn timed out", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


@app.command("stop")
def stop() -> None:
    """Send SIGTERM to the running daemon (escalate to SIGKILL after 5s)."""
    running, pid = lifecycle.is_running(paths.pid_path())
    if not running or pid is None:
        typer.echo("daemon is not running")
        raise typer.Exit(code=1)

    start_t = time.perf_counter()
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        typer.echo("daemon already exited")
        raise typer.Exit(code=0) from None

    deadline = start_t + _STOP_TIMEOUT_SEC
    while time.perf_counter() < deadline:
        running, _ = lifecycle.is_running(paths.pid_path())
        if not running:
            elapsed = time.perf_counter() - start_t
            typer.echo(f"✓ daemon stopped (took {elapsed:.2f}s)")
            return
        time.sleep(_POLL_INTERVAL)

    # Escalate.
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
    deadline2 = time.perf_counter() + 2.0
    while time.perf_counter() < deadline2:
        running, _ = lifecycle.is_running(paths.pid_path())
        if not running:
            typer.secho("⚠ daemon force-killed (SIGKILL)", fg=typer.colors.YELLOW)
            return
        time.sleep(_POLL_INTERVAL)
    typer.secho("daemon failed to stop", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=6)


@app.command("status")
def status() -> None:
    """Report daemon liveness."""
    pid_path = paths.pid_path()
    running, pid = lifecycle.is_running(pid_path)
    if not running or pid is None:
        typer.echo("status: not running")
        raise typer.Exit(code=1)
    log_path = paths.log_dir() / "remotask.log"
    uptime = _format_uptime(_pid_uptime_seconds(pid_path))
    typer.echo("status: running")
    typer.echo(f"pid: {pid}")
    typer.echo(f"uptime: {uptime}")
    typer.echo(f"log: {log_path}")


@app.command("logs")
def logs(follow: bool = typer.Option(False, "-f", "--follow")) -> None:
    """Tail daemon logs."""
    log_path = paths.log_dir() / "remotask.log"
    if not log_path.exists():
        typer.echo("(no logs yet)")
        return
    if follow:
        subprocess.run(["tail", "-f", str(log_path)], check=False)  # noqa: S603, S607
    else:
        subprocess.run(["tail", "-n", "200", str(log_path)], check=False)  # noqa: S603, S607


# --- helpers ----------------------------------------------------------------


def _pid_uptime_seconds(pid_path: Path) -> float:
    try:
        return max(0.0, time.time() - pid_path.stat().st_mtime)
    except FileNotFoundError:
        return 0.0


def _format_uptime(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h {m}m {sec}s"
