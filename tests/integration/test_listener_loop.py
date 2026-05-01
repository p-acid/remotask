"""Integration tests for the Telegram long-poll listener.

Drives the listener with the in-process ``FakeTelegram`` and asserts:

- inbound text messages reach the dispatcher exactly once,
- ``getUpdates`` ``offset`` advances after each batch (no replay),
- chat-id filtering rejects messages from other chats.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from remotask.daemon.listener import Listener
from remotask.daemon.listener_state import HeartbeatWriter
from remotask.telegram.client import TelegramClient
from tests.fakes.fake_telegram import FakeTelegram


@pytest.fixture
def fake_tg() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def client(fake_tg: FakeTelegram) -> TelegramClient:
    return TelegramClient(fake_tg.bot_token, transport=fake_tg.transport())


def _make_listener(
    *,
    fake_tg: FakeTelegram,
    client: TelegramClient,
    on_message,
    state_path: Path,
    poll_timeout: int = 1,
) -> Listener:
    writer = HeartbeatWriter(path=state_path)
    return Listener(
        client=client,
        chat_id=fake_tg.chat_id,
        on_message=on_message,
        poll_timeout_seconds=poll_timeout,
        backoff_max_seconds=2,
        whitelist_size=1,
        state_writer=writer,
    )


async def test_message_in_correct_chat_is_dispatched(
    tmp_path: Path, fake_tg: FakeTelegram, client: TelegramClient
) -> None:
    received: list[dict] = []

    async def on_message(msg: dict) -> None:
        received.append(msg)

    listener = _make_listener(
        fake_tg=fake_tg,
        client=client,
        on_message=on_message,
        state_path=tmp_path / "listener.state",
    )

    fake_tg.push_text_message("ZXTL-7", sender_id=99001)

    task = asyncio.create_task(listener.run())
    # Wait until the listener has captured the message — bounded by overall test timeout.
    for _ in range(50):
        if received:
            break
        await asyncio.sleep(0.05)
    listener.stop()
    await asyncio.wait_for(task, timeout=5.0)

    assert len(received) == 1
    assert received[0]["text"] == "ZXTL-7"
    assert listener.state.last_update_id > 0
    # The listener acknowledged the message: subsequent getUpdates calls should
    # be made with offset = last_update_id + 1.
    last_offset = listener.state.last_update_id
    assert any(
        call_offset == last_offset + 1
        for call_offset, _ in fake_tg.get_updates_calls
    )


async def test_message_from_other_chat_is_ignored(
    tmp_path: Path, fake_tg: FakeTelegram, client: TelegramClient
) -> None:
    received: list[dict] = []

    async def on_message(msg: dict) -> None:
        received.append(msg)

    listener = _make_listener(
        fake_tg=fake_tg,
        client=client,
        on_message=on_message,
        state_path=tmp_path / "listener.state",
    )

    fake_tg.push_text_message("ZXTL-7", sender_id=99001, chat_id=-9999999)
    fake_tg.push_text_message("ZXTL-8", sender_id=99001)  # default chat

    task = asyncio.create_task(listener.run())
    for _ in range(50):
        if received:
            break
        await asyncio.sleep(0.05)
    listener.stop()
    await asyncio.wait_for(task, timeout=5.0)

    assert len(received) == 1
    assert received[0]["text"] == "ZXTL-8"


async def test_persists_offset_via_heartbeat(
    tmp_path: Path, fake_tg: FakeTelegram, client: TelegramClient
) -> None:
    state_path = tmp_path / "listener.state"

    async def on_message(_: dict) -> None:  # noqa: ARG001
        return None

    listener = _make_listener(
        fake_tg=fake_tg,
        client=client,
        on_message=on_message,
        state_path=state_path,
    )

    fake_tg.push_text_message("ZXTL-7", sender_id=99001)

    task = asyncio.create_task(listener.run())
    for _ in range(50):
        if state_path.exists() and listener.state.last_update_id > 0:
            break
        await asyncio.sleep(0.05)
    listener.stop()
    await asyncio.wait_for(task, timeout=5.0)

    assert state_path.exists()
