"""Integration test for the US2 rejection paths.

Covers the three audit-only rejection branches end-to-end (no Telegram reply,
no signal sent, audit.log entry with the right reason).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from remotask.core import config as rt_config
from remotask.core import db as core_db
from remotask.core import logging as rt_logging
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


def _read_audit_events(log_dir: Path) -> list[dict]:
    p = log_dir / "audit.log"
    if not p.exists():
        return []
    return [
        json.loads(line)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _build_cfg(fake_tg: FakeTelegram, *, worktree_root: Path) -> rt_config.ConfigSchema:
    cfg = rt_config.default_schema()
    cfg.telegram.bot_token = fake_tg.bot_token
    cfg.telegram.group_chat_id = fake_tg.chat_id
    cfg.telegram.allowed_user_ids = [99001]
    cfg.agent.worktree_root = str(worktree_root)
    return cfg


def _termination_msg(
    text: str, *, sender_id: int, chat_id: int, topic_id: int | None, message_id: int
) -> dict:
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


async def test_three_rejection_paths(
    tmp_path: Path,
    isolated_xdg: Path,
    conn: sqlite3.Connection,
    fake_tg: FakeTelegram,
    repo: Path,
) -> None:
    log_dir = tmp_path / "logs"
    rt_logging.setup_logging(level="DEBUG", log_dir=log_dir, force_json=True)
    rt_projects.add(conn, "ZXTL", str(repo), base_branch="main")
    cfg = _build_cfg(fake_tg, worktree_root=tmp_path / "wt")
    client = TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())

    in_flight: set[str] = set()
    pid_by_session: dict[str, int] = {}

    ctx = rt_dispatcher.DispatchContext(
        conn=conn,
        client=client,
        cfg=cfg,
        spawn_worker_task=lambda coro: coro.close() if hasattr(coro, "close") else None,
        worker_argv=None,
        worker_env=None,
        mark_operator_stop_in_flight=lambda sid, pid: (
            in_flight.add(sid),
            pid_by_session.__setitem__(sid, pid),
        ),
        is_operator_stop_in_flight=lambda sid: sid in in_flight,
        worker_pid_for_session=lambda sid: pid_by_session.get(sid),
    )

    # ---- 1) unauthorised termination (sender not on whitelist) ---------
    await rt_dispatcher.dispatch(
        _termination_msg(
            "done", sender_id=88888, chat_id=fake_tg.chat_id, topic_id=999, message_id=1
        ),
        ctx,
    )

    # ---- 2) no active session (whitelisted, valid grammar, dead topic) -
    await rt_dispatcher.dispatch(
        _termination_msg(
            "stop", sender_id=99001, chat_id=fake_tg.chat_id, topic_id=999, message_id=2
        ),
        ctx,
    )

    # ---- 3) main-chat termination (silently ignored — no audit row) ----
    await rt_dispatcher.dispatch(
        _termination_msg(
            "finish", sender_id=99001, chat_id=fake_tg.chat_id, topic_id=None, message_id=3
        ),
        ctx,
    )

    await client.aclose()

    # Telegram surface: nothing was posted (no reply, no topic).
    assert fake_tg.sent_messages == []
    assert fake_tg.created_topics == []

    # Audit log: cases 1 and 2 produce one rejected row each; case 3 produces nothing.
    events = _read_audit_events(log_dir)
    rejected = [e for e in events if e.get("event_type") == "telegram_termination_rejected"]
    reasons = sorted(e["reason"] for e in rejected)
    assert reasons == ["no_active_session", "unauthorized"]
