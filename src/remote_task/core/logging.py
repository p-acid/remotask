"""Structured logging configuration for remote-task."""
from __future__ import annotations

import contextlib
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

import structlog

_AUDIT_LOGGER_NAME = "remote_task.audit"
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 5


def setup_logging(
    *,
    level: str = "INFO",
    log_dir: Path,
    force_json: bool = False,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    backup_count: int = _DEFAULT_BACKUP_COUNT,
) -> Any:
    """Configure stdlib + structlog.

    - JSON Lines to ``log_dir/remote-task.log`` (always).
    - Audit logger to ``log_dir/audit.log`` (separate handler).
    - Console output: ConsoleRenderer if TTY, JSONRenderer otherwise (or when
      ``force_json`` is True).
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    # --- stdlib root logger ---
    root = logging.getLogger()
    # Clean prior handlers (idempotent setup_logging during tests)
    for h in list(root.handlers):
        root.removeHandler(h)
        with contextlib.suppress(Exception):
            h.close()

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "remote-task.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(file_handler)

    use_json = force_json or not sys.stderr.isatty()
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(stream_handler)

    root.setLevel(level)

    # --- structlog ---
    renderers: list[Any] = [
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if use_json:
        renderers.append(structlog.processors.JSONRenderer())
    else:
        renderers.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=renderers,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level) if isinstance(level, str) else level
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # --- audit logger (always JSON) ---
    audit = logging.getLogger(_AUDIT_LOGGER_NAME)
    for h in list(audit.handlers):
        audit.removeHandler(h)
        with contextlib.suppress(Exception):
            h.close()
    audit_handler = logging.handlers.RotatingFileHandler(
        log_dir / "audit.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    audit_handler.setFormatter(logging.Formatter("%(message)s"))
    audit.addHandler(audit_handler)
    audit.setLevel(logging.INFO)
    audit.propagate = False

    return structlog.get_logger().bind(component="remote_task")


def audit_logger() -> Any:
    """Returns a structlog logger that writes to audit.log."""
    return structlog.wrap_logger(
        logging.getLogger(_AUDIT_LOGGER_NAME),
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
    )
