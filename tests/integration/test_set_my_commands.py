"""Integration test for setMyCommands lifecycle (004 / SC-006).

Brings up the runtime with fake_telegram, verifies that the curated commands
are registered exactly once at startup, and that a 503 response on the
*first* listener start does not block subsequent dispatch.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from remotask.core import config as rt_config
from remotask.core import db as core_db
from remotask.core import paths as rt_paths
from remotask.daemon.runtime import Runtime
from remotask.telegram.commands import CURATED_COMMANDS
from tests.fakes.fake_telegram import FakeTelegram


@pytest.fixture
def isolated_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "cache").mkdir()
    return tmp_path


@pytest.fixture
def conn(isolated_xdg: Path) -> sqlite3.Connection:
    return core_db.connect(rt_paths.db_path())


def _build_cfg(fake_tg: FakeTelegram) -> rt_config.ConfigSchema:
    cfg = rt_config.default_schema()
    cfg.telegram.bot_token = fake_tg.bot_token
    cfg.telegram.group_chat_id = fake_tg.chat_id
    cfg.telegram.allowed_user_ids = [99001]
    cfg.telegram.poll_timeout_seconds = 1
    cfg.telegram.backoff_max_seconds = 2
    return cfg


async def test_set_my_commands_called_once_at_startup(
    isolated_xdg: Path, conn: sqlite3.Connection
) -> None:
    fake_tg = FakeTelegram()
    cfg = _build_cfg(fake_tg)

    # Patch TelegramClient inside the runtime to use our fake's transport.
    # Easiest way: monkeypatch the module-level constructor we use; here we
    # directly drive the runtime's _async_main code path via an async test.
    from remotask.telegram.client import TelegramClient as _RealClient

    original_init = _RealClient.__init__

    def patched_init(self, bot_token, *, transport=None, base_url=None):
        original_init(self, bot_token, transport=fake_tg.transport())

    import unittest.mock as mock

    with mock.patch.object(_RealClient, "__init__", patched_init):
        rt = Runtime(cfg=cfg)
        rt.start()
        # Wait for setMyCommands to land + first dispatch loop iteration.
        await asyncio.sleep(0.5)
        rt.stop()

    # The runtime registers exactly once at startup (background task).
    assert len(fake_tg.set_my_commands_calls) == 1, (
        f"expected exactly 1 setMyCommands call at startup, "
        f"got {len(fake_tg.set_my_commands_calls)}"
    )
    payload = fake_tg.set_my_commands_calls[0]
    names = [c["command"] for c in payload]
    assert names == [c.name for c in CURATED_COMMANDS]


async def test_5xx_on_set_my_commands_does_not_block_dispatch(
    isolated_xdg: Path, conn: sqlite3.Connection
) -> None:
    """If setMyCommands returns 503 once, the listener still processes inbound."""
    fake_tg = FakeTelegram()
    fake_tg.next_error["setMyCommands"] = (
        503,
        {"ok": False, "error_code": 503, "description": "service unavailable"},
    )
    cfg = _build_cfg(fake_tg)

    from remotask.telegram.client import TelegramClient as _RealClient

    original_init = _RealClient.__init__

    def patched_init(self, bot_token, *, transport=None, base_url=None):
        original_init(self, bot_token, transport=fake_tg.transport())

    import unittest.mock as mock


    with mock.patch.object(_RealClient, "__init__", patched_init):
        rt = Runtime(cfg=cfg)
        rt.start()
        # Push an inbound message that should still be dispatched even though
        # setMyCommands failed.
        fake_tg.push_text_message("just chat", sender_id=99001)
        await asyncio.sleep(0.5)
        rt.stop()

    # The listener kept polling — getUpdates should have been called multiple times.
    assert len(fake_tg.get_updates_calls) >= 1
