"""Project mapping CRUD — provider-aware (008/T5).

The 002 schema keyed ``projects`` on a single ``jira_key`` column. 008
amends V0001 in place to use a composite ``(source, source_identifier)``
PK so a single install can register Jira prefixes (`ZXTL`) and
GitHub-Issue ``owner/repo`` mappings concurrently. Accessors take an
explicit ``source`` argument; the dispatcher infers ``source`` from
``cfg.agent.task_source`` and passes it through.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import TypedDict

# Source identifier shape per provider:
# - Jira: prefix matching ``[A-Z]{2,10}`` (e.g., ``ZXTL``)
# - GitHub Issue: ``owner/repo`` (e.g., ``p-acid/remotask``)
SUPPORTED_SOURCES = ("jira", "github_issue")


class ProjectsError(Exception):
    """Base class for project errors."""


class DuplicateKeyError(ProjectsError):
    """Raised on duplicate ``(source, source_identifier)`` INSERT."""


class UnknownKeyError(ProjectsError):
    """Raised on operations against a missing ``(source, source_identifier)``."""


class ProjectRow(TypedDict):
    source: str
    source_identifier: str
    repo_path: str
    base_branch: str
    enabled: int
    added_at: int
    updated_at: int


def validate_source(source: str) -> None:
    if source not in SUPPORTED_SOURCES:
        raise ValueError(
            f"unknown source {source!r}; expected one of {SUPPORTED_SOURCES}"
        )


# T5 placeholder identifier validators. T4 swaps these for adapter-driven
# `matches`-style validation tied to ``cfg.agent.task_source`` so the
# identifier shape is enforced by the active adapter (B9 policy).
import re as _re

_JIRA_IDENTIFIER_RE = _re.compile(r"^[A-Z]{2,10}$")
_GITHUB_IDENTIFIER_RE = _re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def validate_identifier(source: str, identifier: str) -> None:
    if source == "jira":
        if not _JIRA_IDENTIFIER_RE.fullmatch(identifier):
            raise ValueError(
                f"invalid Jira identifier {identifier!r}; "
                f"must match [A-Z]{{2,10}} (e.g. ZXTL)"
            )
    elif source == "github_issue":
        if not _GITHUB_IDENTIFIER_RE.fullmatch(identifier):
            raise ValueError(
                f"invalid GitHub identifier {identifier!r}; "
                f"must match owner/repo (e.g. p-acid/remotask)"
            )


def validate_repo_path(repo_path: str) -> None:
    p = Path(repo_path).expanduser()
    if not p.exists():
        raise ValueError(f"repo path does not exist: {repo_path}")
    if not p.is_dir():
        raise ValueError(f"repo path is not a directory: {repo_path}")
    if not (p / ".git").exists():
        raise ValueError(f"not a git repository (no .git found): {repo_path}")


def add(
    conn: sqlite3.Connection,
    source: str,
    identifier: str,
    repo_path: str,
    base_branch: str = "main",
) -> None:
    """Insert a project mapping.

    ``source`` is one of :data:`SUPPORTED_SOURCES`; ``identifier`` is the
    provider-native form (Jira prefix or ``owner/repo``). The composite
    ``(source, identifier)`` PK rejects duplicates.
    """
    validate_source(source)
    validate_identifier(source, identifier)
    validate_repo_path(repo_path)
    now = int(time.time())
    try:
        conn.execute(
            "INSERT INTO projects(source, source_identifier, repo_path, "
            "base_branch, enabled, added_at, updated_at) "
            "VALUES (?, ?, ?, ?, 1, ?, ?)",
            (
                source,
                identifier,
                str(Path(repo_path).expanduser().resolve()),
                base_branch,
                now,
                now,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        raise DuplicateKeyError(
            f"project ({source!r}, {identifier!r}) already exists"
        ) from e


def list_all(conn: sqlite3.Connection) -> list[ProjectRow]:
    rows = conn.execute(
        "SELECT source, source_identifier, repo_path, base_branch, "
        "enabled, added_at, updated_at FROM projects "
        "ORDER BY source, source_identifier"
    ).fetchall()
    return [
        ProjectRow(
            source=r[0],
            source_identifier=r[1],
            repo_path=r[2],
            base_branch=r[3],
            enabled=int(r[4]),
            added_at=int(r[5]),
            updated_at=int(r[6]),
        )
        for r in rows
    ]


def remove(conn: sqlite3.Connection, source: str, identifier: str) -> None:
    cursor = conn.execute(
        "DELETE FROM projects WHERE source = ? AND source_identifier = ?",
        (source, identifier),
    )
    conn.commit()
    if cursor.rowcount == 0:
        raise UnknownKeyError(
            f"project ({source!r}, {identifier!r}) is not registered"
        )


def by_identifier(
    conn: sqlite3.Connection, source: str, identifier: str
) -> ProjectRow | None:
    """Return the registered project for ``(source, identifier)``.

    Rows whose ``enabled`` column is ``0`` are treated as not registered
    (the dispatcher's "unknown prefix" UX applies).
    """
    row = conn.execute(
        "SELECT source, source_identifier, repo_path, base_branch, "
        "enabled, added_at, updated_at FROM projects "
        "WHERE source = ? AND source_identifier = ? AND enabled = 1",
        (source, identifier),
    ).fetchone()
    if row is None:
        return None
    return ProjectRow(
        source=row[0],
        source_identifier=row[1],
        repo_path=row[2],
        base_branch=row[3],
        enabled=int(row[4]),
        added_at=int(row[5]),
        updated_at=int(row[6]),
    )


def list_registered_identifiers(
    conn: sqlite3.Connection, source: str
) -> list[str]:
    """Return enabled identifiers for ``source``, sorted alphabetically."""
    rows = conn.execute(
        "SELECT source_identifier FROM projects "
        "WHERE source = ? AND enabled = 1 ORDER BY source_identifier",
        (source,),
    ).fetchall()
    return [r[0] for r in rows]
