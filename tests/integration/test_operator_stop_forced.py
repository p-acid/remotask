"""Integration test for US3 — forced operator stop.

Spawns the demo worker with ``REMOTASK_DEMO_IGNORE_SIGUSR1=1`` so it ignores
the cooperative stop signal. Posts ``done`` in the bound topic and verifies
that after ``operator_stop_grace_seconds`` the dispatcher's grace watchdog
escalates to SIGTERM/SIGKILL and the session lands on ``canceled`` /
``error_message=operator_stop_forced`` with the right topic message.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
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

# 007: daemon's default worker argv now points at sdk_worker. These 003-era
# tests intentionally pin the demo_worker to keep exercising the placeholder
# protocol — the real sdk_worker has its own driver-level test suite.
_DEMO_WORKER_ARGV = [sys.executable, '-m', 'remotask.agent.demo_worker']


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


def _build_cfg(
    fake_tg: FakeTelegram, *, worktree_root: Path, grace_seconds: int
) -> rt_config.ConfigSchema:
    cfg = rt_config.default_schema()
    cfg.telegram.bot_token = fake_tg.bot_token
    cfg.telegram.group_chat_id = fake_tg.chat_id
    cfg.telegram.allowed_user_ids = [99001]
    cfg.agent.worktree_root = str(worktree_root)
    cfg.agent.operator_stop_grace_seconds = grace_seconds
    return cfg


def _msg(text: str, *, sender_id: int, chat_id: int, message_id: int = 1, topic_id: int | None = None) -> dict:
    out = {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": text,
    }
    if topic_id is not None:
        out["message_thread_id"] = topic_id
    return out


def _slash_cancel(
    *, sender_id: int, chat_id: int, topic_id: int, message_id: int
) -> dict:
    cmd = "/cancel"
    return {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": cmd,
        "entities": [{"type": "bot_command", "offset": 0, "length": len(cmd)}],
        "message_thread_id": topic_id,
    }


async def test_unresponsive_worker_is_force_killed(
    tmp_path: Path,
    isolated_xdg: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    rt_projects.add(conn, source="jira", identifier="ZXTL", repo_path=str(repo), base_branch="main")
    cfg = _build_cfg(fake_tg, worktree_root=tmp_path / "wt", grace_seconds=1)
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
    # Tell the worker to ignore SIGUSR1 → forces escalation path.
    env["REMOTASK_DEMO_IGNORE_SIGUSR1"] = "1"

    ctx = rt_dispatcher.DispatchContext(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=spawn_worker_task,
        worker_argv=_DEMO_WORKER_ARGV,
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
        _msg("ZXTL-8888", sender_id=99001, chat_id=fake_tg.chat_id), ctx
    )

    # Wait until first PROGRESS line lands.
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

    # 006: trigger termination via /cancel slash (plain-text `done` no longer works).
    await rt_dispatcher.dispatch(
        _slash_cancel(
            sender_id=99001, chat_id=fake_tg.chat_id, topic_id=topic_id, message_id=42
        ),
        ctx,
    )

    # Wait for terminal state — forced path needs grace (1s) + a small SIGTERM
    # window. Allow up to 15s outer.
    deadline = asyncio.get_running_loop().time() + 15.0
    while asyncio.get_running_loop().time() < deadline:
        srow = conn.execute(
            "SELECT status, error_message FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
        if srow is not None and srow[0] in ("canceled", "completed", "failed"):
            break
        await asyncio.sleep(0.1)

    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    await client.aclose()

    srow = conn.execute(
        "SELECT status, error_message FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    assert srow is not None
    status, error_message = srow
    assert status == "canceled", f"got {status} (err={error_message})"
    assert error_message == "operator_stop_forced"

    topic_msgs = [m.text for m in fake_tg.sent_messages if m.message_thread_id == topic_id]
    # 005: rename "force-stopped" → "force-canceled" for consistency with
    # /cancel + canceled DB status; lines are also prefixed with [<issue_key>].
    assert any("Session force-canceled by operator" in t for t in topic_msgs)
