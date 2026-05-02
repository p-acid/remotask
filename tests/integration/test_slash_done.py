"""Integration test for ``/done`` slash command (004 / US2).

Confirms the slash form is equivalent to 003's plain-text ``done``.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path

import pytest

from remotask.core import config as rt_config
from remotask.core import db as core_db
from remotask.core import paths as rt_paths
from remotask.core import projects as rt_projects
from remotask.daemon import dispatcher as rt_dispatcher
from remotask.telegram.client import TelegramClient
from tests.fakes.fake_telegram import FakeTelegram
from tests.fakes.git_repo import make_repo


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


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path / "repo_parent")


def _python_path_env() -> dict[str, str]:
    src_root = str(Path(__file__).resolve().parents[2] / "src")
    repo_root = str(Path(__file__).resolve().parents[2])
    existing = os.environ.get("PYTHONPATH", "")
    return {
        "PYTHONPATH": os.pathsep.join([src_root, repo_root, existing]).rstrip(os.pathsep)
    }


def _build_cfg(fake_tg: FakeTelegram, *, worktree_root: Path) -> rt_config.ConfigSchema:
    cfg = rt_config.default_schema()
    cfg.telegram.bot_token = fake_tg.bot_token
    cfg.telegram.group_chat_id = fake_tg.chat_id
    cfg.telegram.allowed_user_ids = [99001]
    cfg.agent.worktree_root = str(worktree_root)
    return cfg


def _slash_run(args: str, *, sender_id: int, chat_id: int, message_id: int = 1) -> dict:
    cmd = "/run"
    text = f"{cmd} {args}".rstrip()
    return {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": text,
        "entities": [{"type": "bot_command", "offset": 0, "length": len(cmd)}],
    }


def _slash_done(
    *, sender_id: int, chat_id: int, topic_id: int | None, message_id: int
) -> dict:
    cmd = "/done"
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


async def test_slash_done_in_topic_drives_canceled(
    tmp_path: Path,
    isolated_xdg: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    rt_projects.add(conn, "ZXTL", str(repo), base_branch="main")
    cfg = _build_cfg(fake_tg, worktree_root=tmp_path / "wt")
    client = TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())

    worker_tasks: set[asyncio.Task] = set()

    def spawn_worker_task(coro):
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        worker_tasks.add(task)
        task.add_done_callback(worker_tasks.discard)

    in_flight: set[str] = set()
    pid_by_session: dict[str, int] = {}

    env = _python_path_env()
    env["REMOTASK_DEMO_ITERATIONS"] = "20"
    env["REMOTASK_DEMO_INTERVAL_SECONDS"] = "0.2"

    ctx = rt_dispatcher.DispatchContext(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=spawn_worker_task,
        worker_argv=None,
        worker_env=env,
        mark_operator_stop_in_flight=lambda sid, pid: (
            in_flight.add(sid),
            pid_by_session.__setitem__(sid, pid),
        ),
        is_operator_stop_in_flight=lambda sid: sid in in_flight,
        worker_pid_for_session=lambda sid: pid_by_session.get(sid),
        register_worker_pid=lambda sid, pid: pid_by_session.__setitem__(sid, pid),
    )

    # /run to start a session.
    await rt_dispatcher.dispatch(
        _slash_run("ZXTL-7777", sender_id=99001, chat_id=fake_tg.chat_id), ctx
    )

    # Wait for first PROGRESS line.
    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        if any("Status: iteration " in m.text for m in fake_tg.sent_messages):
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("worker never posted a progress message")

    row = conn.execute(
        "SELECT id, topic_id FROM sessions ORDER BY enqueued_at DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    sid, topic_id = row

    # /done in the bound topic.
    await rt_dispatcher.dispatch(
        _slash_done(
            sender_id=99001,
            chat_id=fake_tg.chat_id,
            topic_id=topic_id,
            message_id=42,
        ),
        ctx,
    )

    deadline = asyncio.get_running_loop().time() + 10.0
    while asyncio.get_running_loop().time() < deadline:
        srow = conn.execute(
            "SELECT status, error_message FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
        if srow is not None and srow[0] in ("canceled", "completed", "failed"):
            break
        await asyncio.sleep(0.05)

    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    await client.aclose()

    srow = conn.execute(
        "SELECT status, error_message FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    assert srow is not None
    status, error_message = srow
    assert status == "canceled"
    assert error_message == "operator_stop"

    # Audit shows BOTH the slash_command_received AND the 003 termination event.
    types = [
        r[0]
        for r in conn.execute(
            "SELECT type FROM session_events WHERE session_id = ?", (sid,)
        ).fetchall()
    ]
    assert "slash_command_received" in types
    assert "telegram_termination_received" in types


async def test_slash_done_in_main_chat_is_silently_rejected(
    tmp_path: Path,
    isolated_xdg: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    """`/done` in main chat → no signal, audit-log only."""
    from remotask.core import logging as rt_logging

    log_dir = tmp_path / "logs"
    rt_logging.setup_logging(level="DEBUG", log_dir=log_dir, force_json=True)
    cfg = _build_cfg(fake_tg, worktree_root=tmp_path / "wt")
    client = TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())

    ctx = rt_dispatcher.DispatchContext(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=lambda coro: coro.close() if hasattr(coro, "close") else None,
        worker_argv=None,
        worker_env=None,
    )

    await rt_dispatcher.dispatch(
        _slash_done(
            sender_id=99001,
            chat_id=fake_tg.chat_id,
            topic_id=None,  # main chat
            message_id=10,
        ),
        ctx,
    )
    await client.aclose()

    # No reply, no signal, no session.
    assert fake_tg.sent_messages == []

    import json

    events = [
        json.loads(line)
        for line in (log_dir / "audit.log").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rejections = [
        e for e in events
        if e.get("event_type") == "slash_command_rejected"
        and e.get("reason") == "main_chat_done"
    ]
    assert len(rejections) == 1
