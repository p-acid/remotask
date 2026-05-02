"""Unit tests for ``remotask.daemon.dispatcher``.

Covers the US1 accept-path. Other branches (US2 unknown prefix, US3 unauth,
US6 same-issue) live in their own phases — this file will gain cases as those
phases land.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from remotask.core import config as rt_config
from remotask.core import db as core_db
from remotask.core import projects as rt_projects
from remotask.daemon import dispatcher as rt_dispatcher
from remotask.telegram.client import TelegramClient
from tests.fakes.fake_telegram import FakeTelegram
from tests.fakes.git_repo import make_repo


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


@pytest.fixture
def conn(tmp_path: Path, repo_path: Path) -> sqlite3.Connection:
    conn = core_db.connect(tmp_path / "state.db")
    rt_projects.add(conn, "ZXTL", str(repo_path), base_branch="main")
    return conn


@pytest.fixture
def fake_tg() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def client(fake_tg: FakeTelegram) -> TelegramClient:
    return TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())


@pytest.fixture
def cfg(fake_tg: FakeTelegram, tmp_path: Path) -> rt_config.ConfigSchema:
    schema = rt_config.default_schema()
    schema.telegram.bot_token = fake_tg.bot_token
    schema.telegram.group_chat_id = fake_tg.chat_id
    schema.telegram.allowed_user_ids = [99001]
    schema.agent.worktree_root = str(tmp_path / "wt")
    return schema


def _build_ctx(
    *,
    conn: sqlite3.Connection,
    client: TelegramClient,
    cfg: rt_config.ConfigSchema,
    spawn: Callable[[object], None],
    worker_argv: list[str] | None = None,
) -> rt_dispatcher.DispatchContext:
    return rt_dispatcher.DispatchContext(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=spawn,
        worker_argv=worker_argv,
    )


def _message(text: str, *, sender_id: int, chat_id: int, message_id: int = 1) -> dict:
    return {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": text,
    }


class TestAcceptPath:
    async def test_inserts_session_and_creates_topic(
        self,
        conn: sqlite3.Connection,
        client: TelegramClient,
        cfg: rt_config.ConfigSchema,
        fake_tg: FakeTelegram,
    ) -> None:
        spawned: list[object] = []
        ctx = _build_ctx(
            conn=conn,
            client=client,
            cfg=cfg,
            # We don't actually want to RUN the worker in a unit test —
            # capture the coroutine object and close it without scheduling.
            spawn=lambda coro: (spawned.append(coro), coro.close())[1] if hasattr(coro, "close") else None,
        )
        msg = _message("ZXTL-1234", sender_id=99001, chat_id=fake_tg.chat_id)

        await rt_dispatcher.dispatch(msg, ctx)

        # Session row inserted, topic_id stored, status moved to starting.
        rows = conn.execute(
            "SELECT issue_key, status, topic_id, trigger_user, trigger_text "
            "FROM sessions"
        ).fetchall()
        assert len(rows) == 1
        issue_key, status, topic_id, trigger_user, trigger_text = rows[0]
        assert issue_key == "ZXTL-1234"
        assert status == "starting"
        assert topic_id is not None and topic_id > 0
        assert trigger_user == 99001
        assert trigger_text == "ZXTL-1234"

        # Topic was created exactly once with the issue key as name.
        assert len(fake_tg.created_topics) == 1
        assert fake_tg.created_topics[0].name == "ZXTL-1234"

        # Two messages posted into the topic: "Session starting …" + "Status: starting".
        topic_messages = [m for m in fake_tg.sent_messages if m.message_thread_id == topic_id]
        assert len(topic_messages) == 2
        assert "Session starting for ZXTL-1234" in topic_messages[0].text
        assert "Status: starting" in topic_messages[1].text

        # Lock acquired.
        lock_rows = conn.execute(
            "SELECT resource, holder_session FROM locks WHERE resource = ?",
            ("issue:ZXTL-1234",),
        ).fetchall()
        assert len(lock_rows) == 1

        # Worker spawn was invoked exactly once.
        assert len(spawned) == 1

    async def test_audit_event_for_received_message(
        self,
        conn: sqlite3.Connection,
        client: TelegramClient,
        cfg: rt_config.ConfigSchema,
        fake_tg: FakeTelegram,
    ) -> None:
        ctx = _build_ctx(
            conn=conn,
            client=client,
            cfg=cfg,
            spawn=lambda coro: coro.close() if hasattr(coro, "close") else None,
        )
        msg = _message(
            "Please look at ZXTL-1234 for me",
            sender_id=99001,
            chat_id=fake_tg.chat_id,
            message_id=42,
        )

        await rt_dispatcher.dispatch(msg, ctx)

        events = conn.execute(
            "SELECT type, payload FROM session_events ORDER BY id"
        ).fetchall()
        types = [e[0] for e in events]
        # We expect: telegram_message_received, state_transition (enqueued→starting).
        assert "telegram_message_received" in types
        assert "state_transition" in types

    async def test_ignores_message_without_issue_key(
        self,
        conn: sqlite3.Connection,
        client: TelegramClient,
        cfg: rt_config.ConfigSchema,
        fake_tg: FakeTelegram,
    ) -> None:
        ctx = _build_ctx(
            conn=conn,
            client=client,
            cfg=cfg,
            spawn=lambda coro: coro.close() if hasattr(coro, "close") else None,
        )
        msg = _message("just chatting here", sender_id=99001, chat_id=fake_tg.chat_id)

        await rt_dispatcher.dispatch(msg, ctx)

        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert fake_tg.sent_messages == []
        assert fake_tg.created_topics == []


class TestUnknownPrefixBranch:
    async def test_replies_in_main_chat_with_registered_list(
        self,
        conn: sqlite3.Connection,
        client: TelegramClient,
        cfg: rt_config.ConfigSchema,
        fake_tg: FakeTelegram,
    ) -> None:
        ctx = _build_ctx(
            conn=conn,
            client=client,
            cfg=cfg,
            spawn=lambda coro: coro.close() if hasattr(coro, "close") else None,
        )
        msg = _message("BAR-7", sender_id=99001, chat_id=fake_tg.chat_id)

        await rt_dispatcher.dispatch(msg, ctx)

        # No session inserted, no topic created.
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert fake_tg.created_topics == []

        # One main-chat reply naming the unknown prefix and listing registered.
        assert len(fake_tg.sent_messages) == 1
        reply = fake_tg.sent_messages[0]
        assert reply.message_thread_id is None
        assert "BAR" in reply.text
        assert "ZXTL" in reply.text

    async def test_emits_audit_event_for_unknown_prefix(
        self,
        tmp_path: Path,
        conn: sqlite3.Connection,
        client: TelegramClient,
        cfg: rt_config.ConfigSchema,
        fake_tg: FakeTelegram,
    ) -> None:
        # Configure logging so audit.log gets written under tmp_path.
        from remotask.core import logging as rt_logging

        log_dir = tmp_path / "logs"
        rt_logging.setup_logging(level="DEBUG", log_dir=log_dir, force_json=True)

        ctx = _build_ctx(
            conn=conn,
            client=client,
            cfg=cfg,
            spawn=lambda coro: coro.close() if hasattr(coro, "close") else None,
        )
        msg = _message(
            "BAR-99", sender_id=99001, chat_id=fake_tg.chat_id, message_id=42
        )

        await rt_dispatcher.dispatch(msg, ctx)

        import json

        lines = (log_dir / "audit.log").read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines if line.strip()]
        assert any(e.get("event_type") == "telegram_unknown_prefix" for e in events)
        evt = next(e for e in events if e["event_type"] == "telegram_unknown_prefix")
        assert evt["prefix"] == "BAR"
        assert evt["key"] == "BAR-99"
        assert "ZXTL" in evt["registered_prefixes"]


class TestUnauthorizedBranch:
    async def test_silent_rejection_no_reply_no_session(
        self,
        conn: sqlite3.Connection,
        client: TelegramClient,
        cfg: rt_config.ConfigSchema,
        fake_tg: FakeTelegram,
    ) -> None:
        ctx = _build_ctx(
            conn=conn,
            client=client,
            cfg=cfg,
            spawn=lambda coro: coro.close() if hasattr(coro, "close") else None,
        )
        # Sender 88888 is NOT in cfg.telegram.allowed_user_ids = [99001].
        msg = _message("ZXTL-1234", sender_id=88888, chat_id=fake_tg.chat_id)

        await rt_dispatcher.dispatch(msg, ctx)

        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert fake_tg.sent_messages == []
        assert fake_tg.created_topics == []

    async def test_emits_audit_event_for_unauthorized(
        self,
        tmp_path: Path,
        conn: sqlite3.Connection,
        client: TelegramClient,
        cfg: rt_config.ConfigSchema,
        fake_tg: FakeTelegram,
    ) -> None:
        from remotask.core import logging as rt_logging

        log_dir = tmp_path / "logs"
        rt_logging.setup_logging(level="DEBUG", log_dir=log_dir, force_json=True)

        ctx = _build_ctx(
            conn=conn,
            client=client,
            cfg=cfg,
            spawn=lambda coro: coro.close() if hasattr(coro, "close") else None,
        )
        msg = _message(
            "ZXTL-1234", sender_id=88888, chat_id=fake_tg.chat_id, message_id=99
        )
        await rt_dispatcher.dispatch(msg, ctx)

        import json

        lines = (log_dir / "audit.log").read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines if line.strip()]
        unauth = [e for e in events if e.get("event_type") == "telegram_unauthorized"]
        assert len(unauth) == 1
        assert unauth[0]["sender_id"] == 88888
        assert unauth[0]["chat_id"] == fake_tg.chat_id
        assert unauth[0]["message_id"] == 99


# ----- 003 / US2: termination dispatch branches ---------------------------


def _seed_running_session(conn: sqlite3.Connection, *, topic_id: int, pid: int = 99999) -> str:
    """Insert a session in `running` state with a bound topic and pid (no real worker)."""
    import time
    import uuid

    sid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO sessions(id, issue_key, status, topic_id, pid, enqueued_at, started_at) "
        "VALUES (?, ?, 'running', ?, ?, ?, ?)",
        (sid, "ZXTL-1234", topic_id, pid, int(time.time()), int(time.time())),
    )
    conn.commit()
    return sid


class TestTerminationBranch:
    async def test_accepted_termination_records_audit_and_signals_pid(
        self,
        tmp_path: Path,
        conn: sqlite3.Connection,
        client: TelegramClient,
        cfg: rt_config.ConfigSchema,
        fake_tg: FakeTelegram,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from remotask.core import logging as rt_logging

        rt_logging.setup_logging(level="DEBUG", log_dir=tmp_path / "logs", force_json=True)

        topic_id = 555
        sid = _seed_running_session(conn, topic_id=topic_id)

        marked: list[tuple[str, int]] = []
        signaled: list[tuple[int, int]] = []

        ctx = rt_dispatcher.DispatchContext(
            conn=conn,
            client=client,
            cfg=cfg,
            spawn_worker_task=lambda coro: coro.close() if hasattr(coro, "close") else None,
            mark_operator_stop_in_flight=lambda s, p: marked.append((s, p)),
            is_operator_stop_in_flight=lambda s: False,
            worker_pid_for_session=lambda s: 99999,
        )

        # Capture os.kill calls instead of actually sending signals.
        import os as _os

        monkeypatch.setattr(_os, "kill", lambda pid, sig: signaled.append((pid, sig)))

        msg = {
            **_message("done", sender_id=99001, chat_id=fake_tg.chat_id, message_id=42),
            "message_thread_id": topic_id,
        }
        await rt_dispatcher.dispatch(msg, ctx)

        # SIGUSR1 was sent to the worker pid.
        import signal as _signal

        assert signaled == [(99999, _signal.SIGUSR1)]
        # Runtime in-flight set was updated.
        assert marked == [(sid, 99999)]
        # session_events row is present.
        types = [
            r[0]
            for r in conn.execute(
                "SELECT type FROM session_events WHERE session_id = ?", (sid,)
            ).fetchall()
        ]
        assert "telegram_termination_received" in types

    async def test_unauthorized_termination_is_audit_logged(
        self,
        tmp_path: Path,
        conn: sqlite3.Connection,
        client: TelegramClient,
        cfg: rt_config.ConfigSchema,
        fake_tg: FakeTelegram,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from remotask.core import logging as rt_logging

        log_dir = tmp_path / "logs"
        rt_logging.setup_logging(level="DEBUG", log_dir=log_dir, force_json=True)

        topic_id = 555
        _seed_running_session(conn, topic_id=topic_id)

        signaled: list[tuple[int, int]] = []

        ctx = rt_dispatcher.DispatchContext(
            conn=conn,
            client=client,
            cfg=cfg,
            spawn_worker_task=lambda coro: coro.close() if hasattr(coro, "close") else None,
            mark_operator_stop_in_flight=lambda s, p: None,
            is_operator_stop_in_flight=lambda s: False,
            worker_pid_for_session=lambda s: 99999,
        )

        import os as _os

        monkeypatch.setattr(_os, "kill", lambda pid, sig: signaled.append((pid, sig)))

        msg = {
            **_message(
                "done", sender_id=88888, chat_id=fake_tg.chat_id, message_id=43
            ),
            "message_thread_id": topic_id,
        }
        await rt_dispatcher.dispatch(msg, ctx)

        # No signal sent.
        assert signaled == []
        import json as _json

        events = [
            _json.loads(line)
            for line in (log_dir / "audit.log").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        rejected = [e for e in events if e.get("event_type") == "telegram_termination_rejected"]
        assert len(rejected) == 1
        assert rejected[0]["reason"] == "unauthorized"

    async def test_termination_with_no_active_session_is_audit_logged(
        self,
        tmp_path: Path,
        conn: sqlite3.Connection,
        client: TelegramClient,
        cfg: rt_config.ConfigSchema,
        fake_tg: FakeTelegram,
    ) -> None:
        from remotask.core import logging as rt_logging

        log_dir = tmp_path / "logs"
        rt_logging.setup_logging(level="DEBUG", log_dir=log_dir, force_json=True)

        # No session inserted.
        ctx = rt_dispatcher.DispatchContext(
            conn=conn,
            client=client,
            cfg=cfg,
            spawn_worker_task=lambda coro: coro.close() if hasattr(coro, "close") else None,
            mark_operator_stop_in_flight=lambda s, p: None,
            is_operator_stop_in_flight=lambda s: False,
            worker_pid_for_session=lambda s: None,
        )

        msg = {
            **_message("stop", sender_id=99001, chat_id=fake_tg.chat_id, message_id=44),
            "message_thread_id": 999,  # no active session bound to this topic
        }
        await rt_dispatcher.dispatch(msg, ctx)

        import json as _json

        events = [
            _json.loads(line)
            for line in (log_dir / "audit.log").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        rejected = [e for e in events if e.get("event_type") == "telegram_termination_rejected"]
        assert len(rejected) == 1
        assert rejected[0]["reason"] == "no_active_session"

    async def test_termination_in_main_chat_is_silently_ignored(
        self,
        conn: sqlite3.Connection,
        client: TelegramClient,
        cfg: rt_config.ConfigSchema,
        fake_tg: FakeTelegram,
    ) -> None:
        topic_id = 555
        _seed_running_session(conn, topic_id=topic_id)

        ctx = rt_dispatcher.DispatchContext(
            conn=conn,
            client=client,
            cfg=cfg,
            spawn_worker_task=lambda coro: coro.close() if hasattr(coro, "close") else None,
            mark_operator_stop_in_flight=lambda s, p: None,
            is_operator_stop_in_flight=lambda s: False,
            worker_pid_for_session=lambda s: 99999,
        )

        # No message_thread_id → main chat → falls through, no termination action.
        msg = _message("done", sender_id=99001, chat_id=fake_tg.chat_id, message_id=45)
        await rt_dispatcher.dispatch(msg, ctx)

        # No new session_events rows (no session was actioned).
        type_seq = [
            r[0]
            for r in conn.execute("SELECT type FROM session_events").fetchall()
        ]
        # state_transition rows from the seed do not exist (we inserted directly);
        # nothing new should appear from this dispatch.
        assert "telegram_termination_received" not in type_seq
