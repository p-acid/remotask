"""projects — Jira ↔ repo mapping CRUD."""
from __future__ import annotations

import typer

from remotask.core import db as rt_db
from remotask.core import paths
from remotask.core import projects as rt_projects

app = typer.Typer(
    name="projects",
    help="Manage Jira project key ↔ git repo mappings.",
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
    """List all registered Jira ↔ repo mappings."""
    _ensure_initialized()
    conn = rt_db.connect(paths.db_path())
    try:
        rows = rt_projects.list_all(conn)
    finally:
        conn.close()

    if not rows:
        typer.echo("no projects yet")
        return

    headers = ("jira_key", "repo_path", "base_branch", "enabled")
    widths = {h: len(h) for h in headers}
    for r in rows:
        widths["jira_key"] = max(widths["jira_key"], len(r["jira_key"]))
        widths["repo_path"] = max(widths["repo_path"], len(r["repo_path"]))
        widths["base_branch"] = max(widths["base_branch"], len(r["base_branch"]))
    fmt = "  ".join(f"{{:<{widths[h]}}}" for h in headers)
    typer.echo(fmt.format(*headers))
    for r in rows:
        typer.echo(fmt.format(r["jira_key"], r["repo_path"], r["base_branch"], r["enabled"]))


@app.command("add")
def add(
    jira_key: str = typer.Argument(..., help="Jira project key (e.g. ZXTL)"),
    repo_path: str = typer.Argument(..., help="Absolute path to the git repository"),
    branch: str = typer.Option("main", "--branch", help="Default base branch"),
) -> None:
    """Register a new Jira ↔ repo mapping."""
    _ensure_initialized()
    try:
        conn = rt_db.connect(paths.db_path())
        try:
            rt_projects.add(conn, jira_key, repo_path, branch)
        finally:
            conn.close()
    except (ValueError, rt_projects.DuplicateKeyError) as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"✓ added {jira_key} → {repo_path} (base: {branch})")


@app.command("remove")
def remove(jira_key: str = typer.Argument(..., help="Jira project key to remove")) -> None:
    """Remove a Jira ↔ repo mapping."""
    _ensure_initialized()
    try:
        conn = rt_db.connect(paths.db_path())
        try:
            rt_projects.remove(conn, jira_key)
        finally:
            conn.close()
    except rt_projects.UnknownKeyError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"✓ removed {jira_key}")
