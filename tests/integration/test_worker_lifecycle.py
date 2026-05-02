"""Integration tests for ``remotask.daemon.worker.run_worker``.

Spawns the ``tests.fakes.fake_agent`` script as a real subprocess so the test
exercises ``asyncio.create_subprocess_exec``, the worktree creation path, the
stdout PR_URL parser, and every state transition the happy-path worker drives.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from remotask.core import db as core_db
from remotask.core import paths as rt_paths
from remotask.daemon import sessions
from remotask.daemon import worker as rt_worker
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
def client(fake_tg: FakeTelegram) -> TelegramClient:
    return TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path / "repo_parent")


def _seed_starting_session(
    conn: sqlite3.Connection, *, issue_key: str, topic_id: int
) -> str:
    """Insert a session row in ``starting`` state with a topic already bound.

    This matches the post-dispatcher / pre-worker state expected by
    ``run_worker``.
    """
    session_id = sessions.new_session_id()
    sessions.insert_enqueued_session(
        conn,
        session_id=session_id,
        issue_key=issue_key,
        trigger_user=99001,
        trigger_text=issue_key,
    )
    sessions.acquire_issue_lock(conn, issue_key=issue_key, session_id=session_id)
    conn.commit()
    sessions.set_topic_id(conn, session_id=session_id, topic_id=topic_id)
    sessions.transition(
        conn, session_id=session_id, from_status="enqueued", to_status="starting"
    )
    return session_id


def _build_python_path_env() -> dict[str, str]:
    """Ensure the spawned fake_agent can import ``tests.fakes.fake_agent``."""
    repo_root = str(Path(__file__).resolve().parents[2])
    existing = os.environ.get("PYTHONPATH", "")
    return {"PYTHONPATH": f"{repo_root}{os.pathsep}{existing}".rstrip(os.pathsep)}


async def test_success_with_pr_drives_pr_created_transition(
    tmp_path: Path,
    conn: sqlite3.Connection,
    client: TelegramClient,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    topic_id = 100
    session_id = _seed_starting_session(conn, issue_key="ZXTL-7", topic_id=topic_id)

    argv, env = worker_command(
        mode="success_with_pr", pr_url="https://github.com/example/repo/pull/9"
    )
    env.update(_build_python_path_env())

    spec = rt_worker.WorkerSpec(
        session_id=session_id,
        issue_key="ZXTL-7",
        repo_path=repo,
        base_branch="main",
        worktree_root=tmp_path / "wt",
        argv=argv,
        extra_env=env,
    )

    outcome = await rt_worker.run_worker(
        spec, conn=conn, client=client, chat_id=fake_tg.chat_id, topic_id=topic_id
    )

    assert outcome.exit_code == 0
    assert outcome.pr_url == "https://github.com/example/repo/pull/9"

    row = conn.execute(
        "SELECT status, worktree_path, branch, pr_url FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    assert row[0] == "pr_created"
    assert row[1].endswith("/wt/ZXTL-7")
    assert row[2] == "agent/ZXTL-7"
    assert row[3] == "https://github.com/example/repo/pull/9"

    # Topic received: Status: running, Status: pr_created, "Draft PR opened: ..."
    topic_msgs = [m.text for m in fake_tg.sent_messages if m.message_thread_id == topic_id]
    assert any("Status: running" in t for t in topic_msgs)
    assert any("Status: pr_created" in t for t in topic_msgs)
    assert any("Draft PR opened: https://github.com/example/repo/pull/9" in t for t in topic_msgs)

    # Lock released.
    locks = conn.execute(
        "SELECT * FROM locks WHERE resource = ?", ("issue:ZXTL-7",)
    ).fetchall()
    assert locks == []


async def test_success_no_pr_drives_completed_transition(
    tmp_path: Path,
    conn: sqlite3.Connection,
    client: TelegramClient,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    topic_id = 200
    session_id = _seed_starting_session(conn, issue_key="ZXTL-8", topic_id=topic_id)

    argv, env = worker_command(mode="success_no_pr")
    env.update(_build_python_path_env())

    spec = rt_worker.WorkerSpec(
        session_id=session_id,
        issue_key="ZXTL-8",
        repo_path=repo,
        base_branch="main",
        worktree_root=tmp_path / "wt",
        argv=argv,
        extra_env=env,
    )

    outcome = await rt_worker.run_worker(
        spec, conn=conn, client=client, chat_id=fake_tg.chat_id, topic_id=topic_id
    )

    assert outcome.exit_code == 0
    assert outcome.pr_url is None

    row = conn.execute(
        "SELECT status, pr_url FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    assert row[0] == "completed"
    assert row[1] is None


async def test_exit_nonzero_drives_failed_transition_with_reason(
    tmp_path: Path,
    conn: sqlite3.Connection,
    client: TelegramClient,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    topic_id = 400
    session_id = _seed_starting_session(conn, issue_key="ZXTL-10", topic_id=topic_id)

    argv, env = worker_command(mode="exit_nonzero", error_message="kaboom")
    env.update(_build_python_path_env())

    spec = rt_worker.WorkerSpec(
        session_id=session_id,
        issue_key="ZXTL-10",
        repo_path=repo,
        base_branch="main",
        worktree_root=tmp_path / "wt",
        argv=argv,
        extra_env=env,
    )

    outcome = await rt_worker.run_worker(
        spec, conn=conn, client=client, chat_id=fake_tg.chat_id, topic_id=topic_id
    )

    assert outcome.exit_code != 0
    assert outcome.timed_out is False

    row = conn.execute(
        "SELECT status, error_message FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    assert row[0] == "failed"
    assert "kaboom" in (row[1] or "")

    topic_msgs = [m.text for m in fake_tg.sent_messages if m.message_thread_id == topic_id]
    # 005: session-bound failure messages are prefixed with [<issue_key>].
    assert any("Session failed:" in t for t in topic_msgs)
    # ``kaboom`` should appear in the failure message (last stderr line).
    assert any("kaboom" in t for t in topic_msgs)


async def test_state_transitions_recorded_in_session_events(
    tmp_path: Path,
    conn: sqlite3.Connection,
    client: TelegramClient,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    topic_id = 300
    session_id = _seed_starting_session(conn, issue_key="ZXTL-9", topic_id=topic_id)

    argv, env = worker_command(mode="success_with_pr")
    env.update(_build_python_path_env())

    spec = rt_worker.WorkerSpec(
        session_id=session_id,
        issue_key="ZXTL-9",
        repo_path=repo,
        base_branch="main",
        worktree_root=tmp_path / "wt",
        argv=argv,
        extra_env=env,
    )

    await rt_worker.run_worker(
        spec, conn=conn, client=client, chat_id=fake_tg.chat_id, topic_id=topic_id
    )

    events = conn.execute(
        "SELECT type FROM session_events WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    type_seq = [e[0] for e in events]
    # We expect at least: state_transition (enqueued→starting from seed),
    # state_transition (starting→running), worker_spawn, worker_exit,
    # state_transition (running→pr_created).
    assert type_seq.count("state_transition") >= 3
    assert "worker_spawn" in type_seq
    assert "worker_exit" in type_seq
