"""projects — provider-aware project ↔ repo mapping CRUD (008/T4–T5)."""
from __future__ import annotations

import typer

from remotask.core import config as rt_config
from remotask.core import db as rt_db
from remotask.core import paths
from remotask.core import projects as rt_projects


def _active_source() -> str:
    """Read ``agent.task_source`` from config (008/T4 — B9 source policy).

    Returns ``"jira"`` when config can't be loaded so that ``init``-time
    workflows still function. Production CLI usage always loads a valid
    config first.
    """
    try:
        cfg = rt_config.load(paths.config_path())
    except Exception:
        return "jira"
    return cfg.agent.task_source

app = typer.Typer(
    name="projects",
    help="Manage task-source identifier ↔ git repo mappings.",
    no_args_is_help=True,
)


def _ensure_initialized() -> None:
    if not paths.config_path().exists():
        typer.secho(
            "remotask is not initialized. Run `remotask init` first.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=3)


@app.command("list")
def list_() -> None:
    """List all registered task-source ↔ repo mappings."""
    _ensure_initialized()
    conn = rt_db.connect(paths.db_path())
    try:
        rows = rt_projects.list_all(conn)
    finally:
        conn.close()

    if not rows:
        typer.echo("no projects yet")
        return

    headers = ("source", "identifier", "repo_path", "base_branch", "enabled")
    widths = {h: len(h) for h in headers}
    for r in rows:
        widths["source"] = max(widths["source"], len(r["source"]))
        widths["identifier"] = max(widths["identifier"], len(r["source_identifier"]))
        widths["repo_path"] = max(widths["repo_path"], len(r["repo_path"]))
        widths["base_branch"] = max(widths["base_branch"], len(r["base_branch"]))
    fmt = "  ".join(f"{{:<{widths[h]}}}" for h in headers)
    typer.echo(fmt.format(*headers))
    for r in rows:
        typer.echo(
            fmt.format(
                r["source"],
                r["source_identifier"],
                r["repo_path"],
                r["base_branch"],
                r["enabled"],
            )
        )


@app.command("add")
def add(
    identifier: str = typer.Argument(
        ...,
        help="Task-source identifier (Jira: prefix like ZXTL; "
        "GitHub Issue: owner/repo like p-acid/remotask)",
    ),
    repo_path: str = typer.Argument(..., help="Absolute path to the git repository"),
    branch: str = typer.Option("main", "--branch", help="Default base branch"),
) -> None:
    """Register a new task-source ↔ repo mapping.

    The ``source`` is inferred from ``cfg.agent.task_source`` (T4 wires
    that read; T5 hard-codes ``"jira"`` until then).
    """
    _ensure_initialized()
    # 008/T4 — source inferred from cfg.agent.task_source (B9 policy).
    # validate_identifier rejects shape mismatches.
    source = _active_source()
    try:
        conn = rt_db.connect(paths.db_path())
        try:
            rt_projects.add(conn, source=source, identifier=identifier, repo_path=repo_path, base_branch=branch)
        finally:
            conn.close()
    except (ValueError, rt_projects.DuplicateKeyError) as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"✓ added {source}:{identifier} → {repo_path} (base: {branch})")


@app.command("remove")
def remove(
    identifier: str = typer.Argument(..., help="Task-source identifier to remove"),
) -> None:
    """Remove a task-source ↔ repo mapping."""
    _ensure_initialized()
    source = _active_source()
    try:
        conn = rt_db.connect(paths.db_path())
        try:
            rt_projects.remove(conn, source=source, identifier=identifier)
        finally:
            conn.close()
    except rt_projects.UnknownKeyError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"✓ removed {source}:{identifier}")
