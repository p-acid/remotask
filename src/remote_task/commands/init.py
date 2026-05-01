"""init — bootstrap user environment (XDG dirs, config.toml, state.db, token)."""
from __future__ import annotations

import contextlib
from pathlib import Path

import typer

from remote_task.core import config as rt_config
from remote_task.core import db as rt_db
from remote_task.core import logging as rt_logging
from remote_task.core import paths

app = typer.Typer(
    name="init",
    help="Bootstrap config, state DB, logs, and an auth token.",
    invoke_without_command=True,
    no_args_is_help=False,
)


def _is_initialized(config_path: Path, db_path: Path) -> bool:
    return config_path.exists() and db_path.exists()


@app.callback(invoke_without_command=True)
def init(
    force: bool = typer.Option(
        False, "--force", help="Overwrite config (DB user data preserved)."
    ),
) -> None:
    """Bootstrap the remote-task environment."""
    config_path = paths.config_path()
    db_path = paths.db_path()
    log_dir = paths.log_dir()
    data_dir = paths.data_dir()
    config_dir = paths.config_dir()

    already = _is_initialized(config_path, db_path)
    if already and not force:
        typer.echo("Already initialized; no changes.")
        typer.echo(f"  config: {config_path}")
        typer.echo(f"  state:  {db_path}")
        raise typer.Exit(code=0)

    # Track artifacts created in this run so we can roll back on failure.
    created: list[Path] = []

    def _track(p: Path) -> None:
        if not p.exists():
            return
        created.append(p)

    try:
        # Directories
        for d in (config_dir, data_dir, log_dir):
            existed = d.exists()
            d.mkdir(parents=True, exist_ok=True)
            if not existed:
                _track(d)

        # Config (token always regenerated when (re)writing)
        schema = rt_config.default_schema()
        had_config = config_path.exists()
        rt_config.save(config_path, schema)
        if not had_config:
            _track(config_path)

        # Database (apply migrations; user data preserved across re-runs)
        had_db = db_path.exists()
        conn = rt_db.connect(db_path)
        conn.close()
        if not had_db:
            _track(db_path)

        # Audit
        rt_logging.setup_logging(level="INFO", log_dir=log_dir)
        rt_logging.audit_logger().info(
            "init.completed",
            forced=force,
            config_path=str(config_path),
            db_path=str(db_path),
        )

        typer.echo(f"✓ Created {config_path} (mode 0600)")
        typer.echo(f"✓ Created {db_path} (schema v1)")
        typer.echo(f"✓ Log dir {log_dir}")
        typer.echo("✓ Generated daemon.auth_token (saved to config.toml)")
        typer.echo("")
        typer.echo("Next steps:")
        typer.echo("  remote-task config set telegram.bot_token <YOUR_TOKEN>")
        typer.echo("  remote-task install")
    except Exception as exc:
        # Rollback only artifacts we created in this run.
        for p in reversed(created):
            with contextlib.suppress(Exception):
                if p.is_dir():
                    if not any(p.iterdir()):
                        p.rmdir()
                else:
                    p.unlink()
        typer.secho(f"init failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
