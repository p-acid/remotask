"""Integration tests for ``/run`` slash command (004).

Covers Jira-key path (US1) and free-text fallback (US4) end-to-end with the
real demo_worker subprocess and fake_telegram.
"""
from __future__ import annotations

import asyncio
import os
import re
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


def _build_cfg(
    fake_tg: FakeTelegram, *, worktree_root: Path, default_project: str = ""
) -> rt_config.ConfigSchema:
    cfg = rt_config.default_schema()
    cfg.telegram.bot_token = fake_tg.bot_token
    cfg.telegram.group_chat_id = fake_tg.chat_id
    cfg.telegram.allowed_user_ids = [99001]
    cfg.agent.worktree_root = str(worktree_root)
    cfg.agent.default_project_jira_key = default_project
    return cfg


def _slash_run_msg(args: str, *, sender_id: int, chat_id: int, message_id: int = 1) -> dict:
    cmd = "/run"
    text = f"{cmd} {args}".rstrip()
    msg = {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": text,
        "entities": [{"type": "bot_command", "offset": 0, "length": len(cmd)}],
    }
    return msg


async def test_slash_run_with_jira_key_drives_pr_created(
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

    env = _python_path_env()
    env["REMOTASK_DEMO_ITERATIONS"] = "3"
    env["REMOTASK_DEMO_INTERVAL_SECONDS"] = "0.05"

    ctx = rt_dispatcher.DispatchContext(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=spawn_worker_task,
        worker_argv=None,
        worker_env=env,
    )

    await rt_dispatcher.dispatch(
        _slash_run_msg(
            "ZXTL-1234 also add tests", sender_id=99001, chat_id=fake_tg.chat_id
        ),
        ctx,
    )

    deadline = asyncio.get_running_loop().time() + 10.0
    while asyncio.get_running_loop().time() < deadline:
        row = conn.execute(
            "SELECT status FROM sessions ORDER BY enqueued_at DESC LIMIT 1"
        ).fetchone()
        if row is not None and row[0] in ("completed", "failed", "canceled", "pr_created"):
            break
        await asyncio.sleep(0.05)

    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    await client.aclose()

    row = conn.execute(
        "SELECT issue_key, status, trigger_text FROM sessions ORDER BY enqueued_at DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row[0] == "ZXTL-1234"
    assert row[1] == "completed"
    assert row[2] == "also add tests"

    # Verify slash_command_received audit row.
    types = [
        r[0]
        for r in conn.execute(
            "SELECT type FROM session_events WHERE session_id IN "
            "(SELECT id FROM sessions WHERE issue_key='ZXTL-1234')"
        ).fetchall()
    ]
    assert "slash_command_received" in types


async def test_slash_run_free_text_uses_default_project(
    tmp_path: Path,
    isolated_xdg: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    """US4 — /run with non-Jira-key args falls back to default project."""
    rt_projects.add(conn, "ZXTL", str(repo), base_branch="main")
    cfg = _build_cfg(fake_tg, worktree_root=tmp_path / "wt", default_project="ZXTL")
    client = TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())

    worker_tasks: set[asyncio.Task] = set()

    def spawn_worker_task(coro):
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        worker_tasks.add(task)
        task.add_done_callback(worker_tasks.discard)

    env = _python_path_env()
    env["REMOTASK_DEMO_ITERATIONS"] = "2"
    env["REMOTASK_DEMO_INTERVAL_SECONDS"] = "0.05"

    ctx = rt_dispatcher.DispatchContext(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=spawn_worker_task,
        worker_argv=None,
        worker_env=env,
    )

    await rt_dispatcher.dispatch(
        _slash_run_msg(
            "fix the cache layer please", sender_id=99001, chat_id=fake_tg.chat_id
        ),
        ctx,
    )

    deadline = asyncio.get_running_loop().time() + 10.0
    while asyncio.get_running_loop().time() < deadline:
        row = conn.execute(
            "SELECT status FROM sessions ORDER BY enqueued_at DESC LIMIT 1"
        ).fetchone()
        if row is not None and row[0] in ("completed", "failed", "canceled", "pr_created"):
            break
        await asyncio.sleep(0.05)

    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    await client.aclose()

    row = conn.execute(
        "SELECT issue_key, trigger_text, status FROM sessions ORDER BY enqueued_at DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    issue_key, trigger_text, status = row
    # Synthetic id shape: run-<YYYY-MM-DD-HH-MM>-<slug>-<6-hex>.
    # Slug is the first ≤20 chars of args (lowercased, alnum + dash).
    assert re.fullmatch(
        r"run-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-[a-z0-9-]+-[0-9a-f]{6}", issue_key
    ), issue_key
    # And the slug portion does come from the args (sanity check).
    assert "fix" in issue_key
    assert trigger_text == "fix the cache layer please"
    assert status == "completed"


async def test_slash_run_free_text_without_default_project_replies_hint(
    tmp_path: Path,
    isolated_xdg: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    rt_projects.add(conn, "ZXTL", str(repo), base_branch="main")
    cfg = _build_cfg(fake_tg, worktree_root=tmp_path / "wt", default_project="")
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
        _slash_run_msg("fix the cache", sender_id=99001, chat_id=fake_tg.chat_id),
        ctx,
    )
    await client.aclose()

    # No session created.
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    # Reply contains the setup hint.
    replies = [m for m in fake_tg.sent_messages if m.message_thread_id is None]
    assert any("default project" in m.text for m in replies)
