"""remotask CLI entry point."""
from __future__ import annotations

import os
from pathlib import Path

import typer

from remotask._version import __version__
from remotask.commands import (
    config_cmd,
)
from remotask.commands import (
    daemon as daemon_cmd,
)
from remotask.commands import (
    init as init_cmd,
)
from remotask.commands import (
    install as install_cmd,
)
from remotask.commands import (
    login as login_cmd,
)
from remotask.commands import (
    projects as projects_cmd,
)
from remotask.commands import (
    sessions as sessions_cmd,
)
from remotask.commands import (
    uninstall as uninstall_cmd,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit(code=0)


app = typer.Typer(
    name="remotask",
    help="Remote agent trigger for Claude Code via Telegram.",
    no_args_is_help=True,
    rich_markup_mode=None if os.environ.get("NO_COLOR") else "rich",
    add_completion=False,
)


@app.callback()
def root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable DEBUG-level logging."
    ),
    no_color: bool = typer.Option(
        False, "--no-color", help="Disable colored terminal output."
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Override config.toml path.",
        exists=False,
        dir_okay=False,
    ),
) -> None:
    """Global options for remotask."""
    if no_color:
        os.environ["NO_COLOR"] = "1"


# Register subcommands
app.add_typer(init_cmd.app, name="init")
app.add_typer(install_cmd.app, name="install")
app.add_typer(uninstall_cmd.app, name="uninstall")
app.add_typer(daemon_cmd.app, name="daemon")
app.add_typer(config_cmd.app, name="config")
app.add_typer(login_cmd.app, name="login")
app.add_typer(sessions_cmd.app, name="sessions")
app.add_typer(projects_cmd.app, name="projects")
