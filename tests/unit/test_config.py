from __future__ import annotations

from pathlib import Path

import pytest

from remotask.core import config


def _bootstrap(path: Path) -> config.ConfigSchema:
    """Create a fresh config file with defaults."""
    schema = config.default_schema()
    config.save(path, schema)
    return schema


def test_default_load_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    _bootstrap(p)
    loaded = config.load(p)
    assert loaded.agent.max_concurrent == 1
    assert loaded.daemon.http_port == 6789
    assert loaded.logging.level == "INFO"
    assert isinstance(loaded.daemon.auth_token, str)
    assert len(loaded.daemon.auth_token) >= 32


def test_get_dotted_path(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    _bootstrap(p)
    schema = config.load(p)
    assert config.get_dotted(schema, "agent.max_concurrent") == 1
    assert config.get_dotted(schema, "telegram.allowed_user_ids") == []
    assert config.get_dotted(schema, "logging.level") == "INFO"


def test_set_dotted_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    _bootstrap(p)
    schema = config.load(p)
    config.set_dotted(schema, "agent.max_concurrent", 5)
    config.save(p, schema)
    reloaded = config.load(p)
    assert reloaded.agent.max_concurrent == 5


def test_set_validates_type(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    _bootstrap(p)
    schema = config.load(p)
    with pytest.raises(config.ConfigValidationError):
        config.set_dotted(schema, "agent.max_concurrent", "abc")


def test_set_validates_unknown_key(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    _bootstrap(p)
    schema = config.load(p)
    with pytest.raises(config.UnknownKeyError):
        config.set_dotted(schema, "foo.bar", 1)


def test_set_validates_range(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    _bootstrap(p)
    schema = config.load(p)
    with pytest.raises(config.ConfigValidationError):
        config.set_dotted(schema, "agent.max_concurrent", 99)


def test_set_validates_enum(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    _bootstrap(p)
    schema = config.load(p)
    with pytest.raises(config.ConfigValidationError):
        config.set_dotted(schema, "logging.level", "BOGUS")


def test_parse_set_value_int(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    _bootstrap(p)
    schema = config.load(p)
    assert config.parse_set_value(schema, "agent.max_concurrent", "3") == 3


def test_parse_set_value_list(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    _bootstrap(p)
    schema = config.load(p)
    assert config.parse_set_value(
        schema, "telegram.allowed_user_ids", "12345,67890"
    ) == [12345, 67890]


def test_load_warns_on_loose_permission(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    _bootstrap(p)
    p.chmod(0o644)
    with pytest.raises(config.InsecurePermissionError):
        config.load(p, strict_permission=True)


def test_save_writes_with_0600_permission(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    _bootstrap(p)
    mode = p.stat().st_mode & 0o777
    assert mode == 0o600


def test_listed_keys_returns_dotted_paths(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    _bootstrap(p)
    schema = config.load(p)
    keys = set(config.list_keys(schema))
    assert "agent.max_concurrent" in keys
    assert "telegram.bot_token" in keys
    assert "daemon.auth_token" in keys
