"""SQLite connection + simple migration runner."""
from __future__ import annotations

import re
import sqlite3
import time
from importlib import resources
from pathlib import Path

_MIGRATION_PKG = "remote_task.migrations"
_MIGRATION_FILENAME_RE = re.compile(r"^V(\d{4})__([A-Za-z0-9_]+)\.sql$")


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
