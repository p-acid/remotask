"""Integration test for 006 / US1: ``/done`` slash is rejected as unknown_command.

Confirms that the deprecated alias ``/done`` (slash form) no longer triggers
the cancel ladder. Three contexts are covered:

1. ``/done`` sent inside an active session topic → session keeps running and
   the dispatcher emits ``slash_command_rejected reason=unknown_command``.
2. ``/done`` sent in main chat → same ``unknown_command`` rejection (NOT
   ``main_chat_done``, which was removed in 006).
3. ``/done@<bot_username>`` form sent in topic → same ``unknown_command``
   rejection.

Plus a US3 regression: across a full sequence of legacy alias inputs, no
outbound message contains the substring ``"deprecated"``.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from remotask.core import config as rt_config
from remotask.core import db as core_db
from remotask.core import logging as rt_logging
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


def _build_cfg(fake_tg: FakeTelegram, *, worktree_root: Path) -> rt_config.ConfigSchema:
    cfg = rt_config.default_schema()
    cfg.telegram.bot_token = fake_tg.bot_token
    cfg.telegram.group_chat_id = fake_tg.chat_id
    cfg.telegram.allowed_user_ids = [99001]
    cfg.agent.worktree_root = str(worktree_root)
    return cfg


def _seed_running_session(
    conn: sqlite3.Connection, *, topic_id: int, pid: int = 99999
) -> str:
    """Insert a session row in 'running' state with a bound topic and pid."""
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


def _slash(
    text: str,
    *,
    sender_id: int,
    chat_id: int,
    message_id: int,
    topic_id: int | None = None,
    cmd_length: int | None = None,
) -> dict:
    if cmd_length is None:
        cmd_length = len(text.split(" ", 1)[0])
    msg: dict = {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": text,
        "entities": [{"type": "bot_command", "offset": 0, "length": cmd_length}],
    }
    if topic_id is not None:
        msg["message_thread_id"] = topic_id
    return msg


def _build_ctx(
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
    cfg: rt_config.ConfigSchema,
    *,
    bot_username: str | None = None,
) -> rt_dispatcher.DispatchContext:
    client = TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())
    return rt_dispatcher.DispatchContext(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=lambda coro: coro.close() if hasattr(coro, "close") else None,
        mark_operator_stop_in_flight=lambda s, p: None,
        is_operator_stop_in_flight=lambda s: False,
        worker_pid_for_session=lambda s: None,
        bot_username=bot_username,
    )


def _read_audit_events(log_dir: Path) -> list[dict]:
    p = log_dir / "audit.log"
    if not p.exists():
        return []
    return [
        json.loads(line)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def test_slash_done_in_topic_rejected_as_unknown_command(
    tmp_path: Path,
    isolated_xdg: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
) -> None:
    log_dir = tmp_path / "logs"
    rt_logging.setup_logging(level="DEBUG", log_dir=log_dir, force_json=True)
    cfg = _build_cfg(fake_tg, worktree_root=tmp_path / "wt")

    topic_id = 555
    sid = _seed_running_session(conn, topic_id=topic_id)

    ctx = _build_ctx(conn, fake_tg, cfg)

    msg = _slash(
        "/done",
        sender_id=99001,
        chat_id=fake_tg.chat_id,
        message_id=42,
        topic_id=topic_id,
    )
    await rt_dispatcher.dispatch(msg, ctx)

    # Session unchanged.
    row = conn.execute("SELECT status FROM sessions WHERE id = ?", (sid,)).fetchone()
    assert row[0] == "running"

    # No outbound message at all (silent rejection).
    assert fake_tg.sent_messages == []

    events = _read_audit_events(log_dir)
    rejected = [e for e in events if e.get("event_type") == "slash_command_rejected"]
    assert len(rejected) == 1
    assert rejected[0]["reason"] == "unknown_command"
    assert rejected[0]["command"] == "done"

    # No alias_deprecation_used events.
    deprec = [e for e in events if e.get("event_type") == "alias_deprecation_used"]
    assert deprec == []

    # No "deprecated" string anywhere in outbound messages (US3).
    assert all("deprecated" not in m.text for m in fake_tg.sent_messages)


async def test_slash_done_in_main_chat_rejected_as_unknown_command(
    tmp_path: Path,
    isolated_xdg: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
) -> None:
    log_dir = tmp_path / "logs"
    rt_logging.setup_logging(level="DEBUG", log_dir=log_dir, force_json=True)
    cfg = _build_cfg(fake_tg, worktree_root=tmp_path / "wt")

    ctx = _build_ctx(conn, fake_tg, cfg)

    # No topic_id → main chat.
    msg = _slash(
        "/done", sender_id=99001, chat_id=fake_tg.chat_id, message_id=43
    )
    await rt_dispatcher.dispatch(msg, ctx)

    events = _read_audit_events(log_dir)
    rejected = [e for e in events if e.get("event_type") == "slash_command_rejected"]
    assert len(rejected) == 1
    # Critical: NOT main_chat_done (constant removed in 006).
    assert rejected[0]["reason"] == "unknown_command"
    assert rejected[0]["command"] == "done"

    # main_chat_done reason must not appear anywhere.
    main_chat_done = [
        e for e in events if e.get("reason") == "main_chat_done"
    ]
    assert main_chat_done == []


async def test_slash_done_at_bot_form_rejected_as_unknown_command(
    tmp_path: Path,
    isolated_xdg: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
) -> None:
    log_dir = tmp_path / "logs"
    rt_logging.setup_logging(level="DEBUG", log_dir=log_dir, force_json=True)
    cfg = _build_cfg(fake_tg, worktree_root=tmp_path / "wt")

    topic_id = 555
    _seed_running_session(conn, topic_id=topic_id)

    bot_username = "curious_claude_notification_bot"
    ctx = _build_ctx(conn, fake_tg, cfg, bot_username=bot_username)

    raw_text = f"/done@{bot_username}"
    msg = _slash(
        raw_text,
        sender_id=99001,
        chat_id=fake_tg.chat_id,
        message_id=44,
        topic_id=topic_id,
        cmd_length=len(raw_text),
    )
    await rt_dispatcher.dispatch(msg, ctx)

    events = _read_audit_events(log_dir)
    rejected = [e for e in events if e.get("event_type") == "slash_command_rejected"]
    assert len(rejected) == 1
    assert rejected[0]["reason"] == "unknown_command"
    # Parser strips @<bot_username>; canonical name is the bare command.
    assert rejected[0]["command"] == "done"


async def test_no_deprecation_warning_across_input_sequence(
    tmp_path: Path,
    isolated_xdg: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
) -> None:
    """US3: no operator-visible 'deprecated' message is ever produced."""
    log_dir = tmp_path / "logs"
    rt_logging.setup_logging(level="DEBUG", log_dir=log_dir, force_json=True)
    cfg = _build_cfg(fake_tg, worktree_root=tmp_path / "wt")

    topic_id = 777
    _seed_running_session(conn, topic_id=topic_id)

    ctx = _build_ctx(conn, fake_tg, cfg)

    # /cancel in main chat (rejects with main_chat_cancel, session survives).
    await rt_dispatcher.dispatch(
        _slash("/cancel", sender_id=99001, chat_id=fake_tg.chat_id, message_id=1),
        ctx,
    )
    # /done in topic.
    await rt_dispatcher.dispatch(
        _slash(
            "/done",
            sender_id=99001,
            chat_id=fake_tg.chat_id,
            message_id=2,
            topic_id=topic_id,
        ),
        ctx,
    )
    # Plain done/stop/finish in topic (each must be ignored entirely).
    for i, token in enumerate(["done", "stop", "finish"], start=3):
        await rt_dispatcher.dispatch(
            {
                "message_id": i,
                "from": {"id": 99001, "is_bot": False, "first_name": "tester"},
                "chat": {"id": fake_tg.chat_id, "type": "supergroup"},
                "date": 1746115200,
                "text": token,
                "message_thread_id": topic_id,
            },
            ctx,
        )

    # Wait one tick to ensure all async tasks settle.
    await asyncio.sleep(0)

    # No outbound message body contains "deprecated".
    assert all("deprecated" not in m.text for m in fake_tg.sent_messages)

    # No alias_deprecation_used events.
    events = _read_audit_events(log_dir)
    deprec = [e for e in events if e.get("event_type") == "alias_deprecation_used"]
    assert deprec == []
