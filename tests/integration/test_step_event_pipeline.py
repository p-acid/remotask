"""Integration coverage for the 007 STEP/EVENT pipeline.

Drives ``run_worker`` against ``fake_agent`` in ``step_then_pr`` mode (which
emits exactly one STEP, one EVENT agent.tool_use, one PR_URL=, and one
FINAL line). Asserts:

1. STEP body lands on the bound topic with the ``[<issue_key>]`` prefix
   (005 chokepoint preserved through the new code path).
2. EVENT agent.tool_use becomes a ``session_events`` row with the parsed
   JSON payload — schema V0001 unchanged, only the ``type`` column gains
   a new value.
3. The 003 PR_URL → ``pr_created`` transition still fires unchanged when
   STEP/EVENT lines precede it.
"""
from __future__ import annotations

import json
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
    session_id = sessions.new_session_id()
    sessions.insert_enqueued_session(
        conn,
        session_id=session_id,
        issue_key=issue_key,
        trigger_user=99007,
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
    repo_root = str(Path(__file__).resolve().parents[2])
    existing = os.environ.get("PYTHONPATH", "")
    return {"PYTHONPATH": f"{repo_root}{os.pathsep}{existing}".rstrip(os.pathsep)}


async def test_step_then_pr_emits_topic_step_and_audit_event(
    tmp_path: Path,
    conn: sqlite3.Connection,
    client: TelegramClient,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    topic_id = 700
    session_id = _seed_starting_session(conn, issue_key="ZXTL-700", topic_id=topic_id)

    argv, env = worker_command(
        mode="step_then_pr", pr_url="https://github.com/example/repo/pull/700"
    )
    env["FAKE_AGENT_STEP_BODY"] = "Bash: gh pr create --draft"
    env.update(_build_python_path_env())

    spec = rt_worker.WorkerSpec(
        session_id=session_id,
        issue_key="ZXTL-700",
        repo_path=repo,
        base_branch="main",
        worktree_root=tmp_path / "wt",
        argv=argv,
        extra_env=env,
    )

    outcome = await rt_worker.run_worker(
        spec,
        conn=conn,
        client=client,
        chat_id=fake_tg.chat_id,
        topic_id=topic_id,
    )

    assert outcome.exit_code == 0
    assert outcome.pr_url == "https://github.com/example/repo/pull/700"
    assert outcome.final_marker == (1, "natural")

    # 1. STEP body landed on the topic with [<key>] prefix (005 chokepoint).
    topic_msgs = [
        m.text for m in fake_tg.sent_messages if m.message_thread_id == topic_id
    ]
    step_lines = [t for t in topic_msgs if "Bash: gh pr create --draft" in t]
    assert len(step_lines) == 1, f"expected exactly 1 STEP line on topic, got {step_lines!r}"
    assert step_lines[0].startswith("[ZXTL-700]"), step_lines[0]

    # 2. EVENT agent.tool_use → session_events row with parsed payload.
    rows = conn.execute(
        "SELECT type, payload FROM session_events "
        "WHERE session_id = ? AND type = 'agent.tool_use'",
        (session_id,),
    ).fetchall()
    assert len(rows) == 1, f"expected exactly 1 agent.tool_use row, got {rows!r}"
    payload = json.loads(rows[0][1])
    assert payload == {"tool": "Bash", "iter": 1}

    # 3. 003 PR-flow unchanged — running → pr_created → topic gets the URL.
    row = conn.execute(
        "SELECT status, pr_url FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    assert row[0] == "pr_created"
    assert row[1] == "https://github.com/example/repo/pull/700"
    assert any(
        "Draft PR opened: https://github.com/example/repo/pull/700" in t
        for t in topic_msgs
    )


async def test_unknown_event_type_is_dropped(
    tmp_path: Path,
    conn: sqlite3.Connection,
    client: TelegramClient,
    fake_tg: FakeTelegram,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An EVENT line with an unknown type must be dropped — not stored.

    We simulate this by spawning a fake worker that emits a non-whitelisted
    event type, then asserting nothing was inserted into ``session_events``
    for that type.
    """
    topic_id = 701
    session_id = _seed_starting_session(conn, issue_key="ZXTL-701", topic_id=topic_id)

    # Use the existing success_with_pr path but inject a custom unknown event
    # by writing a tiny inline script. Fastest reliable way: monkeypatch the
    # fake_agent module to emit an extra line. Since fake_agent runs in a
    # subprocess, we instead add a one-off mode through env var passthrough.
    # Simpler approach: run the success_with_pr mode but prepend a stdin pipe.
    # The cleanest route is to write a temp Python script.
    import sys as _sys

    inline = tmp_path / "inline_worker.py"
    inline.write_text(
        "import sys\n"
        'sys.stdout.write("EVENT agent.unknown_kind {\\"foo\\": 1}\\n")\n'
        'sys.stdout.write("PR_URL=https://example.com/pr/1\\n")\n'
        'sys.stdout.write("FINAL 1 natural\\n")\n'
        "sys.stdout.flush()\n"
        "raise SystemExit(0)\n"
    )

    spec = rt_worker.WorkerSpec(
        session_id=session_id,
        issue_key="ZXTL-701",
        repo_path=repo,
        base_branch="main",
        worktree_root=tmp_path / "wt",
        argv=[_sys.executable, str(inline)],
        extra_env=_build_python_path_env(),
    )

    await rt_worker.run_worker(
        spec,
        conn=conn,
        client=client,
        chat_id=fake_tg.chat_id,
        topic_id=topic_id,
    )

    rows = conn.execute(
        "SELECT type FROM session_events WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    types = [r[0] for r in rows]
    assert "agent.unknown_kind" not in types
