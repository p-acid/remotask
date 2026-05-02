"""Integration tests for ``/status`` slash command (004 / US3).

Covers the main-chat list and the topic-detail variants. Uses direct DB
inserts (no real worker) so the test runs in milliseconds.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path

import pytest

from remotask.core import config as rt_config
from remotask.core import db as core_db
from remotask.core import paths as rt_paths
from remotask.daemon import dispatcher as rt_dispatcher
from remotask.telegram.client import TelegramClient
from tests.fakes.fake_telegram import FakeTelegram


@pytest.fixture
def isolated_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "cache").mkdir()
    return tmp_path


@pytest.fixture
def conn(isolated_xdg: Path) -> sqlite3.Connection:
    return core_db.connect(rt_paths.db_path())


@pytest.fixture
def fake_tg() -> FakeTelegram:
    return FakeTelegram()


def _build_cfg(fake_tg: FakeTelegram) -> rt_config.ConfigSchema:
    cfg = rt_config.default_schema()
    cfg.telegram.bot_token = fake_tg.bot_token
    cfg.telegram.group_chat_id = fake_tg.chat_id
    cfg.telegram.allowed_user_ids = [99001]
    return cfg


def _build_ctx(conn, client, cfg) -> rt_dispatcher.DispatchContext:
    return rt_dispatcher.DispatchContext(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=lambda coro: coro.close() if hasattr(coro, "close") else None,
        worker_argv=None,
        worker_env=None,
    )


def _slash_status(
    *, sender_id: int, chat_id: int, topic_id: int | None, message_id: int
) -> dict:
    cmd = "/status"
    msg = {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": cmd,
        "entities": [{"type": "bot_command", "offset": 0, "length": len(cmd)}],
    }
    if topic_id is not None:
        msg["message_thread_id"] = topic_id
    return msg


def _seed_session(
    conn: sqlite3.Connection,
    *,
    issue_key: str,
    status: str,
    topic_id: int | None,
    age_seconds: int = 60,
) -> str:
    sid = uuid.uuid4().hex
    now = int(time.time())
    conn.execute(
        "INSERT INTO sessions(id, issue_key, status, topic_id, enqueued_at, started_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (sid, issue_key, status, topic_id, now - age_seconds, now - age_seconds),
    )
    conn.commit()
    return sid


async def test_status_main_chat_no_active(
    isolated_xdg: Path, conn: sqlite3.Connection, fake_tg: FakeTelegram
) -> None:
    cfg = _build_cfg(fake_tg)
    client = TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())
    ctx = _build_ctx(conn, client, cfg)

    await rt_dispatcher.dispatch(
        _slash_status(sender_id=99001, chat_id=fake_tg.chat_id, topic_id=None, message_id=1),
        ctx,
    )
    await client.aclose()

    main_replies = [m.text for m in fake_tg.sent_messages if m.message_thread_id is None]
    assert main_replies == ["No active sessions."]


async def test_status_main_chat_lists_active_sessions(
    isolated_xdg: Path, conn: sqlite3.Connection, fake_tg: FakeTelegram
) -> None:
    _seed_session(conn, issue_key="ZXTL-1", status="running", topic_id=100, age_seconds=30)
    _seed_session(conn, issue_key="ZXTL-2", status="starting", topic_id=101, age_seconds=10)
    _seed_session(conn, issue_key="ZXTL-OLD", status="completed", topic_id=99, age_seconds=300)

    cfg = _build_cfg(fake_tg)
    client = TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())
    ctx = _build_ctx(conn, client, cfg)

    await rt_dispatcher.dispatch(
        _slash_status(sender_id=99001, chat_id=fake_tg.chat_id, topic_id=None, message_id=1),
        ctx,
    )
    await client.aclose()

    main_replies = [m.text for m in fake_tg.sent_messages if m.message_thread_id is None]
    assert len(main_replies) == 1
    body = main_replies[0]
    # Header reports 2 active sessions.
    assert "Active sessions (2)" in body
    # Both active issue keys appear.
    assert "ZXTL-1" in body
    assert "ZXTL-2" in body
    # Terminal session is NOT shown.
    assert "ZXTL-OLD" not in body


async def test_status_topic_detail(
    isolated_xdg: Path, conn: sqlite3.Connection, fake_tg: FakeTelegram
) -> None:
    _seed_session(conn, issue_key="ZXTL-7", status="running", topic_id=555, age_seconds=120)

    cfg = _build_cfg(fake_tg)
    client = TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())
    ctx = _build_ctx(conn, client, cfg)

    await rt_dispatcher.dispatch(
        _slash_status(sender_id=99001, chat_id=fake_tg.chat_id, topic_id=555, message_id=1),
        ctx,
    )
    await client.aclose()

    topic_replies = [m.text for m in fake_tg.sent_messages if m.message_thread_id == 555]
    assert len(topic_replies) == 1
    detail = topic_replies[0]
    assert "ZXTL-7" in detail
    assert "running" in detail


async def test_status_topic_detail_no_active(
    isolated_xdg: Path, conn: sqlite3.Connection, fake_tg: FakeTelegram
) -> None:
    cfg = _build_cfg(fake_tg)
    client = TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())
    ctx = _build_ctx(conn, client, cfg)

    await rt_dispatcher.dispatch(
        _slash_status(sender_id=99001, chat_id=fake_tg.chat_id, topic_id=999, message_id=1),
        ctx,
    )
    await client.aclose()

    topic_replies = [m.text for m in fake_tg.sent_messages if m.message_thread_id == 999]
    assert topic_replies == ["No active session in this topic."]


async def test_status_main_chat_truncation_at_10(
    isolated_xdg: Path, conn: sqlite3.Connection, fake_tg: FakeTelegram
) -> None:
    """11 active sessions → 10 listed + '+ 1 more' trailer."""
    for i in range(11):
        _seed_session(
            conn,
            issue_key=f"ZXTL-{i}",
            status="running",
            topic_id=200 + i,
            age_seconds=10 + i,
        )

    cfg = _build_cfg(fake_tg)
    client = TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())
    ctx = _build_ctx(conn, client, cfg)

    await rt_dispatcher.dispatch(
        _slash_status(sender_id=99001, chat_id=fake_tg.chat_id, topic_id=None, message_id=1),
        ctx,
    )
    await client.aclose()

    body = next(m.text for m in fake_tg.sent_messages if m.message_thread_id is None)
    # Header reports the *total* active count (11), then 10 lines, then a
    # "+ 1 more (truncated)" footer reflecting actual overflow rather than
    # always-1 from the previous LIMIT 11 / fetch-all approach.
    assert "Active sessions (11)" in body
    assert "+ 1 more" in body
