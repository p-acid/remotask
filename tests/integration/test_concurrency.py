"""Integration tests for the US6 concurrency rules.

- Two distinct issue keys triggered close together each get their own topic /
  worktree / branch and complete independently.
- A second trigger for an issue already in flight is rejected with a clear
  reply naming the existing topic.
- The ``max_concurrent`` cap rejects a second concurrent issue with a cap
  message in the main chat.
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


def _python_path_env() -> dict[str, str]:
    repo_root = str(Path(__file__).resolve().parents[2])
    existing = os.environ.get("PYTHONPATH", "")
    return {"PYTHONPATH": f"{repo_root}{os.pathsep}{existing}".rstrip(os.pathsep)}


def _message(text: str, *, sender_id: int, chat_id: int, message_id: int) -> dict:
    return {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": text,
    }


def _build_cfg(
    fake_tg: FakeTelegram, *, max_concurrent: int, worktree_root: Path
) -> rt_config.ConfigSchema:
    cfg = rt_config.default_schema()
    cfg.telegram.bot_token = fake_tg.bot_token
    cfg.telegram.group_chat_id = fake_tg.chat_id
    cfg.telegram.allowed_user_ids = [99001]
    cfg.agent.worktree_root = str(worktree_root)
    cfg.agent.max_concurrent = max_concurrent
    return cfg


async def test_same_issue_retrigger_is_rejected_with_topic_pointer(
    tmp_path: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    rt_projects.add(conn, source="jira", identifier="ZXTL", repo_path=str(repo), base_branch="main")
    cfg = _build_cfg(fake_tg, max_concurrent=2, worktree_root=tmp_path / "wt")
    client = TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())

    worker_tasks: list = []

    def spawn(coro):
        # Don't actually run the worker — capture & close. Leaves the row in
        # ``starting`` state forever, which is exactly what we want to test
        # the same-issue rejection branch.
        worker_tasks.append(coro)
        coro.close()

    argv, env = worker_command(mode="success_with_pr")
    env.update(_python_path_env())

    ctx = rt_dispatcher.DispatchContext(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=spawn,
        worker_argv=argv,
        worker_env=env,
    )

    # First trigger goes through and stays in ``starting`` (worker is closed).
    await rt_dispatcher.dispatch(
        _message("ZXTL-1234", sender_id=99001, chat_id=fake_tg.chat_id, message_id=1),
        ctx,
    )
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    first_topic_id = fake_tg.created_topics[0].message_thread_id

    # Second trigger for the SAME issue → reply in main chat naming the topic.
    await rt_dispatcher.dispatch(
        _message("ZXTL-1234", sender_id=99001, chat_id=fake_tg.chat_id, message_id=2),
        ctx,
    )
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    main_chat_msgs = [m.text for m in fake_tg.sent_messages if m.message_thread_id is None]
    assert any("already in flight" in t for t in main_chat_msgs)
    assert any(str(first_topic_id) in t for t in main_chat_msgs)

    await client.aclose()


async def test_max_concurrent_cap_rejects_extra_issue(
    tmp_path: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    rt_projects.add(conn, source="jira", identifier="ZXTL", repo_path=str(repo), base_branch="main")
    # Cap = 1 → second different issue must be rejected.
    cfg = _build_cfg(fake_tg, max_concurrent=1, worktree_root=tmp_path / "wt")
    client = TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())

    def spawn(coro):
        coro.close()

    argv, env = worker_command(mode="success_with_pr")
    env.update(_python_path_env())

    ctx = rt_dispatcher.DispatchContext(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=spawn,
        worker_argv=argv,
        worker_env=env,
    )

    await rt_dispatcher.dispatch(
        _message("ZXTL-1", sender_id=99001, chat_id=fake_tg.chat_id, message_id=1), ctx
    )
    await rt_dispatcher.dispatch(
        _message("ZXTL-2", sender_id=99001, chat_id=fake_tg.chat_id, message_id=2), ctx
    )

    # Only one session row was inserted.
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    # The cap message landed in the main chat.
    main_chat_msgs = [m.text for m in fake_tg.sent_messages if m.message_thread_id is None]
    assert any("Concurrent session limit (1) reached" in t for t in main_chat_msgs)

    await client.aclose()


async def test_two_distinct_issues_both_complete_independently(
    tmp_path: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    rt_projects.add(conn, source="jira", identifier="ZXTL", repo_path=str(repo), base_branch="main")
    cfg = _build_cfg(fake_tg, max_concurrent=2, worktree_root=tmp_path / "wt")
    client = TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())

    worker_tasks: set[asyncio.Task] = set()

    def spawn(coro):
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        worker_tasks.add(task)
        task.add_done_callback(worker_tasks.discard)

    argv, env = worker_command(
        mode="success_with_pr", pr_url="https://github.com/example/repo/pull/1"
    )
    env.update(_python_path_env())

    ctx = rt_dispatcher.DispatchContext(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=spawn,
        worker_argv=argv,
        worker_env=env,
    )

    await rt_dispatcher.dispatch(
        _message("ZXTL-100", sender_id=99001, chat_id=fake_tg.chat_id, message_id=1),
        ctx,
    )
    await rt_dispatcher.dispatch(
        _message("ZXTL-200", sender_id=99001, chat_id=fake_tg.chat_id, message_id=2),
        ctx,
    )

    # Wait for both workers to finish.
    if worker_tasks:
        await asyncio.gather(*worker_tasks)
    await client.aclose()

    rows = conn.execute(
        "SELECT issue_key, status, topic_id, worktree_path, branch FROM sessions ORDER BY enqueued_at"
    ).fetchall()
    assert len(rows) == 2
    issues = {r[0] for r in rows}
    assert issues == {"ZXTL-100", "ZXTL-200"}
    statuses = {r[1] for r in rows}
    assert statuses == {"pr_created"}
    # Distinct topic ids, worktree paths, branches.
    assert len({r[2] for r in rows}) == 2
    assert len({r[3] for r in rows}) == 2
    assert len({r[4] for r in rows}) == 2
