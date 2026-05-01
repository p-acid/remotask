"""Integration tests for ``remotask telegram`` subcommands.

We can't test the live ``getUpdates`` loop in CI without a real bot token, so
these tests focus on the CLI surface: exit codes, error messages, and on-disk
side effects (``listener.cmd`` / ``listener.state``).

Lifecycle scenarios that *do* need a live daemon are covered by
``quickstart.md`` (manual verification on a real Telegram group).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from remotask.daemon import listener_state


def test_status_when_no_state_file_exits_1(cli_runner) -> None:
    res = cli_runner("init", expect_exit=0)
    assert res.returncode == 0
    res = cli_runner("telegram", "status", expect_exit=1)
    assert "unavailable" in (res.stdout + res.stderr).lower()


def test_status_reads_existing_state_file(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init", expect_exit=0)
    state_path = tmp_xdg_env / "data" / "remotask" / "listener.state"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = listener_state.ListenerState(
        running=True,
        started_at=time.time() - 60,
        last_poll_ok_at=time.time() - 5,
        consecutive_failures=0,
        active_sessions=1,
        whitelist_size=2,
        degraded=False,
        last_update_id=42,
    )
    state_path.write_text(state.to_json(), encoding="utf-8")
    state_path.chmod(0o600)

    res = cli_runner("telegram", "status", expect_exit=0)
    assert "listener:" in res.stdout
    assert "running" in res.stdout
    assert "active sessions: 1" in res.stdout
    assert "whitelist size:  2" in res.stdout


def test_status_json_emits_machine_readable(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init", expect_exit=0)
    state_path = tmp_xdg_env / "data" / "remotask" / "listener.state"
    state = listener_state.ListenerState(
        running=False,
        started_at=time.time() - 200,
        last_poll_ok_at=time.time() - 50,
        consecutive_failures=2,
        active_sessions=0,
        whitelist_size=1,
        degraded=False,
        last_update_id=7,
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(state.to_json(), encoding="utf-8")
    state_path.chmod(0o600)

    res = cli_runner("telegram", "status", "--json", expect_exit=0)
    parsed = json.loads(res.stdout.strip())
    assert parsed["running"] is False
    assert parsed["consecutive_failures"] == 2
    assert parsed["last_update_id"] == 7


def test_start_with_empty_whitelist_exits_5(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init", expect_exit=0)
    # Set bot_token + chat_id but leave whitelist empty.
    cli_runner(
        "config",
        "set",
        "telegram.bot_token",
        "123456789:abcdefghijklmnopqrstuvwxyz0123456",
        expect_exit=0,
    )
    cli_runner(
        "config", "set", "--", "telegram.group_chat_id", "-1000000000001", expect_exit=0
    )

    res = cli_runner("telegram", "start", expect_exit=5)
    assert "allowed_user_ids" in (res.stdout + res.stderr)


def test_start_with_no_daemon_exits_3(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init", expect_exit=0)
    cli_runner(
        "config",
        "set",
        "telegram.bot_token",
        "123456789:abcdefghijklmnopqrstuvwxyz0123456",
        expect_exit=0,
    )
    cli_runner(
        "config", "set", "--", "telegram.group_chat_id", "-1000000000001", expect_exit=0
    )
    cli_runner("config", "set", "telegram.allowed_user_ids", "99001", expect_exit=0)

    # No daemon running → start should fail with exit 3.
    res = cli_runner("telegram", "start", expect_exit=3)
    assert "daemon" in (res.stdout + res.stderr).lower()
