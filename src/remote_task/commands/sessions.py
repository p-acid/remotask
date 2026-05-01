"""sessions — list/cancel (stub; implemented in 003-agent-execution)."""
from __future__ import annotations

import typer

app = typer.Typer(
    name="sessions",
    help="Inspect and cancel running sessions.",
    no_args_is_help=True,
)


@app.command("list")
def list_() -> None:
    """List sessions (currently always empty in 001-cli-bootstrap)."""
    typer.echo("no sessions yet")


@app.command("cancel")
def cancel(issue_key: str = typer.Argument(...)) -> None:
    """Cancel an active session by issue key."""
    typer.echo("sessions cancel: stub — implemented in 003-agent-execution")
