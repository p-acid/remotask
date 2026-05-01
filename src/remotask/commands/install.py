"""install — register macOS launchd agent."""
from __future__ import annotations

import shutil
import sys
import time

import typer

from remotask.core import logging as rt_logging
from remotask.core import paths
from remotask.platform import macos_launchd

app = typer.Typer(
    name="install",
    help="Register the remotask daemon as a macOS launchd Launch Agent.",
    invoke_without_command=True,
    no_args_is_help=False,
)


def _ensure_initialized() -> None:
    if not paths.config_path().exists():
        typer.secho(
            "remotask is not initialized. Run `remotask init` first.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=3)


def _resolve_remotask_path() -> str:
    found = shutil.which("remotask")
    if found:
        return found
    return f"{sys.executable} -m remotask"


def _wait_for_daemon(timeout: float = 5.0) -> None:
    """Poll for the daemon to come up after launchctl load."""
    import os as _os
    if _os.environ.get("REMOTE_TASK_SKIP_HEALTH_POLL"):
        return
    from remotask.core import lifecycle  # local import to avoid cycle
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        running, _ = lifecycle.is_running(paths.pid_path())
        if running:
            return
        time.sleep(0.1)


@app.callback(invoke_without_command=True)
def install(
    label: str = typer.Option(macos_launchd.DEFAULT_LABEL, "--label"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Generate plist, load via launchctl, wait for daemon health."""
    _ensure_initialized()
    macos_launchd.validate_label(label)

    plist = macos_launchd.plist_path(label)
    plist.parent.mkdir(parents=True, exist_ok=True)

    rendered = macos_launchd.render_plist(
        label=label,
        remotask_path=_resolve_remotask_path(),
        env=macos_launchd.detect_environment(),
    )

    is_replacing = plist.exists()
    if is_replacing:
        if not force:
            typer.echo(f"plist already exists: {plist}")
            typer.echo("Use --force to replace.")
            raise typer.Exit(code=1)
        macos_launchd.launchctl_unload(plist)

    plist.write_text(rendered, encoding="utf-8")
    macos_launchd.launchctl_load(plist)
    _wait_for_daemon()

    rt_logging.setup_logging(level="INFO", log_dir=paths.log_dir())
    rt_logging.audit_logger().info(
        "launchd.install",
        label=label,
        plist=str(plist),
        replaced=is_replacing,
    )

    typer.echo(f"✓ Wrote {plist}")
    typer.echo("✓ launchctl load (waiting for daemon health…)")
    typer.echo("✓ daemon load requested")
