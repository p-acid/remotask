"""login — telegram credentials (stub; implemented in 002-telegram-trigger)."""
from __future__ import annotations

import typer

app = typer.Typer(
    name="login",
    help="Register Telegram bot token and group context.",
    invoke_without_command=True,
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def login() -> None:
    """Run the interactive Telegram login flow."""
    typer.echo("login: stub — implemented in 002-telegram-trigger")
    raise typer.Exit(code=0)
