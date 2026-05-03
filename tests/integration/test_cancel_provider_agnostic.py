"""AT9 — operator-stop ladder + topic prefix work identically across providers.

Given a running GitHub-Issue session, ``/cancel`` invokes the same SIGUSR1 →
grace → SIGTERM ladder as a Jira session, and topic posts use the same
``[<canonical_key>] ...`` prefix chokepoint.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from remotask.core import config as rt_config
from remotask.core import db as core_db
from remotask.core import projects as rt_projects
from remotask.daemon import sessions as rt_sessions
from remotask.daemon import topic as rt_topic


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return core_db.connect(tmp_path / "state.db")


class TestTopicPrefixIsProviderAgnostic:
    """``format_progress(canonical_key, body)`` produces ``[<key>] <body>``
    for both Jira-shape and GH-shape canonical keys.
    """

    def test_jira_key_prefix(self) -> None:
        rendered = rt_topic.format_progress("ZXTL-1234", "running")
        assert rendered == "[ZXTL-1234] running"

    def test_github_canonical_prefix(self) -> None:
        rendered = rt_topic.format_progress("gh-p-acid-remotask-42", "running")
        assert rendered == "[gh-p-acid-remotask-42] running"


class TestCancelLadderForGitHubSession:
    """The 003/005 termination ladder is unchanged when the session was
    accepted under the GitHub-Issue adapter — the dispatcher's
    ``_handle_termination`` resolves topic → session by ``topic_id`` and
    sends SIGUSR1 to the worker PID, regardless of which provider produced
    the session.
    """

    def test_active_session_lookup_works_for_gh_canonical(
        self, conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        rt_projects.add(
            conn,
            source="github_issue",
            identifier="p-acid/remotask",
            repo_path=str(repo),
        )
        rt_sessions.insert_enqueued_session(
            conn,
            session_id="s1",
            issue_key="gh-p-acid-remotask-42",
            trigger_user=42,
            trigger_text="p-acid/remotask#42",
            source="github_issue",
            project_identifier="p-acid/remotask",
        )
        rt_sessions.set_topic_id(conn, session_id="s1", topic_id=1234)
        rt_sessions.transition(
            conn,
            session_id="s1",
            from_status="enqueued",
            to_status="starting",
        )
        rt_sessions.transition(
            conn,
            session_id="s1",
            from_status="starting",
            to_status="running",
        )

        row = core_db.get_active_session_by_topic(conn, 1234)
        assert row is not None
        assert row["id"] == "s1"
        assert row["issue_key"] == "gh-p-acid-remotask-42"
