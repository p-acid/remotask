"""config — get / set / list / regenerate-token."""
from __future__ import annotations

import typer

from remote_task.core import config as rt_config
from remote_task.core import logging as rt_logging
from remote_task.core import paths
from remote_task.core import secrets as rt_secrets

app = typer.Typer(
    name="config",
    help="Inspect and modify remote-task configuration.",
    no_args_is_help=True,
)


def _ensure_initialized() -> None:
    cp = paths.config_path()
    if not cp.exists():
        typer.secho(
            "remote-task is not initialized. Run `remote-task init` first.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=3)


def _format_value(value: object) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(str(v) for v in value) + "]"
    return str(value)


@app.command("get")
def get(
    key: str = typer.Argument(..., help="Dotted-path key (e.g. agent.max_concurrent)"),
    reveal: bool = typer.Option(False, "--reveal", help="Show secrets in plaintext."),
) -> None:
    """Get a config value (secrets masked unless --reveal)."""
    _ensure_initialized()
    try:
        schema = rt_config.load(paths.config_path())
        value = rt_config.get_dotted(schema, key)
    except rt_config.UnknownKeyError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        typer.echo("Available keys: " + ", ".join(rt_config.list_keys(rt_config.default_schema())), err=True)
        raise typer.Exit(code=1) from e
    if rt_secrets.is_secret_key(key) and not reveal:
        typer.echo(rt_secrets.mask(str(value) if value else None))
    else:
        typer.echo(_format_value(value))


@app.command("set")
def set_(
    key: str = typer.Argument(..., help="Dotted-path key"),
    value: str = typer.Argument(..., help="New value"),
) -> None:
    """Set a config value."""
    _ensure_initialized()
    config_path = paths.config_path()
    try:
        schema = rt_config.load(config_path)
        typed_value = rt_config.parse_set_value(schema, key, value)
        rt_config.set_dotted(schema, key, typed_value)
        rt_config.save(config_path, schema)
    except rt_config.UnknownKeyError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        typer.echo("Available keys: " + ", ".join(rt_config.list_keys(rt_config.default_schema())), err=True)
        raise typer.Exit(code=1) from e
    except rt_config.ConfigValidationError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e
    display = (
        rt_secrets.mask(str(typed_value)) if rt_secrets.is_secret_key(key) else _format_value(typed_value)
    )
    typer.echo(f"✓ {key} = {display}")


@app.command("list")
def list_(reveal: bool = typer.Option(False, "--reveal", help="Show secrets in plaintext.")) -> None:
    """List all config keys."""
    _ensure_initialized()
    schema = rt_config.load(paths.config_path())
    keys = rt_config.list_keys(schema)
    width = max(len(k) for k in keys)
    for key in keys:
        value = rt_config.get_dotted(schema, key)
        if rt_secrets.is_secret_key(key) and not reveal:
            display = rt_secrets.mask(str(value) if value else None)
        else:
            display = _format_value(value)
        typer.echo(f"{key.ljust(width)}  {display}")


@app.command("regenerate-token")
def regenerate_token(
    name: str = typer.Option("daemon", "--name", help="Token name to regenerate."),
) -> None:
    """Regenerate the named auth token."""
    _ensure_initialized()
    config_path = paths.config_path()
    schema = rt_config.load(config_path)
    key = f"{name}.auth_token"
    if not rt_secrets.is_secret_key(key):
        typer.secho(f"unknown token name: {name}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    new_token = rt_secrets.generate_token()
    rt_config.set_dotted(schema, key, new_token)
    rt_config.save(config_path, schema)

    rt_logging.setup_logging(level="INFO", log_dir=paths.log_dir())
    rt_logging.audit_logger().info("token.regenerated", name=name)

    typer.echo(f"✓ {key} regenerated")
