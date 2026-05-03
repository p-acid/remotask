from __future__ import annotations

import sqlite3
import time
import tomllib
from pathlib import Path


def _read_config(p: Path) -> dict:
    return tomllib.loads(p.read_text())


def test_init_creates_all_artifacts(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    config_path = tmp_xdg_env / "config" / "remotask" / "config.toml"
    db_path = tmp_xdg_env / "data" / "remotask" / "state.db"
    log_dir = tmp_xdg_env / "data" / "remotask" / "logs"
    assert config_path.exists()
    assert db_path.exists()
    assert log_dir.is_dir()


def test_init_config_permission_0600(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    config_path = tmp_xdg_env / "config" / "remotask" / "config.toml"
    mode = config_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_init_db_schema_v1(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    db_path = tmp_xdg_env / "data" / "remotask" / "state.db"
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"schema_version", "projects", "sessions", "session_events", "locks"} <= tables
        version_rows = conn.execute("SELECT version FROM schema_version").fetchall()
        assert (1,) in version_rows
    finally:
        conn.close()


def test_init_generates_auth_token(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    config_path = tmp_xdg_env / "config" / "remotask" / "config.toml"
    cfg = _read_config(config_path)
    token = cfg["daemon"]["auth_token"]
    assert isinstance(token, str)
    assert len(token) >= 32


def test_init_idempotent(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    config_path = tmp_xdg_env / "config" / "remotask" / "config.toml"
    first_token = _read_config(config_path)["daemon"]["auth_token"]
    first_mtime = config_path.stat().st_mtime_ns

    time.sleep(0.01)
    result = cli_runner("init")
    second_token = _read_config(config_path)["daemon"]["auth_token"]

    assert second_token == first_token, "init must not regenerate token on repeat"
    assert config_path.stat().st_mtime_ns == first_mtime, "init must not rewrite config"
    assert "already initialized" in result.stdout.lower() or "no changes" in result.stdout.lower()


def test_init_force_overwrites_config_preserves_db(
    cli_runner, tmp_xdg_env: Path
) -> None:
    cli_runner("init")
    db_path = tmp_xdg_env / "data" / "remotask" / "state.db"
    config_path = tmp_xdg_env / "config" / "remotask" / "config.toml"
    first_token = _read_config(config_path)["daemon"]["auth_token"]

    # Insert a project row to verify DB preservation.
    conn = sqlite3.connect(db_path)
    try:
        now = int(time.time())
        conn.execute(
            "INSERT INTO projects(source, source_identifier, repo_path, "
            "base_branch, enabled, added_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("jira", "ZXTL", "/tmp/repo", "main", 1, now, now),
        )
        conn.commit()
    finally:
        conn.close()

    cli_runner("init", "--force")

    # Config token regenerated.
    second_token = _read_config(config_path)["daemon"]["auth_token"]
    assert second_token != first_token

    # DB user row preserved.
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT source_identifier FROM projects").fetchall()
    finally:
        conn.close()
    assert ("ZXTL",) in rows


def test_init_under_3s(cli_runner) -> None:
    """SC-003: init completes within 3s on a clean environment."""
    start = time.perf_counter()
    cli_runner("init")
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0, f"init took {elapsed:.3f}s (>= 3.0s)"


def test_init_emits_summary(cli_runner, tmp_xdg_env: Path) -> None:
    result = cli_runner("init")
    out = result.stdout.lower()
    assert "config.toml" in out
    assert "state.db" in out
