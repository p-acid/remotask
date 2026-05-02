"""Integration test for 005 alias deprecation (US2 / FR-006/7/8/12).

Confirms:

1. ``/done`` (slash) cancels a session and emits exactly one
   ``alias_deprecation_used`` audit row + one structured-log WARNING.
2. Plain-text ``stop`` cancels a session and produces an audit row with
   ``alias_token=stop``, ``canonical=cancel``.
3. Repeated alias use on the same (alias_token, session_id) pair is silent
   (no second WARNING).
4. Cross-session, the WARNING fires again (once per fresh session).
"""
from __future__ import annotations

import asyncio
import json
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


@pytest.fixture
def audit_log_path(tmp_path: Path) -> Path:
    from remotask.core import logging as rt_logging

    log_dir = tmp_path / "audit_logs"
    rt_logging.setup_logging(level="DEBUG", log_dir=log_dir, force_json=True)
    return log_dir / "audit.log"


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


def _slash_run(args: str, *, sender_id: int, chat_id: int, message_id: int = 1) -> dict:
    cmd = "/run"
    text = f"{cmd} {args}".rstrip()
    return {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": text,
        "entities": [{"type": "bot_command", "offset": 0, "length": len(cmd)}],
    }


def _slash_done(
    *, sender_id: int, chat_id: int, topic_id: int | None, message_id: int
) -> dict:
    cmd = "/done"
    msg = {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": cmd,
        "entities": [{"type": "bot_command", "offset": 0, "length": len(cmd)}],
    }
    if topic_id is not None:
        msg["message_thread_id"] = topic_id
    return msg


def _plain_text(
    text: str, *, sender_id: int, chat_id: int, topic_id: int, message_id: int
) -> dict:
    return {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": text,
        "message_thread_id": topic_id,
    }


def _read_audit_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _build_ctx(
    *,
    conn: sqlite3.Connection,
    client: TelegramClient,
    cfg: rt_config.ConfigSchema,
    spawn_worker_task,
    in_flight: set[str],
    pid_by_session: dict[str, int],
    alias_warned: set[tuple[str, str]],
    env: dict[str, str],
) -> rt_dispatcher.DispatchContext:
    return rt_dispatcher.DispatchContext(
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
        has_alias_deprecation_warned=lambda alias, sid: (alias, sid) in alias_warned,
        record_alias_deprecation_warned=lambda alias, sid: alias_warned.add((alias, sid)),
        clear_alias_deprecation_for_session=lambda sid: alias_warned.difference_update(
            {tup for tup in list(alias_warned) if tup[1] == sid}
        ),
    )


async def _trigger_run_and_wait(ctx, fake_tg, conn, *, key: str, message_id: int = 1):
    await rt_dispatcher.dispatch(
        _slash_run(key, sender_id=99001, chat_id=fake_tg.chat_id, message_id=message_id),
        ctx,
    )
    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        if any("Status: iteration " in m.text for m in fake_tg.sent_messages):
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail(f"worker for {key} never posted progress")
    row = conn.execute(
        "SELECT id, topic_id FROM sessions WHERE issue_key = ?", (key,)
    ).fetchone()
    assert row is not None
    return row[0], row[1]


