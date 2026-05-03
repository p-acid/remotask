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
EV_SLASH_COMMAND_RECEIVED: Final = "slash_command_received"
# 008/T8 — emitted from dispatcher._accept_trigger after the session row
# is inserted. Payload: {adapter, source_identifier, canonical_key}.
EV_TASK_SOURCE_RESOLVED: Final = "task_source_resolved"

# 007: per-turn agent events emitted by the SDK driver via stdout EVENT lines.
# Daemon-side ``worker.py`` parses ``EVENT <type> <json>`` and dispatches the
# payload here. The ``type`` strings are the column values used directly.
EV_AGENT_TURN: Final = "agent.turn"  # umbrella label for fan-out site only.
EV_AGENT_TOOL_USE: Final = "agent.tool_use"
EV_AGENT_TOOL_RESULT: Final = "agent.tool_result"
EV_AGENT_STOP: Final = "agent.stop"
EV_AGENT_INTERRUPT: Final = "agent.interrupt"
AGENT_EVENT_TYPES: Final = frozenset(
    {EV_AGENT_TOOL_USE, EV_AGENT_TOOL_RESULT, EV_AGENT_STOP, EV_AGENT_INTERRUPT}
)

# ---- unbound event types (emitted to the audit logger only) ---------------

EV_TELEGRAM_UNAUTHORIZED: Final = "telegram_unauthorized"
EV_TELEGRAM_UNKNOWN_PREFIX: Final = "telegram_unknown_prefix"
EV_LISTENER_DEGRADED: Final = "listener_degraded"
EV_TELEGRAM_TERMINATION_REJECTED: Final = "telegram_termination_rejected"
EV_SLASH_COMMAND_REJECTED: Final = "slash_command_rejected"
EV_COMMANDS_REGISTERED: Final = "commands_registered"
EV_COMMANDS_REGISTRATION_FAILED: Final = "commands_registration_failed"

# ---- slash_command_rejected reason values --------------------------------

# 005: ``/cancel`` issued in main chat (no topic_id) is rejected with this reason.
REASON_MAIN_CHAT_CANCEL: Final = "main_chat_cancel"


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
