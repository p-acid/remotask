from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from remotask.core import db


def _all_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def test_connect_creates_schema_version_and_v1(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "state.db")
    tables = _all_tables(conn)
    assert {"schema_version", "projects", "sessions", "session_events", "locks"} <= tables
    # schema_version row recorded
    rows = conn.execute("SELECT version FROM schema_version").fetchall()
    assert (1,) in rows


def test_migrations_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "state.db"
    conn1 = db.connect(p)
    initial_count = conn1.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    conn1.close()
    conn2 = db.connect(p)
    second_count = conn2.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert initial_count == second_count == 1


def test_session_status_check_constraint(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "state.db")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sessions(id, issue_key, status, enqueued_at) VALUES (?, ?, ?, ?)",
            ("uuid-1", "ZXTL-1", "BOGUS", int(time.time())),
        )


def test_session_valid_status_inserts(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "state.db")
    conn.execute(
        "INSERT INTO sessions(id, issue_key, status, enqueued_at) VALUES (?, ?, ?, ?)",
        ("uuid-1", "ZXTL-1", "enqueued", int(time.time())),
    )
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert n == 1


def test_projects_jira_key_unique(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "state.db")
    now = int(time.time())
    conn.execute(
        "INSERT INTO projects(jira_key, repo_path, base_branch, enabled, added_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("ZXTL", "/tmp/repo", "main", 1, now, now),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO projects(jira_key, repo_path, base_branch, enabled, added_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("ZXTL", "/tmp/repo2", "main", 1, now, now),
        )


def test_session_events_cascade_delete(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "state.db")
    conn.execute("PRAGMA foreign_keys = ON")
    now = int(time.time())
    conn.execute(
        "INSERT INTO sessions(id, issue_key, status, enqueued_at) VALUES (?, ?, ?, ?)",
        ("u1", "ZXTL-9", "enqueued", now),
    )
    conn.execute(
        "INSERT INTO session_events(session_id, type, payload, created_at) VALUES (?, ?, ?, ?)",
        ("u1", "log", "{}", now),
    )
    conn.commit()
    conn.execute("DELETE FROM sessions WHERE id = 'u1'")
    conn.commit()
    rows = conn.execute("SELECT COUNT(*) FROM session_events WHERE session_id='u1'").fetchone()[0]
    assert rows == 0


def test_journal_mode_wal(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "state.db")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
