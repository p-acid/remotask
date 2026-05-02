"""Integration test for US1 — natural-completion happy path.

Drives the full pipeline (dispatcher → worker → topic) using ``fake_telegram``
plus the **real** ``remotask.agent.demo_worker`` subprocess, with shortened
iterations / interval via env vars.
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
    repo_root = str(Path(__file__).resolve().parents[2])
    src_root = str(Path(__file__).resolve().parents[2] / "src")
    existing = os.environ.get("PYTHONPATH", "")
    paths_combined = os.pathsep.join([src_root, repo_root, existing]).rstrip(os.pathsep)
    return {"PYTHONPATH": paths_combined}


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


async def test_full_natural_completion_flow(
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

    # Override demo worker iteration parameters via env vars.
    env = _python_path_env()
    env["REMOTASK_DEMO_ITERATIONS"] = "3"
    env["REMOTASK_DEMO_INTERVAL_SECONDS"] = "0.05"

    ctx = rt_dispatcher.DispatchContext(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=spawn_worker_task,
        worker_argv=None,  # use the default — i.e., remotask.agent.demo_worker
        worker_env=env,
    )

    # Trigger.
    await rt_dispatcher.dispatch(
        _message("ZXTL-9001", sender_id=99001, chat_id=fake_tg.chat_id), ctx
    )

    # Wait for the worker to reach a terminal state.
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

    # Inspect the session row.
    row = conn.execute(
        "SELECT status, error_message, topic_id FROM sessions ORDER BY enqueued_at DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    status, error_message, topic_id = row
    assert status == "completed", f"expected completed, got {status} (err={error_message})"
    assert topic_id is not None and topic_id > 0

    # Inspect the bound topic — should have:
    #   "Session starting…", "Status: starting", "Status: running",
    #   3 × "Status: iteration i/3 @ <ts>", "Status: final iteration 3 (natural)",
    #   "Status: completed".
    topic_msgs = [m.text for m in fake_tg.sent_messages if m.message_thread_id == topic_id]
    progress_msgs = [t for t in topic_msgs if "Status: iteration " in t]
    assert len(progress_msgs) == 3, f"expected 3 progress msgs, got {progress_msgs}"
    assert any("Session starting for ZXTL-9001" in t for t in topic_msgs)
    assert any("Status: final iteration 3 (natural)" in t for t in topic_msgs)
    assert any("Status: completed" in t for t in topic_msgs)
