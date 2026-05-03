"""Integration test for ``[KEY]`` prefix on session-bound messages (005 / US3).

Asserts that:

- Every progress / `Status: …` / final / canceled message posted to the topic
  carries the ``[<issue_key>] `` prefix.
- The ``Session starting for <key>. …`` template does NOT carry the prefix
  (already names the key — FR-010).

Triggers a session, lets it complete naturally, captures every outbound
message via the FakeTelegram, then partitions them.
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


def _build_cfg(fake_tg: FakeTelegram, *, worktree_root: Path) -> rt_config.ConfigSchema:
    cfg = rt_config.default_schema()
    cfg.telegram.bot_token = fake_tg.bot_token
    cfg.telegram.group_chat_id = fake_tg.chat_id
    cfg.telegram.allowed_user_ids = [99001]
    cfg.agent.worktree_root = str(worktree_root)
    return cfg


def _trigger(text: str, *, sender_id: int, chat_id: int) -> dict:
    return {
        "message_id": 1,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": text,
    }


async def test_progress_and_final_carry_key_prefix(
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
    # Short, deterministic workload — natural completion in ~1s.
    env["REMOTASK_DEMO_ITERATIONS"] = "3"
    env["REMOTASK_DEMO_INTERVAL_SECONDS"] = "0.1"

    ctx = rt_dispatcher.DispatchContext(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=spawn_worker_task,
        worker_argv=_DEMO_WORKER_ARGV,
        worker_env=env,
    )

    issue_key = "ZXTL-9001"
    await rt_dispatcher.dispatch(_trigger(issue_key, sender_id=99001, chat_id=fake_tg.chat_id), ctx)

    # Wait up to 30s for the session to reach a terminal state.
    deadline = asyncio.get_running_loop().time() + 30.0
    sid = None
    while asyncio.get_running_loop().time() < deadline:
        row = conn.execute(
            "SELECT id, status FROM sessions WHERE issue_key = ?", (issue_key,)
        ).fetchone()
        if row is not None:
            sid, status = row
            if status in ("completed", "canceled", "failed", "pr_created"):
                break
        await asyncio.sleep(0.1)

    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    await client.aclose()

    assert sid is not None

    # Inspect every outbound message into the bound topic.
    row = conn.execute("SELECT topic_id FROM sessions WHERE id = ?", (sid,)).fetchone()
    topic_id = row[0]
    assert topic_id is not None
    topic_messages = [
        m for m in fake_tg.sent_messages if m.message_thread_id == topic_id
    ]
    assert len(topic_messages) >= 3  # Session starting + at least 1 status + completion

    prefix = f"[{issue_key}] "

    # FR-010: "Session starting for ZXTL-9001. ..." MUST NOT be prefixed.
    starting_lines = [m for m in topic_messages if "Session starting" in m.text]
    assert len(starting_lines) == 1
    assert not starting_lines[0].text.startswith(prefix), (
        f"FR-010 violated: 'Session starting' template was prefixed: "
        f"{starting_lines[0].text!r}"
    )

    # Every Status: line MUST be prefixed.
    status_lines = [m for m in topic_messages if "Status:" in m.text]
    assert len(status_lines) >= 2  # at least starting + one of running/completed
    for m in status_lines:
        assert m.text.startswith(prefix), (
            f"FR-009 violated: status line missing [KEY] prefix: {m.text!r}"
        )

    # If a final-iteration line was emitted, it must be prefixed.
    final_lines = [m for m in topic_messages if "final iteration" in m.text]
    for m in final_lines:
        assert m.text.startswith(prefix), (
            f"FR-009 violated: FINAL line missing [KEY] prefix: {m.text!r}"
        )
