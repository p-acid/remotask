"""AT1 + AT2 + AT4 — dispatcher consults the active adapter.

The dispatcher's two call sites (plain-text + slash) delegate to the
``DispatchContext.adapter`` injected by the runtime.
"""
from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from remotask.core import config as rt_config
from remotask.core import db as core_db
from remotask.core import projects as rt_projects
from remotask.daemon import dispatcher as rt_dispatcher
from remotask.task_sources.github_issue import GitHubIssueAdapter
from remotask.task_sources.jira import JiraAdapter
from remotask.telegram.client import TelegramClient
from tests.fakes.fake_telegram import FakeTelegram
from tests.fakes.git_repo import make_repo


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


@pytest.fixture
def fake_tg() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def client(fake_tg: FakeTelegram) -> TelegramClient:
    return TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())


def _message(
    text: str, *, sender_id: int, chat_id: int, message_id: int = 1
) -> dict:
    return {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": text,
    }


class TestDispatcherJiraMode:
    """AT1 — Jira retrofit: 002's accept-path test passes after retrofit."""

    def test_plain_text_jira_key_accepted(
        self,
        tmp_path: Path,
        repo_path: Path,
        fake_tg: FakeTelegram,
        client: TelegramClient,
    ) -> None:
        conn = core_db.connect(tmp_path / "state.db")
        rt_projects.add(
            conn, source="jira", identifier="ZXTL", repo_path=str(repo_path)
        )

        cfg = rt_config.default_schema()
        cfg.telegram.bot_token = fake_tg.bot_token
        cfg.telegram.group_chat_id = fake_tg.chat_id
        cfg.telegram.allowed_user_ids = [99001]
        cfg.agent.task_source = "jira"
        cfg.agent.worktree_root = str(tmp_path / "wt")

        spawned: list[object] = []
        adapter = JiraAdapter(host="test.atlassian.net")
        ctx = rt_dispatcher.DispatchContext(
            conn=conn,
            client=client,
            cfg=cfg,
            adapter=adapter,
            spawn_worker_task=lambda c: (spawned.append(c), c.close())[0],
        )

        msg = _message(
            "ZXTL-1234 fix the bug",
            sender_id=99001,
            chat_id=fake_tg.chat_id,
        )
        asyncio.run(rt_dispatcher.dispatch(msg, ctx))

        # Session row exists with provider columns populated.
        rows = conn.execute(
            "SELECT issue_key, source, project_identifier FROM sessions"
        ).fetchall()
        assert rows == [("ZXTL-1234", "jira", "ZXTL")]

        # AT10 (T-A3 strengthening) — EV_TASK_SOURCE_RESOLVED is emitted
        # from the dispatcher's _accept_trigger chokepoint, not just by
        # direct audit.record_event calls in unit tests. This guards
        # against silent removal of the emission line.
        import json as _json

        from remotask.daemon import audit as rt_audit

        ev_rows = conn.execute(
            "SELECT payload FROM session_events WHERE type = ?",
            (rt_audit.EV_TASK_SOURCE_RESOLVED,),
        ).fetchall()
        assert len(ev_rows) == 1, "EV_TASK_SOURCE_RESOLVED missing from accept path"
        payload = _json.loads(ev_rows[0][0])
        assert payload["adapter"] == "jira"
        assert payload["source_identifier"] == "ZXTL"
        assert payload["canonical_key"] == "ZXTL-1234"


class TestDispatcherJiraRejectsForeignKey:
    """AT2 — when active adapter is Jira, ``owner/repo#42`` is not accepted."""

    def test_owner_repo_hash_is_ignored(
        self,
        tmp_path: Path,
        repo_path: Path,
        fake_tg: FakeTelegram,
        client: TelegramClient,
    ) -> None:
        conn = core_db.connect(tmp_path / "state.db")
        rt_projects.add(
            conn, source="jira", identifier="ZXTL", repo_path=str(repo_path)
        )

        cfg = rt_config.default_schema()
        cfg.telegram.bot_token = fake_tg.bot_token
        cfg.telegram.group_chat_id = fake_tg.chat_id
        cfg.telegram.allowed_user_ids = [99001]
        cfg.agent.task_source = "jira"
        cfg.agent.worktree_root = str(tmp_path / "wt")

        adapter = JiraAdapter(host="test.atlassian.net")
        ctx = rt_dispatcher.DispatchContext(
            conn=conn,
            client=client,
            cfg=cfg,
            adapter=adapter,
            spawn_worker_task=lambda c: c.close(),
        )

        msg = _message(
            "p-acid/remotask#42 fix",
            sender_id=99001,
            chat_id=fake_tg.chat_id,
        )
        asyncio.run(rt_dispatcher.dispatch(msg, ctx))

        rows = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        assert rows[0] == 0


class TestDispatcherGitHubMode:
    """AT4 — ``agent.task_source = "github_issue"`` accepts ``owner/repo#N``
    and stores the canonical key + structured columns.
    """

    def test_github_issue_accept_and_normalise(
        self,
        tmp_path: Path,
        repo_path: Path,
        fake_tg: FakeTelegram,
        client: TelegramClient,
    ) -> None:
        conn = core_db.connect(tmp_path / "state.db")
        rt_projects.add(
            conn,
            source="github_issue",
            identifier="p-acid/remotask",
            repo_path=str(repo_path),
        )

        cfg = rt_config.default_schema()
        cfg.telegram.bot_token = fake_tg.bot_token
        cfg.telegram.group_chat_id = fake_tg.chat_id
        cfg.telegram.allowed_user_ids = [99001]
        cfg.agent.task_source = "github_issue"
        cfg.agent.worktree_root = str(tmp_path / "wt")

        projects_rows = rt_projects.list_all(conn)
        adapter = GitHubIssueAdapter(projects_rows)
        ctx = rt_dispatcher.DispatchContext(
            conn=conn,
            client=client,
            cfg=cfg,
            adapter=adapter,
            spawn_worker_task=lambda c: c.close(),
        )

        msg = _message(
            "p-acid/remotask#42 please look",
            sender_id=99001,
            chat_id=fake_tg.chat_id,
        )
        asyncio.run(rt_dispatcher.dispatch(msg, ctx))

        rows = conn.execute(
            "SELECT issue_key, source, project_identifier FROM sessions"
        ).fetchall()
        assert rows == [
            ("gh-p-acid-remotask-42", "github_issue", "p-acid/remotask")
        ]
