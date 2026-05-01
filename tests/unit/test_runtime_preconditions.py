"""Unit tests for ``Runtime.validate_listener_preconditions``.

Pins the FR-003 fail-closed posture: empty/invalid config refuses to start the
listener and surfaces a precise field name (without leaking values).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from remotask.core import config as rt_config
from remotask.daemon.runtime import (
    ListenerPreconditionError,
    validate_listener_preconditions,
)


def _good_cfg() -> rt_config.ConfigSchema:
    schema = rt_config.default_schema()
    schema.telegram.bot_token = "123456789:abcdefghijklmnopqrstuvwxyz0123456"
    schema.telegram.group_chat_id = -1000000000001
    schema.telegram.allowed_user_ids = [99001]
    return schema


def test_good_cfg_passes() -> None:
    validate_listener_preconditions(_good_cfg())


def test_empty_bot_token_fails() -> None:
    cfg = _good_cfg()
    cfg.telegram.bot_token = ""
    with pytest.raises(ListenerPreconditionError) as ei:
        validate_listener_preconditions(cfg)
    assert ei.value.field == "telegram.bot_token"


def test_zero_chat_id_fails() -> None:
    cfg = _good_cfg()
    cfg.telegram.group_chat_id = 0
    with pytest.raises(ListenerPreconditionError) as ei:
        validate_listener_preconditions(cfg)
    assert ei.value.field == "telegram.group_chat_id"


def test_empty_whitelist_fails_closed() -> None:
    cfg = _good_cfg()
    cfg.telegram.allowed_user_ids = []
    with pytest.raises(ListenerPreconditionError) as ei:
        validate_listener_preconditions(cfg)
    assert ei.value.field == "telegram.allowed_user_ids"


def test_loose_config_file_mode_fails(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("# placeholder\n", encoding="utf-8")
    cfg_path.chmod(0o644)
    with pytest.raises(ListenerPreconditionError) as ei:
        validate_listener_preconditions(_good_cfg(), config_path=cfg_path)
    assert ei.value.field == "config_path"


def test_correct_config_file_mode_passes(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("# placeholder\n", encoding="utf-8")
    cfg_path.chmod(0o600)
    validate_listener_preconditions(_good_cfg(), config_path=cfg_path)


def test_error_does_not_carry_secret_value() -> None:
    # The error message contains the field name, never the field value.
    cfg = _good_cfg()
    cfg.telegram.bot_token = ""
    try:
        validate_listener_preconditions(cfg)
    except ListenerPreconditionError as e:
        assert "value is empty" in str(e)
        # Defensive: should not contain the literal token from a good cfg.
        assert "123456789" not in str(e)
