"""uninstall — unregister launchd agent."""
from __future__ import annotations

import shutil

import typer

from remote_task.core import logging as rt_logging
from remote_task.core import paths
from remote_task.platform import macos_launchd

app = typer.Typer(
    name="uninstall",
    help="Unregister the launchd agent and optionally remove user data.",
    invoke_without_command=True,
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def uninstall(
    label: str = typer.Option(macos_launchd.DEFAULT_LABEL, "--label"),
    purge: bool = typer.Option(False, "--purge", help="Remove user data (config, db, logs)."),
) -> None:
    """Unload, delete plist, optionally purge user data."""
    macos_launchd.validate_label(label)
    plist = macos_launchd.plist_path(label)

    if plist.exists():
        macos_launchd.launchctl_unload(plist)
        plist.unlink()
        typer.echo(f"✓ launchctl unload + removed {plist}")
    else:
        typer.echo(f"(plist not found: {plist})")

    rt_logging.setup_logging(level="INFO", log_dir=paths.log_dir())
    rt_logging.audit_logger().info(
        "launchd.uninstall",
        label=label,
        purge=purge,
    )

    if purge:
        for d in (paths.config_dir(), paths.data_dir(), paths.cache_dir()):
            if d.exists():
                shutil.rmtree(d)
                typer.echo(f"✓ removed {d}")
    else:
        typer.echo("✓ User data preserved (config.toml, state.db, logs/)")
