from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


def _config_path(tmp_xdg_env: Path) -> Path:
    return tmp_xdg_env / "config" / "remote-task" / "config.toml"


def _data_dir(tmp_xdg_env: Path) -> Path:
    return tmp_xdg_env / "data" / "remote-task"


def _read_toml(p: Path) -> dict:
    return tomllib.loads(p.read_text())


def test_get_default_value(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    result = cli_runner("config", "get", "agent.max_concurrent")
    assert result.stdout.strip() == "1"


def test_set_round_trip(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    cli_runner("config", "set", "agent.max_concurrent", "2")
    result = cli_runner("config", "get", "agent.max_concurrent")
    assert result.stdout.strip() == "2"
    cfg = _read_toml(_config_path(tmp_xdg_env))
    assert cfg["agent"]["max_concurrent"] == 2


def test_set_unknown_key_rejected(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    result = cli_runner("config", "set", "foo.bar", "1", expect_exit=None)
    assert result.returncode != 0
    msg = result.stdout + result.stderr
    assert "unknown" in msg.lower() or "not defined" in msg.lower()


def test_set_invalid_format_rejected(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    result = cli_runner(
        "config", "set", "agent.max_concurrent", "abc", expect_exit=None
    )
    assert result.returncode != 0
    msg = result.stdout + result.stderr
    assert "integer" in msg.lower() or "int" in msg.lower()


def test_set_out_of_range_rejected(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    result = cli_runner(
        "config", "set", "agent.max_concurrent", "99", expect_exit=None
    )
    assert result.returncode != 0


def test_secret_masked_by_default(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    result = cli_runner("config", "get", "daemon.auth_token")
    out = result.stdout.strip()
    assert out.startswith("****")
    cfg = _read_toml(_config_path(tmp_xdg_env))
    real = cfg["daemon"]["auth_token"]
    assert real not in out  # full token must NOT appear


def test_reveal_flag_returns_plaintext(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    cfg = _read_toml(_config_path(tmp_xdg_env))
    real = cfg["daemon"]["auth_token"]
    result = cli_runner("config", "get", "daemon.auth_token", "--reveal")
    assert result.stdout.strip() == real


def test_list_masks_secrets(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    cfg = _read_toml(_config_path(tmp_xdg_env))
    real = cfg["daemon"]["auth_token"]
    result = cli_runner("config", "list")
    assert real not in result.stdout
    assert "daemon.auth_token" in result.stdout
    assert "****" in result.stdout


def test_regenerate_token(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    before = _read_toml(_config_path(tmp_xdg_env))["daemon"]["auth_token"]
    cli_runner("config", "regenerate-token")
    after = _read_toml(_config_path(tmp_xdg_env))["daemon"]["auth_token"]
    assert before != after
    assert len(after) >= 32


def test_set_list_value(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    cli_runner(
        "config", "set", "telegram.allowed_user_ids", "12345,67890"
    )
    cfg = _read_toml(_config_path(tmp_xdg_env))
    assert cfg["telegram"]["allowed_user_ids"] == [12345, 67890]


def test_regenerate_token_emits_audit_log(cli_runner, tmp_xdg_env: Path) -> None:
    """FR-053: token rotation audit logged without plaintext token."""
    cli_runner("init")
    before = _read_toml(_config_path(tmp_xdg_env))["daemon"]["auth_token"]
    cli_runner("config", "regenerate-token")
    after = _read_toml(_config_path(tmp_xdg_env))["daemon"]["auth_token"]

    audit_path = _data_dir(tmp_xdg_env) / "logs" / "audit.log"
    assert audit_path.exists(), "audit.log not created"
    lines = audit_path.read_text().strip().splitlines()
    matching = [json.loads(line) for line in lines if "token.regenerated" in line]
    assert matching, f"no token.regenerated entry in audit log:\n{lines}"
    last = matching[-1]
    assert last["event"] == "token.regenerated"
    # The plaintext token must NOT appear anywhere in audit log.
    full = audit_path.read_text()
    assert before not in full
    assert after not in full


def test_get_unknown_key_rejected(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    result = cli_runner("config", "get", "foo.bar", expect_exit=None)
    assert result.returncode != 0


def test_help_output_no_secrets(cli_runner, tmp_xdg_env: Path) -> None:
    """Make sure error/help paths never echo secrets, even on misuse."""
    cli_runner("init")
    cfg = _read_toml(_config_path(tmp_xdg_env))
    real = cfg["daemon"]["auth_token"]
    result = cli_runner("config", "--help")
    assert real not in result.stdout
    assert real not in result.stderr


CONFIG_LIST_KEY_RE = re.compile(r"^[a-z]+\.[a-z_]+\b", re.MULTILINE)


def test_list_includes_all_known_keys(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    result = cli_runner("config", "list")
    keys_in_output = set(CONFIG_LIST_KEY_RE.findall(result.stdout))
    expected = {
        "agent.max_concurrent",
        "agent.permission_mode",
        "daemon.auth_token",
        "daemon.http_port",
        "telegram.bot_token",
        "telegram.allowed_user_ids",
        "logging.level",
    }
    assert expected <= keys_in_output, f"missing: {expected - keys_in_output}"
