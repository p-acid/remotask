"""Backwards-compat smoke for 002 / 003 plain-text triggers after 004 lands.

In the same dispatcher invocation, mix:

- 002 plain-text Jira-key trigger
- 004 /run with Jira-key
- 003 plain-text `done` inside a topic
- 004 /done inside a topic

All four must reach a session terminal state correctly. Confirms SC-005.
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
    cfg.agent.max_concurrent = 5  # multiple parallel sessions
    return cfg


def _plain_text(text: str, *, sender_id: int, chat_id: int, message_id: int, topic_id: int | None = None) -> dict:
    msg = {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": text,
    }
    if topic_id is not None:
        msg["message_thread_id"] = topic_id
    return msg


def _slash(text: str, *, sender_id: int, chat_id: int, message_id: int, topic_id: int | None = None) -> dict:
    cmd = text.split(" ", 1)[0]
    msg = {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": text,
        "entities": [{"type": "bot_command", "offset": 0, "length": len(cmd)}],
    }
    if topic_id is not None:
        msg["message_thread_id"] = topic_id
    return msg


async def test_plain_text_and_slash_paths_coexist(
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
    env["REMOTASK_DEMO_ITERATIONS"] = "10"
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

    # 1. Plain-text Jira-key trigger (002).
    await rt_dispatcher.dispatch(
        _plain_text("ZXTL-1001", sender_id=99001, chat_id=fake_tg.chat_id, message_id=1),
        ctx,
    )
    # 2. Slash /run trigger (004).
    await rt_dispatcher.dispatch(
        _slash("/run ZXTL-1002", sender_id=99001, chat_id=fake_tg.chat_id, message_id=2),
        ctx,
    )

    # Wait for both sessions to enter running and post their first PROGRESS.
    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        progress_count = sum(
            1 for m in fake_tg.sent_messages if "Status: iteration " in m.text
        )
        if progress_count >= 2:
            break
        await asyncio.sleep(0.05)

    rows = conn.execute(
        "SELECT id, issue_key, topic_id FROM sessions ORDER BY enqueued_at"
    ).fetchall()
    assert len(rows) == 2
    s1_id, s1_key, s1_topic = rows[0]
    s2_id, s2_key, s2_topic = rows[1]
    assert s1_key == "ZXTL-1001"
    assert s2_key == "ZXTL-1002"

    # 3. Plain-text `done` inside session 1's topic (003).
    await rt_dispatcher.dispatch(
        _plain_text(
            "done",
            sender_id=99001,
            chat_id=fake_tg.chat_id,
            message_id=10,
            topic_id=s1_topic,
        ),
        ctx,
    )
    # 4. Slash /done inside session 2's topic (004).
    await rt_dispatcher.dispatch(
        _slash(
            "/done",
            sender_id=99001,
            chat_id=fake_tg.chat_id,
            message_id=11,
            topic_id=s2_topic,
        ),
        ctx,
    )

    # Wait for both sessions to reach canceled.
    deadline = asyncio.get_running_loop().time() + 10.0
    while asyncio.get_running_loop().time() < deadline:
        statuses = [
            r[0]
            for r in conn.execute(
                "SELECT status FROM sessions WHERE id IN (?, ?)", (s1_id, s2_id)
            ).fetchall()
        ]
        if all(s in ("canceled", "completed", "failed") for s in statuses):
            break
        await asyncio.sleep(0.05)

    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    await client.aclose()

    final = dict(
        conn.execute(
            "SELECT id, error_message FROM sessions WHERE id IN (?, ?)",
            (s1_id, s2_id),
        ).fetchall()
    )
    assert final[s1_id] == "operator_stop"
    assert final[s2_id] == "operator_stop"
