"""Integration test for daemon-restart recovery (R10 / FR-014).

Pre-seeds the DB with sessions stuck in non-terminal states (as a previous
daemon would have left them on a crash), runs the recovery routine, and
asserts that all of those rows are forcibly transitioned to ``failed`` with
reason ``daemon_restart``, and that any session with a bound topic gets a
"Session terminated by daemon restart." notice.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from remotask.core import db as core_db
from remotask.daemon.runtime import recover_non_terminal_sessions
from remotask.telegram.client import TelegramClient
from tests.fakes.fake_telegram import FakeTelegram


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return core_db.connect(tmp_path / "state.db")


@pytest.fixture
def fake_tg() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def client(fake_tg: FakeTelegram) -> TelegramClient:
    return TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())


def _insert_session(
    conn: sqlite3.Connection, *, sid: str, issue: str, status: str, topic_id: int | None
) -> None:
    conn.execute(
        "INSERT INTO sessions(id, issue_key, status, topic_id, enqueued_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (sid, issue, status, topic_id, int(time.time())),
    )
    conn.execute(
        "INSERT INTO locks(resource, holder_session, acquired_at) VALUES (?, ?, ?)",
        (f"issue:{issue}", sid, int(time.time())),
    )
    conn.commit()


async def test_marks_non_terminal_sessions_failed_on_recovery(
    conn: sqlite3.Connection, client: TelegramClient, fake_tg: FakeTelegram
) -> None:
    _insert_session(conn, sid="s1", issue="ZXTL-1", status="enqueued", topic_id=None)
    _insert_session(conn, sid="s2", issue="ZXTL-2", status="starting", topic_id=200)
    _insert_session(conn, sid="s3", issue="ZXTL-3", status="running", topic_id=201)
    _insert_session(conn, sid="s4", issue="ZXTL-4", status="completed", topic_id=202)  # control: should not change

    n = await recover_non_terminal_sessions(conn=conn, client=client, chat_id=fake_tg.chat_id)
    assert n == 3

    # The three non-terminal sessions are now failed with reason 'daemon_restart'.
    rows = conn.execute(
        "SELECT id, status, error_message FROM sessions ORDER BY id"
    ).fetchall()
    by_id = {r[0]: (r[1], r[2]) for r in rows}
    assert by_id["s1"] == ("failed", "daemon_restart")
    assert by_id["s2"] == ("failed", "daemon_restart")
    assert by_id["s3"] == ("failed", "daemon_restart")
    # The terminal session is left alone.
    assert by_id["s4"][0] == "completed"

    # Locks released for the three recovered sessions.
    locks = conn.execute("SELECT resource FROM locks").fetchall()
    assert {row[0] for row in locks} == {"issue:ZXTL-4"}

    # Topic notices posted only for sessions that had a topic_id.
    posted_to = {m.message_thread_id for m in fake_tg.sent_messages}
    assert 200 in posted_to
    assert 201 in posted_to
    # s1 had no topic_id → no message.
    # s4 was terminal → no message.
    msgs = [m.text for m in fake_tg.sent_messages if m.message_thread_id in (200, 201)]
    assert all("Session terminated by daemon restart" in t for t in msgs)


async def test_recovery_with_no_rows_is_a_noop(
    conn: sqlite3.Connection, client: TelegramClient, fake_tg: FakeTelegram
) -> None:
    n = await recover_non_terminal_sessions(conn=conn, client=client, chat_id=fake_tg.chat_id)
    assert n == 0
    assert fake_tg.sent_messages == []
