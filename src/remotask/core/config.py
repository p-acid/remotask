"""TOML-backed configuration with pydantic validation."""
from __future__ import annotations

import os
import re
import tomllib
import typing
from pathlib import Path
from typing import Any, Literal

import tomli_w
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from remotask.core import secrets as rt_secrets

# Telegram bot token format from @BotFather: <bot_id>:<35-char hash>.
# Empty string is also accepted (config-not-yet-populated state).
_BOT_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{30,}$")


class ConfigError(Exception):
    """Base class for configuration errors."""


class UnknownKeyError(ConfigError):
    """Raised when a dotted-path key isn't defined in the schema."""


class ConfigValidationError(ConfigError):
    """Raised when a value fails pydantic validation."""


class InsecurePermissionError(ConfigError):
    """Raised when config.toml has loose permissions."""


# ---------- pydantic models ----------


_GH_OWNER_REPO_RE = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")


class AgentConfig(BaseModel):
    max_concurrent: int = Field(default=1, ge=1, le=10)
    worktree_root: str = "~/Developments/wt"
    default_base_branch: str = "main"
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = (
        "acceptEdits"
    )
    session_timeout_seconds: int = Field(default=1800, ge=60, le=86400)
    # Grace window after a SIGUSR1 (operator stop) before the daemon escalates
    # to the SIGTERM/SIGKILL ladder from 002. Short by default — the demo
    # placeholder only needs to flush one stdout line.
    operator_stop_grace_seconds: int = Field(default=5, ge=1, le=30)
    # 008/T4 — active task source provider. Default "jira" mirrors the
    # V0001 schema's column default and keeps existing test paths
    # untouched; production installs declare this explicitly via config.
    task_source: Literal["jira", "github_issue"] = "jira"
    # 008/T4 — provider-neutral free-text fallback (renamed from
    # default_project_jira_key). Empty/unset disables the fallback.
    # Validator dispatches on task_source: Jira prefix when "jira", or
    # owner/repo shape when "github_issue".
    default_project: str = ""

    @model_validator(mode="after")
    def _validate_default_project(self) -> AgentConfig:
        if not self.default_project:
            return self
        if self.task_source == "jira":
            if not re.fullmatch(r"[A-Z]{2,10}", self.default_project):
                raise ValueError(
                    "agent.default_project must match [A-Z]{2,10} (e.g. ZXTL) "
                    "when agent.task_source = 'jira'"
                )
        elif self.task_source == "github_issue":
            if not _GH_OWNER_REPO_RE.fullmatch(self.default_project):
                raise ValueError(
                    "agent.default_project must match owner/repo (e.g. "
                    "p-acid/remotask) when agent.task_source = 'github_issue'"
                )
        return self


class JiraConfig(BaseModel):
    """Jira-specific config block — populated only when
    ``agent.task_source == "jira"``. The host is read by
    ``JiraAdapter.format_issue_url`` and raises at format time when
    empty (T3); config-load time validation is intentionally lenient so
    GitHub-Issue installs can leave this section blank.
    """

    host: str = ""


class DaemonConfig(BaseModel):
    auth_token: str = Field(default="", min_length=0)
    http_host: str = "127.0.0.1"
    http_port: int = Field(default=6789, ge=1024, le=65535)


class TelegramConfig(BaseModel):
    bot_token: str = ""
    group_chat_id: int = 0
    allowed_user_ids: list[int] = []
    poll_timeout_seconds: int = Field(default=25, ge=1, le=60)
    backoff_max_seconds: int = Field(default=60, ge=1, le=600)

    @field_validator("bot_token")
    @classmethod
    def _validate_bot_token(cls, v: str) -> str:
        if v and not _BOT_TOKEN_RE.fullmatch(v):
            raise ValueError(
                "telegram.bot_token must match '<digits>:<30+ url-safe chars>'"
            )
        return v

    @field_validator("allowed_user_ids")
    @classmethod
    def _validate_user_ids(cls, v: list[int]) -> list[int]:
        for uid in v:
            if uid < 1:
                raise ValueError("telegram.allowed_user_ids entries must be ≥ 1")
        return v


