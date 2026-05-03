"""AT8 + AT10 — sessions row carries provider/project as discrete columns
and ``EV_TASK_SOURCE_RESOLVED`` audit event is emitted on accept.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from remotask.core import db as core_db
from remotask.core import projects as rt_projects
from remotask.daemon import audit as rt_audit
from remotask.daemon import sessions as rt_sessions


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return core_db.connect(tmp_path / "state.db")


class TestSessionsProviderColumns:
    """AT8 — ``source`` + ``project_identifier`` are discrete columns on
    ``sessions``, populated at insert time from the active adapter.
    """

    def test_sessions_table_has_provider_columns(
        self, conn: sqlite3.Connection
    ) -> None:
        cur = conn.execute("PRAGMA table_info(sessions)")
        cols = {row[1] for row in cur.fetchall()}
        assert "source" in cols
        assert "project_identifier" in cols

    def test_two_sessions_carry_distinct_pairs(
        self, conn: sqlite3.Connection
    ) -> None:
        # Insert one Jira-mode and one GitHub-Issue-mode session row.
        rt_sessions.insert_enqueued_session(
            conn,
            session_id="s1",
            issue_key="ZXTL-1234",
            trigger_user=42,
            trigger_text="ZXTL-1234",
            source="jira",
            project_identifier="ZXTL",
        )
        rt_sessions.insert_enqueued_session(
            conn,
            session_id="s2",
            issue_key="gh-p-acid-remotask-42",
            trigger_user=42,
            trigger_text="p-acid/remotask#42",
            source="github_issue",
            project_identifier="p-acid/remotask",
        )

        rows = conn.execute(
            "SELECT id, source, project_identifier FROM sessions ORDER BY id"
        ).fetchall()
        assert len(rows) == 2
        rows_by_id = {r[0]: (r[1], r[2]) for r in rows}
        assert rows_by_id["s1"] == ("jira", "ZXTL")
        assert rows_by_id["s2"] == ("github_issue", "p-acid/remotask")


class TestProjectsTableSchema:
    """AT8 (V0001 amended) — projects table carries (source, source_identifier) PK."""

    def test_projects_pk_is_composite(self, conn: sqlite3.Connection) -> None:
        cur = conn.execute("PRAGMA table_info(projects)")
        rows = cur.fetchall()
        cols = {row[1] for row in rows}
        assert "source" in cols
        assert "source_identifier" in cols
        # PK columns have ``pk > 0``.
        pk_cols = {row[1] for row in rows if row[5] > 0}
        assert pk_cols == {"source", "source_identifier"}


class TestProjectsAccessorsTakeSource:
    """The ``by_identifier`` / ``list_registered_identifiers`` / ``add``
    accessors all take ``source`` as a named argument.
    """

    def test_by_identifier_filters_by_source(
        self, conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        rt_projects.add(
            conn, source="jira", identifier="ZXTL", repo_path=str(repo)
        )
        rt_projects.add(
            conn,
            source="github_issue",
            identifier="p-acid/remotask",
            repo_path=str(repo),
        )

        jira_row = rt_projects.by_identifier(
            conn, source="jira", identifier="ZXTL"
        )
        gh_row = rt_projects.by_identifier(
            conn, source="github_issue", identifier="p-acid/remotask"
        )
        assert jira_row is not None
        assert gh_row is not None
        # Cross-source lookup must return None.
        assert (
            rt_projects.by_identifier(
                conn, source="github_issue", identifier="ZXTL"
            )
            is None
        )

    def test_list_registered_identifiers_filters_by_source(
        self, conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        rt_projects.add(
            conn, source="jira", identifier="ZXTL", repo_path=str(repo)
        )
        rt_projects.add(
            conn,
            source="github_issue",
            identifier="p-acid/remotask",
            repo_path=str(repo),
        )
        assert rt_projects.list_registered_identifiers(conn, source="jira") == [
            "ZXTL"
        ]
        assert rt_projects.list_registered_identifiers(
            conn, source="github_issue"
        ) == ["p-acid/remotask"]


class TestTaskSourceResolvedAuditEvent:
    """AT10 — ``EV_TASK_SOURCE_RESOLVED`` exists and emission writes a single
    row into ``session_events`` with the canonical payload shape.
    """

    def test_event_constant_exists(self) -> None:
        assert hasattr(rt_audit, "EV_TASK_SOURCE_RESOLVED")
        assert isinstance(rt_audit.EV_TASK_SOURCE_RESOLVED, str)

    def test_event_payload_carries_three_fields(
        self, conn: sqlite3.Connection
    ) -> None:
        rt_sessions.insert_enqueued_session(
            conn,
            session_id="s1",
            issue_key="gh-p-acid-remotask-42",
            trigger_user=42,
            trigger_text="p-acid/remotask#42",
            source="github_issue",
            project_identifier="p-acid/remotask",
        )
        rt_audit.record_event(
            conn,
            session_id="s1",
            type=rt_audit.EV_TASK_SOURCE_RESOLVED,
            payload={
                "adapter": "github_issue",
                "source_identifier": "p-acid/remotask",
                "canonical_key": "gh-p-acid-remotask-42",
            },
        )
        conn.commit()

        rows = conn.execute(
            "SELECT type, payload FROM session_events WHERE type = ?",
            (rt_audit.EV_TASK_SOURCE_RESOLVED,),
        ).fetchall()
        assert len(rows) == 1
        payload = json.loads(rows[0][1])
        assert payload["adapter"] == "github_issue"
        assert payload["source_identifier"] == "p-acid/remotask"
        assert payload["canonical_key"] == "gh-p-acid-remotask-42"
