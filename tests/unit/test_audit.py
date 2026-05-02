"""Unit tests for ``remotask.daemon.audit``."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from remotask.core import db as core_db
from remotask.core import logging as rt_logging
from remotask.daemon import audit


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    """An in-memory-ish DB with V0001 applied and one parent session row."""
    conn = core_db.connect(tmp_path / "state.db")
    conn.execute(
        "INSERT INTO sessions(id, issue_key, status, enqueued_at) VALUES (?, ?, ?, ?)",
        ("sess-1", "ZXTL-1", "enqueued", int(time.time())),
    )
    conn.commit()
    return conn


@pytest.fixture
def audit_log_path(tmp_path: Path) -> Path:
    """Configure logging into ``tmp_path/logs`` and return the audit.log path."""
    log_dir = tmp_path / "logs"
    rt_logging.setup_logging(level="DEBUG", log_dir=log_dir, force_json=True)
    return log_dir / "audit.log"


def _read_audit_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


class TestRecordEvent:
    def test_inserts_session_event_row(self, conn: sqlite3.Connection) -> None:
        audit.record_event(
            conn,
            session_id="sess-1",
            type=audit.EV_STATE_TRANSITION,
            payload={"from": "enqueued", "to": "starting"},
        )
        conn.commit()
        rows = conn.execute(
            "SELECT session_id, type, payload FROM session_events"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "sess-1"
        assert rows[0][1] == audit.EV_STATE_TRANSITION
        assert json.loads(rows[0][2]) == {"from": "enqueued", "to": "starting"}

    def test_empty_payload_is_serialized_as_object(self, conn: sqlite3.Connection) -> None:
        audit.record_event(conn, session_id="sess-1", type=audit.EV_WORKER_SPAWN)
        conn.commit()
        row = conn.execute(
            "SELECT payload FROM session_events WHERE session_id=?", ("sess-1",)
        ).fetchone()
        assert json.loads(row[0]) == {}


class TestLogUnboundEvent:
    def test_emits_warning_with_event_type_and_payload(self, audit_log_path: Path) -> None:
        audit.log_unbound_event(
            audit.EV_TELEGRAM_UNAUTHORIZED,
            {"sender_id": 999, "chat_id": -100, "message_id": 17},
        )
        records = _read_audit_lines(audit_log_path)
        assert len(records) == 1
        rec = records[0]
        assert rec["event_type"] == audit.EV_TELEGRAM_UNAUTHORIZED
        assert rec["sender_id"] == 999
        assert rec["chat_id"] == -100
        assert rec["message_id"] == 17
        assert rec["level"] == "warning"

    def test_does_not_emit_bot_token_field(self, audit_log_path: Path) -> None:
        # The audit module never accepts or adds a bot_token field — sanity-check
        # that nothing in the emitted record names the secret key.
        audit.log_unbound_event(audit.EV_TELEGRAM_UNKNOWN_PREFIX, {"prefix": "FOO"})
        records = _read_audit_lines(audit_log_path)
        assert len(records) == 1
        joined = json.dumps(records[0])
        assert "bot_token" not in joined


class TestFiveZeroFiveConstants:
    """005: new audit-event + reason constants."""

    def test_alias_deprecation_used_constant_value(self) -> None:
        assert audit.EV_ALIAS_DEPRECATION_USED == "alias_deprecation_used"

    def test_main_chat_cancel_reason_distinct_from_main_chat_done(self) -> None:
        assert audit.REASON_MAIN_CHAT_CANCEL == "main_chat_cancel"
        assert audit.REASON_MAIN_CHAT_DONE == "main_chat_done"
        assert audit.REASON_MAIN_CHAT_CANCEL != audit.REASON_MAIN_CHAT_DONE

    def test_alias_deprecation_used_log_payload(self, audit_log_path: Path) -> None:
        audit.log_unbound_event(
            audit.EV_ALIAS_DEPRECATION_USED,
            {
                "alias_token": "/done",
                "canonical": "cancel",
                "session_id": "abc",
                "sender_id": 1,
                "message_id": 2,
                "chat_id": 3,
                "message_thread_id": 4,
            },
        )
        records = _read_audit_lines(audit_log_path)
        assert len(records) == 1
        rec = records[0]
        assert rec["event_type"] == "alias_deprecation_used"
        assert rec["alias_token"] == "/done"
        assert rec["canonical"] == "cancel"
        assert rec["session_id"] == "abc"
