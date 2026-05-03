"""Session row mutation + state-transition helpers.

dispatcher and worker both flip a ``sessions.status`` over time. Routing every
mutation through this module keeps three things in lock-step on every change:

1. the DB row update (commit immediately so a crash leaves a recoverable trail)
2. an audit row of type ``state_transition`` (or whatever we pass in)
3. a ``Status: <new>`` message to the bound topic, when one exists

The helpers are deliberately small and synchronous-on-the-DB-side; the topic
post is async because it talks to Telegram. Callers running outside an event
loop should ignore ``post_status_to_topic`` and use ``transition`` directly.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any

from remotask.daemon import audit, topic
from remotask.telegram.client import TelegramClient


def new_session_id() -> str:
    """Return a fresh session id (uuid4 hex; matches existing convention)."""
    return uuid.uuid4().hex


def insert_enqueued_session(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    issue_key: str,
    trigger_user: int,
    trigger_text: str,
    source: str = "jira",
    project_identifier: str | None = None,
) -> None:
    """Insert a fresh ``sessions`` row in ``enqueued`` state.

    Caller is expected to be inside an explicit transaction (``BEGIN IMMEDIATE``)
    so the same-issue concurrency check + insert + lock acquisition happen
    atomically. We only execute the INSERT here — the caller commits.

    ``source`` and ``project_identifier`` (008/T5) record which provider
    and which project produced the session. Default ``source = "jira"``
    keeps existing test paths working until T4 wires the dispatcher's
    adapter-driven source resolution.
    """
    conn.execute(
        "INSERT INTO sessions("
        "id, issue_key, source, project_identifier, status, trigger_user, "
        "trigger_text, enqueued_at"
        ") VALUES (?, ?, ?, ?, 'enqueued', ?, ?, ?)",
        (
            session_id,
            issue_key,
            source,
            project_identifier,
            trigger_user,
            trigger_text,
            int(time.time()),
        ),
    )


def acquire_issue_lock(
    conn: sqlite3.Connection, *, issue_key: str, session_id: str
) -> None:
    """Mark ``locks(resource='issue:<KEY>')`` as held by ``session_id``.

    Same-transaction with the row insert. Will raise on duplicate key, which
    the dispatcher catches as the same-issue race condition.
    """
    conn.execute(
        "INSERT INTO locks(resource, holder_session, acquired_at) VALUES (?, ?, ?)",
        (f"issue:{issue_key}", session_id, int(time.time())),
    )


def release_issue_lock(conn: sqlite3.Connection, *, issue_key: str) -> None:
    """Drop the per-issue lock once the session reaches a terminal state."""
    conn.execute("DELETE FROM locks WHERE resource = ?", (f"issue:{issue_key}",))


def set_topic_id(conn: sqlite3.Connection, *, session_id: str, topic_id: int) -> None:
    """Persist the Telegram ``message_thread_id`` for a session."""
    conn.execute(
        "UPDATE sessions SET topic_id = ? WHERE id = ?", (topic_id, session_id)
    )
    conn.commit()


def transition(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    from_status: str,
    to_status: str,
    extra_columns: dict[str, Any] | None = None,
) -> None:
    """Move a session's status, set timestamps, and append a ``state_transition`` event.

    The ``from_status`` is enforced via the WHERE clause so a stale caller
    cannot accidentally double-transition. ``extra_columns`` are added to the
    same UPDATE — used to set ``worktree_path`` / ``branch`` on enter-running
    and ``pr_url`` / ``pr_number`` on enter-pr_created.
    """
    now = int(time.time())
    columns: list[str] = ["status = ?"]
    values: list[Any] = [to_status]

    if to_status == "starting":
        columns.append("started_at = ?")
        values.append(now)
    if to_status in ("pr_created", "completed", "failed", "canceled"):
        columns.append("ended_at = ?")
        values.append(now)
    if extra_columns:
        for col, val in extra_columns.items():
            columns.append(f"{col} = ?")
            values.append(val)
    values.extend([session_id, from_status])

    cur = conn.execute(
        f"UPDATE sessions SET {', '.join(columns)} "
        f"WHERE id = ? AND status = ?",
        values,
    )
    if cur.rowcount != 1:
        raise RuntimeError(
            f"transition {from_status}→{to_status} for session {session_id} "
            f"matched {cur.rowcount} rows"
        )
    audit.record_event(
        conn,
        session_id=session_id,
        type=audit.EV_STATE_TRANSITION,
        payload={"from": from_status, "to": to_status, "at": now},
    )
    conn.commit()


async def post_status_to_topic(
    client: TelegramClient,
    *,
    chat_id: int,
    topic_id: int | None,
    new_status: str,
    issue_key: str | None = None,
) -> None:
    """Best-effort ``Status: <new_status>`` post into the bound topic.

    005: every topic-bound status post MUST carry a ``[<issue_key>]`` prefix
    (FR-009 / FR-011). When ``topic_id`` is non-None, ``issue_key`` is
    therefore required — passing ``None`` raises :class:`ValueError` so a new
    call site can't silently regress un-prefixed output. ``issue_key`` may
    still be omitted when ``topic_id`` is None (no-op early return).
    """
    if topic_id is None:
        return
    if issue_key is None:
        raise ValueError(
            "issue_key is required for topic-bound status posts (FR-009 / FR-011)"
        )
    body = topic.format_progress(
        issue_key, topic.TPL_STATUS.format(status=new_status)
    )
    await topic.post_to_topic(
        client,
        chat_id=chat_id,
        topic_id=topic_id,
        text=body,
    )
