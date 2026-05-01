"""SQLite connection + simple migration runner."""
from __future__ import annotations

import re
import sqlite3
import time
from importlib import resources
from pathlib import Path

_MIGRATION_PKG = "remotask.migrations"
_MIGRATION_FILENAME_RE = re.compile(r"^V(\d{4})__([A-Za-z0-9_]+)\.sql$")

# Non-terminal session states. A row in any of these has (or is about to have)
# an active worker subprocess; it is not safe to start a second session for the
# same issue while one is in this set, and on daemon restart all such rows are
# forcibly transitioned to 'failed' (R10 in research.md).
NON_TERMINAL_STATES: tuple[str, ...] = ("enqueued", "starting", "running")


def connect(db_path: Path, *, foreign_keys: bool = True) -> sqlite3.Connection:
    """Open a connection, enable WAL, and apply pending migrations."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys = ON")
    apply_migrations(conn)
    return conn


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
          version    INTEGER PRIMARY KEY,
          slug       TEXT NOT NULL,
          applied_at INTEGER NOT NULL
        )
        """
    )
    conn.commit()


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT version FROM schema_version").fetchall()
    return {r[0] for r in rows}


def _list_migrations() -> list[tuple[int, str, str]]:
    """Return [(version, slug, sql_text), ...] sorted by version."""
    out: list[tuple[int, str, str]] = []
    pkg = resources.files(_MIGRATION_PKG)
    for entry in pkg.iterdir():
        name = entry.name
        m = _MIGRATION_FILENAME_RE.match(name)
        if not m:
            continue
        version = int(m.group(1))
        slug = m.group(2)
        sql_text = entry.read_text(encoding="utf-8")
        out.append((version, slug, sql_text))
    out.sort(key=lambda x: x[0])
    return out


def apply_migrations(conn: sqlite3.Connection) -> list[int]:
    """Apply pending migrations in a single transaction each.

    Returns the list of newly applied versions.
    """
    _ensure_schema_version_table(conn)
    already = _applied_versions(conn)
    applied: list[int] = []
    for version, slug, sql_text in _list_migrations():
        if version in already:
            continue
        try:
            conn.execute("BEGIN")
            conn.executescript(sql_text)
            conn.execute(
                "INSERT INTO schema_version(version, slug, applied_at) VALUES (?, ?, ?)",
                (version, slug, int(time.time())),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        applied.append(version)
    return applied


# ---------- session helpers (used by the dispatcher / runtime) ----------

_NON_TERMINAL_PLACEHOLDERS = ",".join("?" * len(NON_TERMINAL_STATES))


def _row_cursor(conn: sqlite3.Connection) -> sqlite3.Cursor:
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    return cur


def get_active_session_for_issue(
    conn: sqlite3.Connection, issue_key: str
) -> sqlite3.Row | None:
    """Return a non-terminal session row for ``issue_key`` if one exists.

    Used by the dispatcher to enforce the same-issue concurrency rule
    (FR-010): a second trigger for an issue already in flight is rejected.
    """
    cur = _row_cursor(conn)
    cur.execute(
        f"SELECT * FROM sessions "
        f"WHERE issue_key = ? AND status IN ({_NON_TERMINAL_PLACEHOLDERS}) "
        f"LIMIT 1",
        (issue_key, *NON_TERMINAL_STATES),
    )
    row: sqlite3.Row | None = cur.fetchone()
    return row


def count_active_sessions(conn: sqlite3.Connection) -> int:
    """Return number of sessions currently in a non-terminal state."""
    row = conn.execute(
        f"SELECT COUNT(*) FROM sessions WHERE status IN ({_NON_TERMINAL_PLACEHOLDERS})",
        NON_TERMINAL_STATES,
    ).fetchone()
    return int(row[0])


def iter_non_terminal_sessions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all non-terminal session rows (used by daemon-restart recovery)."""
    cur = _row_cursor(conn)
    cur.execute(
        f"SELECT * FROM sessions WHERE status IN ({_NON_TERMINAL_PLACEHOLDERS})",
        NON_TERMINAL_STATES,
    )
    return cur.fetchall()