class LoggingConfig(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    rotate_max_mb: int = Field(default=10, ge=1, le=100)
    rotate_backups: int = Field(default=5, ge=1, le=50)


class PathsConfig(BaseModel):
    config_dir: str = ""
    data_dir: str = ""
    cache_dir: str = ""


class ConfigSchema(BaseModel):
    agent: AgentConfig = Field(default_factory=AgentConfig)
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    jira: JiraConfig = Field(default_factory=JiraConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)


# ---------- public API ----------


def default_schema() -> ConfigSchema:
    """Return a fresh schema with an auto-generated daemon auth token."""
    return ConfigSchema(daemon=DaemonConfig(auth_token=rt_secrets.generate_token()))


def load(path: Path, *, strict_permission: bool = False) -> ConfigSchema:
    """Load and validate a config file."""
    if strict_permission:
        ensure_permission_0600(path)
    with path.open("rb") as f:
        raw = tomllib.load(f)
    try:
        return ConfigSchema.model_validate(raw)
    except ValidationError as e:
        raise ConfigValidationError(str(e)) from e


def save(path: Path, schema: ConfigSchema) -> None:
    """Atomically write the config with 0600 permission."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = schema.model_dump()
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = tomli_w.dumps(payload).encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    tmp.replace(path)
    # Ensure 0600 in case umask altered it during replace on some FS.
    path.chmod(0o600)


def ensure_permission_0600(path: Path) -> None:
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise InsecurePermissionError(
            f"config file {path} has mode {oct(mode)}; expected 0o600 or stricter"
        )


# ---------- dotted-path access ----------


def _split(key: str) -> tuple[str, str]:
    if "." not in key:
        raise UnknownKeyError(f"key must be in 'section.field' form: {key!r}")
    section, _, field = key.partition(".")
    return section, field


def _section_model(schema: ConfigSchema, section: str) -> BaseModel:
    if section not in ConfigSchema.model_fields:
        raise UnknownKeyError(f"unknown section {section!r}; known: {list_sections()}")
    obj = getattr(schema, section)
    assert isinstance(obj, BaseModel)
    return obj


def list_sections() -> list[str]:
    return list(ConfigSchema.model_fields.keys())


def list_keys(schema: ConfigSchema) -> list[str]:
    """Return all dotted keys in the schema."""
    keys: list[str] = []
    for section_name in ConfigSchema.model_fields:
        section_cls = type(getattr(schema, section_name))
        for field_name in section_cls.model_fields:
            keys.append(f"{section_name}.{field_name}")
    return sorted(keys)


def get_dotted(schema: ConfigSchema, key: str) -> Any:
    section, field = _split(key)
    section_obj = _section_model(schema, section)
    section_cls = type(section_obj)
    if field not in section_cls.model_fields:
        raise UnknownKeyError(f"unknown key {key!r}")
    return getattr(section_obj, field)


def set_dotted(schema: ConfigSchema, key: str, value: Any) -> None:
    """Set ``key=value`` in-place; raises on validation/unknown key."""
    section, field = _split(key)
    section_obj = _section_model(schema, section)
    section_cls = type(section_obj)
    if field not in section_cls.model_fields:
        raise UnknownKeyError(f"unknown key {key!r}")
    current = section_obj.model_dump()
    current[field] = value
    try:
        new_section = section_cls.model_validate(current)
    except ValidationError as e:
        raise ConfigValidationError(str(e)) from e
    setattr(schema, section, new_section)


def parse_set_value(schema: ConfigSchema, key: str, raw: str) -> Any:
    """Convert a CLI string value into the schema-appropriate Python type."""
    section, field = _split(key)
    section_obj = _section_model(schema, section)
    section_cls = type(section_obj)
    if field not in section_cls.model_fields:
        raise UnknownKeyError(f"unknown key {key!r}")
    annotation = section_cls.model_fields[field].annotation
    if annotation is int or annotation is int | None:
        try:
            return int(raw)
        except ValueError as e:
            raise ConfigValidationError(f"{key} expects an integer, got {raw!r}") from e
    if annotation is bool or annotation is bool | None:
        if raw.lower() in {"true", "1", "yes"}:
            return True
        if raw.lower() in {"false", "0", "no"}:
            return False
        raise ConfigValidationError(f"{key} expects bool, got {raw!r}")
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is list and args == (int,):
        if not raw:
            return []
        try:
            return [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError as e:
            raise ConfigValidationError(
                f"{key} expects comma-separated ints, got {raw!r}"
            ) from e
    return raw
