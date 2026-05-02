"""Integration test for US2 — graceful operator stop.

Trigger a session with the real ``demo_worker`` subprocess, wait until the
first progress line lands in the topic, then post ``done`` in the bound topic
via fake Telegram. Confirm the worker honours SIGUSR1, prints a `FINAL …
operator_stop` line, exits 0, and the session row reaches `canceled` /
`error_message=operator_stop`.
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


def _message(text: str, *, sender_id: int, chat_id: int, message_id: int = 1) -> dict:
    return {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": text,
    }


async def test_operator_stop_drives_canceled_with_operator_stop_reason(
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

    # In-memory operator-stop coordination (stand-in for Runtime).
    in_flight: set[str] = set()
    pid_by_session: dict[str, int] = {}

    env = _python_path_env()
    # Plenty of iterations with a small interval — the test cancels mid-run.
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

    # Trigger.
    await rt_dispatcher.dispatch(
        _message("ZXTL-7777", sender_id=99001, chat_id=fake_tg.chat_id), ctx
    )

    # Wait until at least one PROGRESS message has been posted to the topic.
    async def _has_progress_msg() -> bool:
        return any("Status: iteration " in m.text for m in fake_tg.sent_messages)

    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        if await _has_progress_msg():
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("worker never posted a progress message")

    # Resolve the topic_id for the running session.
    row = conn.execute(
        "SELECT id, topic_id FROM sessions ORDER BY enqueued_at DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    sid, topic_id = row

    # Now post `done` inside the bound topic.
    stop_msg = {
        **_message("done", sender_id=99001, chat_id=fake_tg.chat_id, message_id=42),
        "message_thread_id": topic_id,
    }
    await rt_dispatcher.dispatch(stop_msg, ctx)

    # Wait for terminal state.
    deadline = asyncio.get_running_loop().time() + 10.0
    while asyncio.get_running_loop().time() < deadline:
        srow = conn.execute(
            "SELECT status, error_message FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
        if srow is not None and srow[0] in ("canceled", "completed", "failed", "pr_created"):
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
    assert status == "canceled", f"got {status} (err={error_message})"
    assert error_message == "operator_stop"

    # Verify topic-bound messages: at least one PROGRESS, one FINAL ... operator_stop,
    # and the "Session stopped by operator." line.
    topic_msgs = [m.text for m in fake_tg.sent_messages if m.message_thread_id == topic_id]
    assert any("Status: iteration " in t for t in topic_msgs)
    assert any(
        "Status: final iteration " in t and "(operator_stop)" in t for t in topic_msgs
    )
    assert any("Session stopped by operator." in t for t in topic_msgs)

    # Verify session_events captured the termination.
    types = [
        r[0]
        for r in conn.execute(
            "SELECT type FROM session_events WHERE session_id = ?", (sid,)
        ).fetchall()
    ]
    assert "telegram_termination_received" in types
