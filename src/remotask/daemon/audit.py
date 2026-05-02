"""Audit-event writer.

V0001 schema constraint: ``session_events.session_id`` is ``NOT NULL`` and has
a foreign key to ``sessions(id)``. So events that are *not* tied to a specific
session (whitelist rejection, unknown prefix, listener-degraded, …) cannot live
in ``session_events``. They are emitted instead via the existing
``audit_logger()`` from ``core/logging.py``, which writes structured JSON lines
to ``~/.local/share/remotask/logs/audit.log`` (see data-model.md §Audit event
taxonomy for the constraint clarification).

This module is the single chokepoint for writing audit data so the bot token
never escapes into a payload accidentally.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Final

from remotask.core import logging as rt_logging

# ---- session-bound event types (inserted into session_events) -------------

EV_STATE_TRANSITION: Final = "state_transition"
EV_WORKER_SPAWN: Final = "worker_spawn"
EV_WORKER_EXIT: Final = "worker_exit"
EV_WORKER_TIMEOUT: Final = "worker_timeout"
EV_DAEMON_RESTART: Final = "daemon_restart"
EV_TELEGRAM_MESSAGE_RECEIVED: Final = "telegram_message_received"
EV_TELEGRAM_TOPIC_CREATE_FAILED: Final = "telegram_topic_create_failed"
EV_TELEGRAM_ALREADY_IN_FLIGHT: Final = "telegram_already_in_flight"
EV_TELEGRAM_TERMINATION_RECEIVED: Final = "telegram_termination_received"

# ---- unbound event types (emitted to the audit logger only) ---------------

EV_TELEGRAM_UNAUTHORIZED: Final = "telegram_unauthorized"
EV_TELEGRAM_UNKNOWN_PREFIX: Final = "telegram_unknown_prefix"
EV_LISTENER_DEGRADED: Final = "listener_degraded"
EV_TELEGRAM_TERMINATION_REJECTED: Final = "telegram_termination_rejected"


def record_event(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Insert a session-bound event row into ``session_events``.

    Caller is responsible for committing the surrounding transaction (this lets
    a state-transition event be written in the same txn as the row update).
    """
    payload_json = json.dumps(payload or {}, separators=(",", ":"))
    conn.execute(
        "INSERT INTO session_events(session_id, type, payload, created_at) "
        "VALUES (?, ?, ?, ?)",
        (session_id, type, payload_json, int(time.time())),
    )


def log_unbound_event(type: str, payload: dict[str, Any] | None = None) -> None:
    """Emit a non-session-bound audit event as a structured JSON line.

    This goes through the same audit logger (``audit.log``) that the existing
    code uses, at WARNING level so an empty/quiet operations day produces no
    noise but a rejected trigger does.
    """
    log = rt_logging.audit_logger()
    log.warning("audit_event", event_type=type, **(payload or {}))
