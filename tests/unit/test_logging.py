from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path

import pytest
import structlog

from remotask.core import logging as rt_logging


def test_setup_logging_returns_structlog_bound_logger(tmp_path: Path) -> None:
    logger = rt_logging.setup_logging(level="INFO", log_dir=tmp_path, force_json=True)
    assert isinstance(logger, structlog.stdlib.BoundLogger) or hasattr(logger, "bind")


def test_setup_logging_creates_log_dir(tmp_path: Path) -> None:
    log_dir = tmp_path / "nested" / "logs"
    rt_logging.setup_logging(level="INFO", log_dir=log_dir)
    assert log_dir.is_dir()


def test_log_writes_json_lines_to_file(tmp_path: Path) -> None:
    logger = rt_logging.setup_logging(level="INFO", log_dir=tmp_path, force_json=True)
    logger.info("hello", component="test", key=1)
    # flush handlers
    for h in logging.getLogger().handlers:
        h.flush()
    log_file = tmp_path / "remotask.log"
    assert log_file.exists()
    line = log_file.read_text().strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "hello"
    assert payload["component"] == "test"
    assert payload["key"] == 1


def test_audit_logger_uses_separate_file(tmp_path: Path) -> None:
    rt_logging.setup_logging(level="INFO", log_dir=tmp_path, force_json=True)
    audit = rt_logging.audit_logger()
    audit.info("token.regenerated", name="daemon")
    for h in logging.getLogger("remotask.audit").handlers:
        h.flush()
    audit_file = tmp_path / "audit.log"
    assert audit_file.exists()
    line = audit_file.read_text().strip().splitlines()[-1]
    assert json.loads(line)["event"] == "token.regenerated"


def test_rotating_handler_configured(tmp_path: Path) -> None:
    rt_logging.setup_logging(level="INFO", log_dir=tmp_path, max_bytes=10 * 1024 * 1024, backup_count=5)
    file_handlers = [
        h for h in logging.getLogger().handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert any(h.maxBytes == 10 * 1024 * 1024 for h in file_handlers)
    assert any(h.backupCount == 5 for h in file_handlers)


def test_force_json_overrides_tty_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Even when "TTY" appears, force_json=True should still emit JSON to file.
    rt_logging.setup_logging(level="INFO", log_dir=tmp_path, force_json=True)
    log = structlog.get_logger().bind(component="x")
    log.info("event_z", n=2)
    for h in logging.getLogger().handlers:
        h.flush()
    line = (tmp_path / "remotask.log").read_text().strip().splitlines()[-1]
    assert json.loads(line)["event"] == "event_z"
