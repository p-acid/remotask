"""Jira project ↔ git repo mapping CRUD."""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import TypedDict

_JIRA_KEY_RE = re.compile(r"^[A-Z]{2,10}$")


class ProjectsError(Exception):
    """Base class for project errors."""


class DuplicateKeyError(ProjectsError):
    """Raised on duplicate jira_key INSERT."""


class UnknownKeyError(ProjectsError):
    """Raised on operations against a missing jira_key."""


class ProjectRow(TypedDict):
    jira_key: str
    repo_path: str
    base_branch: str
    enabled: int
    added_at: int
    updated_at: int


def validate_jira_key(key: str) -> None:
    if not _JIRA_KEY_RE.fullmatch(key):
        raise ValueError(
            f"invalid jira key {key!r}; must match [A-Z]{{2,10}} (e.g. ZXTL)"
        )


def validate_repo_path(repo_path: str) -> None:
    p = Path(repo_path).expanduser()
    if not p.exists():
        raise ValueError(f"repo path does not exist: {repo_path}")
    if not p.is_dir():
        raise ValueError(f"repo path is not a directory: {repo_path}")
    if not (p / ".git").exists():
        raise ValueError(f"not a git repository (no .git found): {repo_path}")


def add(conn: sqlite3.Connection, jira_key: str, repo_path: str, base_branch: str = "main") -> None:
    validate_jira_key(jira_key)
    validate_repo_path(repo_path)
    now = int(time.time())
    try:
        conn.execute(
            "INSERT INTO projects(jira_key, repo_path, base_branch, enabled, added_at, updated_at) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (jira_key, str(Path(repo_path).expanduser().resolve()), base_branch, now, now),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        raise DuplicateKeyError(f"project {jira_key!r} already exists") from e


def list_all(conn: sqlite3.Connection) -> list[ProjectRow]:
    rows = conn.execute(
        "SELECT jira_key, repo_path, base_branch, enabled, added_at, updated_at "
        "FROM projects ORDER BY jira_key"
    ).fetchall()
    return [
        ProjectRow(
            jira_key=r[0],
            repo_path=r[1],
            base_branch=r[2],
            enabled=int(r[3]),
            added_at=int(r[4]),
            updated_at=int(r[5]),
        )
        for r in rows
    ]


def remove(conn: sqlite3.Connection, jira_key: str) -> None:
    cursor = conn.execute("DELETE FROM projects WHERE jira_key = ?", (jira_key,))
    conn.commit()
    if cursor.rowcount == 0:
        raise UnknownKeyError(f"project {jira_key!r} is not registered")


def by_prefix(conn: sqlite3.Connection, prefix: str) -> ProjectRow | None:
    """Return the registered project for ``prefix`` (case-sensitive jira key match).

    A row whose ``enabled`` column is ``0`` is treated as not registered — the
    dispatcher's "unknown prefix" UX applies, per data-model.md.
    """
    row = conn.execute(
        "SELECT jira_key, repo_path, base_branch, enabled, added_at, updated_at "
        "FROM projects WHERE jira_key = ? AND enabled = 1",
        (prefix,),
    ).fetchone()
    if row is None:
        return None
    return ProjectRow(
        jira_key=row[0],
        repo_path=row[1],
        base_branch=row[2],
        enabled=int(row[3]),
        added_at=int(row[4]),
        updated_at=int(row[5]),
    )


def list_registered_prefixes(conn: sqlite3.Connection) -> list[str]:
    """Return enabled prefixes (jira keys) sorted alphabetically."""
    rows = conn.execute(
        "SELECT jira_key FROM projects WHERE enabled = 1 ORDER BY jira_key"
    ).fetchall()
    return [r[0] for r in rows]
