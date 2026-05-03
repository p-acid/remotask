"""End-to-end test for the US1 happy path.

Exercises the entire trigger flow without spinning up a real daemon process:
listener (with FakeTelegram backend) → dispatcher → worker (fake_agent
subprocess). Verifies that posting a valid issue key results in:

- a forum topic created with the issue key as its name,
- "Session starting…" + status messages posted into the topic,
- "Draft PR opened: …" posted on completion,
- the session row reaching ``pr_created`` with a non-null ``pr_url``.
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
from remotask.daemon.listener import Listener
from remotask.daemon.listener_state import HeartbeatWriter
from remotask.telegram.client import TelegramClient
from tests.fakes.fake_agent import worker_command
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


def _build_python_path_env() -> dict[str, str]:
    repo_root = str(Path(__file__).resolve().parents[2])
    existing = os.environ.get("PYTHONPATH", "")
    return {"PYTHONPATH": f"{repo_root}{os.pathsep}{existing}".rstrip(os.pathsep)}


async def test_full_happy_path_drives_pr_created(
    tmp_path: Path,
    isolated_xdg: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    rt_projects.add(conn, source="jira", identifier="ZXTL", repo_path=str(repo), base_branch="main")

    cfg = rt_config.default_schema()
    cfg.telegram.bot_token = fake_tg.bot_token
    cfg.telegram.group_chat_id = fake_tg.chat_id
    cfg.telegram.allowed_user_ids = [99001]
    cfg.agent.worktree_root = str(tmp_path / "wt")

    client = TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())

    worker_tasks: set[asyncio.Task] = set()

    def spawn_worker_task(coro):
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        worker_tasks.add(task)
        task.add_done_callback(worker_tasks.discard)

    argv, env = worker_command(
        mode="success_with_pr", pr_url="https://github.com/example/repo/pull/777"
    )
    env.update(_build_python_path_env())

    async def on_message(msg):
        ctx = rt_dispatcher.DispatchContext(
            conn=conn,
            client=client,
            cfg=cfg,
            spawn_worker_task=spawn_worker_task,
            worker_argv=argv,
            worker_env=env,
        )
        await rt_dispatcher.dispatch(msg, ctx)

    listener = Listener(
        client=client,
        chat_id=fake_tg.chat_id,
        on_message=on_message,
        poll_timeout_seconds=1,
        backoff_max_seconds=2,
        whitelist_size=1,
        state_writer=HeartbeatWriter(path=tmp_path / "listener.state"),
    )

    fake_tg.push_text_message("ZXTL-1234", sender_id=99001)
    listener_task = asyncio.create_task(listener.run())

    # Wait for the worker to finish (status=pr_created in DB).
    deadline = asyncio.get_running_loop().time() + 10.0
    while asyncio.get_running_loop().time() < deadline:
        row = conn.execute(
            "SELECT status, pr_url, topic_id FROM sessions ORDER BY enqueued_at DESC LIMIT 1"
        ).fetchone()
        if row is not None and row[0] == "pr_created":
            break
        await asyncio.sleep(0.05)

    listener.stop()
    await asyncio.wait_for(listener_task, timeout=5.0)
    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    await client.aclose()

    row = conn.execute(
        "SELECT status, pr_url, topic_id FROM sessions ORDER BY enqueued_at DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    status, pr_url, topic_id = row
    assert status == "pr_created"
    assert pr_url == "https://github.com/example/repo/pull/777"
    assert topic_id is not None and topic_id > 0

    # Topic was created exactly once with the issue key as name.
    assert len(fake_tg.created_topics) == 1
    assert fake_tg.created_topics[0].name == "ZXTL-1234"

    # The bound topic received: "Session starting…", "Status: starting",
    # "Status: running", "Status: pr_created", "Draft PR opened: …".
    topic_msgs = [m.text for m in fake_tg.sent_messages if m.message_thread_id == topic_id]
    assert any("Session starting for ZXTL-1234" in t for t in topic_msgs)
    assert any("Status: running" in t for t in topic_msgs)
    assert any("Status: pr_created" in t for t in topic_msgs)
    assert any("Draft PR opened: https://github.com/example/repo/pull/777" in t for t in topic_msgs)
