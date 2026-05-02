"""Integration test for 006 / US2: plain-text done/stop/finish are non-control text.

Confirms that bare ``done``, ``stop``, or ``finish`` (without the leading
slash) posted in a session topic is treated as ordinary chat — no termination,
no warning, no audit event tied to the token.
"""
from __future__ import annotations

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


def _plain(
    text: str,
    *,
    sender_id: int,
    chat_id: int,
    message_id: int,
    topic_id: int | None = None,
) -> dict:
    msg: dict = {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": text,
    }
    if topic_id is not None:
        msg["message_thread_id"] = topic_id
    return msg


def _build_ctx(
    conn: sqlite3.Connection, fake_tg: FakeTelegram, cfg: rt_config.ConfigSchema
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


@pytest.mark.parametrize("token", ["done", "stop", "finish"])
async def test_plain_token_in_topic_does_nothing(
    token: str,
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

    msgs_before = list(fake_tg.sent_messages)
    events_count_before = conn.execute(
        "SELECT COUNT(*) FROM session_events"
    ).fetchone()[0]
    audit_before = _read_audit_events(log_dir)

    msg = _plain(
        token,
        sender_id=99001,
        chat_id=fake_tg.chat_id,
        message_id=42,
        topic_id=topic_id,
    )
    await rt_dispatcher.dispatch(msg, ctx)

    # Session unchanged.
    row = conn.execute("SELECT status FROM sessions WHERE id = ?", (sid,)).fetchone()
    assert row[0] == "running"

    # No new outbound messages.
    assert fake_tg.sent_messages == msgs_before

    # No new session_events rows.
    events_count_after = conn.execute(
        "SELECT COUNT(*) FROM session_events"
    ).fetchone()[0]
    assert events_count_after == events_count_before

    # No new alias_deprecation_used or termination_received audit lines.
    audit_after = _read_audit_events(log_dir)
    new_audit = audit_after[len(audit_before):]
    assert all(
        e.get("event_type") not in (
            "alias_deprecation_used",
            "telegram_termination_received",
            "telegram_termination_rejected",
        )
        for e in new_audit
    ), f"unexpected audit events: {new_audit}"


async def test_plain_done_in_main_chat_already_non_control(
    tmp_path: Path,
    isolated_xdg: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
) -> None:
    """Regression guard: plain `done` outside any topic was already non-control
    in 005; 006 must not regress this."""
    log_dir = tmp_path / "logs"
    rt_logging.setup_logging(level="DEBUG", log_dir=log_dir, force_json=True)
    cfg = _build_cfg(fake_tg, worktree_root=tmp_path / "wt")

    ctx = _build_ctx(conn, fake_tg, cfg)

    audit_before = _read_audit_events(log_dir)
    msg = _plain("done", sender_id=99001, chat_id=fake_tg.chat_id, message_id=1)
    await rt_dispatcher.dispatch(msg, ctx)

    assert fake_tg.sent_messages == []
    audit_after = _read_audit_events(log_dir)
    new_audit = audit_after[len(audit_before):]
    assert new_audit == []