async def test_slash_done_cancels_with_warning(
    tmp_path: Path,
    isolated_xdg: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
    repo: Path,
    audit_log_path: Path,
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
    alias_warned: set[tuple[str, str]] = set()

    env = _python_path_env()
    env["REMOTASK_DEMO_ITERATIONS"] = "20"
    env["REMOTASK_DEMO_INTERVAL_SECONDS"] = "0.2"

    ctx = _build_ctx(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=spawn_worker_task,
        in_flight=in_flight,
        pid_by_session=pid_by_session,
        alias_warned=alias_warned,
        env=env,
    )

    sid, topic_id = await _trigger_run_and_wait(ctx, fake_tg, conn, key="ZXTL-8001")

    # /done in topic — twice, to test idempotency.
    await rt_dispatcher.dispatch(
        _slash_done(sender_id=99001, chat_id=fake_tg.chat_id, topic_id=topic_id, message_id=42),
        ctx,
    )
    await rt_dispatcher.dispatch(
        _slash_done(sender_id=99001, chat_id=fake_tg.chat_id, topic_id=topic_id, message_id=43),
        ctx,
    )

    # Wait for terminal.
    deadline = asyncio.get_running_loop().time() + 10.0
    while asyncio.get_running_loop().time() < deadline:
        srow = conn.execute(
            "SELECT status FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
        if srow is not None and srow[0] in ("canceled", "completed", "failed"):
            break
        await asyncio.sleep(0.05)

    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    await client.aclose()

    # Session ended canceled / operator_stop.
    srow = conn.execute(
        "SELECT status, error_message FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    assert srow == ("canceled", "operator_stop")

    # Audit log: exactly ONE alias_deprecation_used row for (/done, sid)
    # despite two /done invocations.
    events = _read_audit_lines(audit_log_path)
    deprec = [
        e for e in events
        if e.get("event_type") == "alias_deprecation_used"
        and e.get("alias_token") == "/done"
        and e.get("session_id") == sid
    ]
    assert len(deprec) == 1
    assert deprec[0]["canonical"] == "cancel"


async def test_plaintext_stop_cancels_with_warning(
    tmp_path: Path,
    isolated_xdg: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
    repo: Path,
    audit_log_path: Path,
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
    alias_warned: set[tuple[str, str]] = set()

    env = _python_path_env()
    env["REMOTASK_DEMO_ITERATIONS"] = "20"
    env["REMOTASK_DEMO_INTERVAL_SECONDS"] = "0.2"

    ctx = _build_ctx(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=spawn_worker_task,
        in_flight=in_flight,
        pid_by_session=pid_by_session,
        alias_warned=alias_warned,
        env=env,
    )

    sid, topic_id = await _trigger_run_and_wait(ctx, fake_tg, conn, key="ZXTL-8002")

    # Plain-text "stop" inside topic.
    await rt_dispatcher.dispatch(
        _plain_text("stop", sender_id=99001, chat_id=fake_tg.chat_id, topic_id=topic_id, message_id=44),
        ctx,
    )

    # Wait for terminal.
    deadline = asyncio.get_running_loop().time() + 10.0
    while asyncio.get_running_loop().time() < deadline:
        srow = conn.execute(
            "SELECT status FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
        if srow is not None and srow[0] in ("canceled", "completed", "failed"):
            break
        await asyncio.sleep(0.05)

    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    await client.aclose()

    srow = conn.execute(
        "SELECT status, error_message FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    assert srow == ("canceled", "operator_stop")

    events = _read_audit_lines(audit_log_path)
    deprec = [
        e for e in events
        if e.get("event_type") == "alias_deprecation_used"
        and e.get("alias_token") == "stop"
        and e.get("session_id") == sid
    ]
    assert len(deprec) == 1
    assert deprec[0]["canonical"] == "cancel"


async def test_alias_warning_fires_once_per_session_across_two_sessions(
    tmp_path: Path,
    isolated_xdg: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
    repo: Path,
    audit_log_path: Path,
) -> None:
    """Cross-session: the WARNING fires once per (alias, session) — twice
    total when the operator uses /done on two different sessions."""
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
    alias_warned: set[tuple[str, str]] = set()

    env = _python_path_env()
    env["REMOTASK_DEMO_ITERATIONS"] = "20"
    env["REMOTASK_DEMO_INTERVAL_SECONDS"] = "0.2"

    ctx = _build_ctx(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=spawn_worker_task,
        in_flight=in_flight,
        pid_by_session=pid_by_session,
        alias_warned=alias_warned,
        env=env,
    )

    # Session A
    sid_a, topic_a = await _trigger_run_and_wait(
        ctx, fake_tg, conn, key="ZXTL-8101", message_id=1
    )
    await rt_dispatcher.dispatch(
        _slash_done(sender_id=99001, chat_id=fake_tg.chat_id, topic_id=topic_a, message_id=46),
        ctx,
    )
    deadline = asyncio.get_running_loop().time() + 10.0
    while asyncio.get_running_loop().time() < deadline:
        s = conn.execute("SELECT status FROM sessions WHERE id = ?", (sid_a,)).fetchone()
        if s and s[0] in ("canceled", "failed", "completed"):
            break
        await asyncio.sleep(0.05)

    # Session B
    sid_b, topic_b = await _trigger_run_and_wait(
        ctx, fake_tg, conn, key="ZXTL-8102", message_id=2
    )
    await rt_dispatcher.dispatch(
        _slash_done(sender_id=99001, chat_id=fake_tg.chat_id, topic_id=topic_b, message_id=47),
        ctx,
    )
    deadline = asyncio.get_running_loop().time() + 10.0
    while asyncio.get_running_loop().time() < deadline:
        s = conn.execute("SELECT status FROM sessions WHERE id = ?", (sid_b,)).fetchone()
        if s and s[0] in ("canceled", "failed", "completed"):
            break
        await asyncio.sleep(0.05)

    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    await client.aclose()

    events = _read_audit_lines(audit_log_path)
    deprec = [
        e for e in events
        if e.get("event_type") == "alias_deprecation_used"
        and e.get("alias_token") == "/done"
    ]
    # One per session — two total.
    sids = {e["session_id"] for e in deprec}
    assert sids == {sid_a, sid_b}
    assert len(deprec) == 2
