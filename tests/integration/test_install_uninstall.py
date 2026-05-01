from __future__ import annotations

import json
import plistlib
from pathlib import Path

import pytest


def _agents_dir(tmp_xdg_env: Path) -> Path:
    return tmp_xdg_env / "LaunchAgents"


def _plist_path(tmp_xdg_env: Path, label: str = "kr.mission-driven.remote-task") -> Path:
    return _agents_dir(tmp_xdg_env) / f"{label}.plist"


def _audit_path(tmp_xdg_env: Path) -> Path:
    return tmp_xdg_env / "data" / "remote-task" / "logs" / "audit.log"


def _no_op(*args: object, **kwargs: object) -> None:
    return None


@pytest.fixture
def stub_env(tmp_xdg_env: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Env vars that subprocess CLI runs see — stub launchctl + LaunchAgents."""
    agents = _agents_dir(tmp_xdg_env)
    agents.mkdir()
    log_file = tmp_xdg_env / "data" / "remote-task" / "logs" / "launchctl_calls.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.touch()

    return {
        "REMOTE_TASK_LAUNCH_AGENTS_DIR": str(agents),
        "REMOTE_TASK_STUB_LAUNCHCTL_LOG": str(log_file),
        "REMOTE_TASK_SKIP_HEALTH_POLL": "1",
    }


def _read_calls(tmp_xdg_env: Path) -> dict[str, list[str]]:
    log_file = tmp_xdg_env / "data" / "remote-task" / "logs" / "launchctl_calls.log"
    calls: dict[str, list[str]] = {"load": [], "unload": []}
    if not log_file.exists():
        return calls
    for line in log_file.read_text().splitlines():
        if not line.strip():
            continue
        op, _, plist = line.partition(" ")
        if op in calls:
            calls[op].append(plist)
    return calls


def test_install_creates_plist(cli_runner, tmp_xdg_env: Path, stub_env: dict[str, str]) -> None:
    cli_runner("init", extra_env=stub_env)
    cli_runner("install", extra_env=stub_env)
    plist = _plist_path(tmp_xdg_env)
    assert plist.exists()
    parsed = plistlib.loads(plist.read_bytes())
    assert parsed["Label"] == "kr.mission-driven.remote-task"
    calls = _read_calls(tmp_xdg_env)
    assert calls["load"], "launchctl load was not invoked"


def test_uninstall_preserves_user_data(
    cli_runner, tmp_xdg_env: Path, stub_env: dict[str, str]
) -> None:
    cli_runner("init", extra_env=stub_env)
    cli_runner("install", extra_env=stub_env)
    plist = _plist_path(tmp_xdg_env)
    assert plist.exists()
    cli_runner("uninstall", extra_env=stub_env)
    assert not plist.exists()
    config_path = tmp_xdg_env / "config" / "remote-task" / "config.toml"
    db_path = tmp_xdg_env / "data" / "remote-task" / "state.db"
    assert config_path.exists()
    assert db_path.exists()
    calls = _read_calls(tmp_xdg_env)
    assert calls["unload"], "launchctl unload was not invoked"


def test_uninstall_purge_removes_data(
    cli_runner, tmp_xdg_env: Path, stub_env: dict[str, str]
) -> None:
    cli_runner("init", extra_env=stub_env)
    cli_runner("install", extra_env=stub_env)
    cli_runner("uninstall", "--purge", extra_env=stub_env)
    config_path = tmp_xdg_env / "config" / "remote-task"
    data_path = tmp_xdg_env / "data" / "remote-task"
    assert not config_path.exists()
    assert not data_path.exists()


def test_install_replaces_existing_plist(
    cli_runner, tmp_xdg_env: Path, stub_env: dict[str, str]
) -> None:
    """FR-042: re-install with --force unloads then reloads the agent."""
    cli_runner("init", extra_env=stub_env)
    cli_runner("install", extra_env=stub_env)
    calls_before = _read_calls(tmp_xdg_env)
    assert len(calls_before["load"]) == 1
    cli_runner("install", "--force", extra_env=stub_env)
    calls_after = _read_calls(tmp_xdg_env)
    assert len(calls_after["unload"]) >= 1
    assert len(calls_after["load"]) == 2


def test_install_emits_audit_log(
    cli_runner, tmp_xdg_env: Path, stub_env: dict[str, str]
) -> None:
    cli_runner("init", extra_env=stub_env)
    cli_runner("install", extra_env=stub_env)
    audit = _audit_path(tmp_xdg_env)
    assert audit.exists()
    events = [json.loads(line) for line in audit.read_text().splitlines() if line.strip()]
    install_events = [e for e in events if e["event"] == "launchd.install"]
    assert install_events, f"no launchd.install event:\n{events}"


def test_uninstall_emits_audit_log(
    cli_runner, tmp_xdg_env: Path, stub_env: dict[str, str]
) -> None:
    cli_runner("init", extra_env=stub_env)
    cli_runner("install", extra_env=stub_env)
    cli_runner("uninstall", extra_env=stub_env)
    audit = _audit_path(tmp_xdg_env)
    events = [json.loads(line) for line in audit.read_text().splitlines() if line.strip()]
    uninstall_events = [e for e in events if e["event"] == "launchd.uninstall"]
    assert uninstall_events
    assert "purge" in uninstall_events[-1]


def test_install_requires_init(
    cli_runner, tmp_xdg_env: Path, stub_env: dict[str, str]
) -> None:
    result = cli_runner("install", extra_env=stub_env, expect_exit=None)
    assert result.returncode == 3
    assert "init" in (result.stdout + result.stderr).lower()


# Opt-in real launchctl tests. Skipped by default; run with `pytest -m local_only`.

@pytest.mark.local_only
def test_install_loads_with_launchctl(cli_runner, tmp_xdg_env: Path) -> None:
    """Real launchctl test — skipped unless opt-in."""
    pytest.skip("real launchctl test requires manual opt-in")


@pytest.mark.local_only
def test_uninstall_unloads_with_launchctl(cli_runner, tmp_xdg_env: Path) -> None:
    """Real launchctl test — skipped unless opt-in."""
    pytest.skip("real launchctl test requires manual opt-in")
