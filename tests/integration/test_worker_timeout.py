"""Integration test for ``worker.run_worker`` per-session timeout watchdog.

The fake_agent in ``hang`` mode sleeps forever; we set a tiny
``timeout_seconds`` so the watchdog SIGTERMs the process group and the
session transitions to ``failed`` with reason ``timeout``.
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


def _seed_starting_session(conn: sqlite3.Connection, *, issue_key: str, topic_id: int) -> str:
    sid = sessions.new_session_id()
    sessions.insert_enqueued_session(
        conn, session_id=sid, issue_key=issue_key, trigger_user=99001, trigger_text=issue_key
    )
    sessions.acquire_issue_lock(conn, issue_key=issue_key, session_id=sid)
    conn.commit()
    sessions.set_topic_id(conn, session_id=sid, topic_id=topic_id)
    sessions.transition(conn, session_id=sid, from_status="enqueued", to_status="starting")
    return sid


def _python_path_env() -> dict[str, str]:
    repo_root = str(Path(__file__).resolve().parents[2])
    existing = os.environ.get("PYTHONPATH", "")
    return {"PYTHONPATH": f"{repo_root}{os.pathsep}{existing}".rstrip(os.pathsep)}


async def test_hung_worker_is_killed_after_timeout(
    tmp_path: Path,
    conn: sqlite3.Connection,
    client: TelegramClient,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    topic_id = 555
    session_id = _seed_starting_session(conn, issue_key="ZXTL-99", topic_id=topic_id)

    argv, env = worker_command(mode="hang")
    env.update(_python_path_env())

    spec = rt_worker.WorkerSpec(
        session_id=session_id,
        issue_key="ZXTL-99",
        repo_path=repo,
        base_branch="main",
        worktree_root=tmp_path / "wt",
        argv=argv,
        extra_env=env,
        # 1-second timeout — the watchdog should kick in well within the
        # surrounding test timeout.
        timeout_seconds=1.0,
    )

    outcome = await rt_worker.run_worker(
        spec, conn=conn, client=client, chat_id=fake_tg.chat_id, topic_id=topic_id
    )

    assert outcome.timed_out is True
    assert outcome.exit_code != 0

    row = conn.execute(
        "SELECT status, error_message FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    assert row[0] == "failed"
    assert "timeout" in (row[1] or "")

    topic_msgs = [m.text for m in fake_tg.sent_messages if m.message_thread_id == topic_id]
    assert any("Session terminated: timeout" in t for t in topic_msgs)

    # Audit trail: worker_timeout + worker_exit events are recorded.
    types = [
        r[0]
        for r in conn.execute(
            "SELECT type FROM session_events WHERE session_id = ?", (session_id,)
        ).fetchall()
    ]
    assert "worker_timeout" in types
    assert "worker_exit" in types
