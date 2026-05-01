"""In-process Telegram Bot API fake.

Used to drive the listener and dispatcher in integration tests without hitting
api.telegram.org. Built on ``httpx.MockTransport``, so it plugs into our
``TelegramClient(transport=...)`` ctor argument.

Capabilities:

- ``push_update(message_dict)`` — enqueue an inbound text message that the next
  ``getUpdates`` call will return.
- ``sent_messages`` — list of all ``sendMessage`` calls (for assertions).
- ``created_topics`` — list of all ``createForumTopic`` calls.
- Configurable: per-method failures (set ``next_error`` on a method to inject a
  one-shot HTTP error response).

Not modelled (out of scope for tests): photos/voice/edited messages, callback
queries. The listener ignores those anyway per the protocol contract.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class SentMessage:
    chat_id: int
    text: str
    message_thread_id: int | None = None


@dataclass
class CreatedTopic:
    chat_id: int
    name: str
    message_thread_id: int


@dataclass
class FakeTelegram:
    """Stateful fake; pass ``transport`` into ``TelegramClient``."""

    bot_token: str = "123456789:abcdefghijklmnopqrstuvwxyz0123456"
    chat_id: int = -1000000000001

    # Backing state
    _pending_updates: list[dict[str, Any]] = field(default_factory=list)
    _next_update_id: itertools.count = field(default_factory=lambda: itertools.count(1))
    _next_thread_id: itertools.count = field(default_factory=lambda: itertools.count(100))
    _next_message_id: itertools.count = field(default_factory=lambda: itertools.count(1))
    sent_messages: list[SentMessage] = field(default_factory=list)
    created_topics: list[CreatedTopic] = field(default_factory=list)
    # If set, the next call to that method returns the given (status, body).
    next_error: dict[str, tuple[int, dict[str, Any]]] = field(default_factory=dict)
    # Records every getUpdates call: list of (offset, timeout) tuples.
    get_updates_calls: list[tuple[int | None, int]] = field(default_factory=list)

    # ---- public test API ----------------------------------------------------

    def push_text_message(
        self,
        text: str,
        sender_id: int,
        *,
        chat_id: int | None = None,
        message_id: int | None = None,
    ) -> dict[str, Any]:
        """Enqueue a text message that will be returned by the next getUpdates."""
        msg = {
            "message_id": message_id if message_id is not None else next(self._next_message_id),
            "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
            "chat": {"id": chat_id if chat_id is not None else self.chat_id, "type": "supergroup"},
            "date": 1746115200,
            "text": text,
        }
        update = {"update_id": next(self._next_update_id), "message": msg}
        self._pending_updates.append(update)
        return msg

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handler)

    # ---- request handler ----------------------------------------------------

    def _handler(self, request: httpx.Request) -> httpx.Response:
        # path is /bot<TOKEN>/<method>
        path = request.url.path
        method = path.rsplit("/", 1)[-1]
        params: dict[str, Any] = {}
        if request.content:
            try:
                params = json.loads(request.content)
            except json.JSONDecodeError:
                params = {}

        if method in self.next_error:
            status, body = self.next_error.pop(method)
            return httpx.Response(status, json=body)

        if method == "getUpdates":
            return self._handle_get_updates(params)
        if method == "createForumTopic":
            return self._handle_create_forum_topic(params)
        if method == "sendMessage":
            return self._handle_send_message(params)
        # Unknown method — fail loudly so tests catch protocol drift.
        return httpx.Response(
            404, json={"ok": False, "error_code": 404, "description": f"unknown method {method}"}
        )

    def _handle_get_updates(self, params: dict[str, Any]) -> httpx.Response:
        offset = params.get("offset")
        timeout = int(params.get("timeout", 0))
        self.get_updates_calls.append((offset, timeout))
        # Telegram's contract: passing ``offset=N`` confirms updates with id < N
        # (they are removed and never returned again) and returns updates with
        # id >= N. So we drop anything strictly < offset, then return whatever
        # remains so the next poll keeps seeing it until acknowledged.
        if offset is not None:
            self._pending_updates = [
                u for u in self._pending_updates if u["update_id"] >= int(offset)
            ]
        updates = list(self._pending_updates)
        return httpx.Response(200, json={"ok": True, "result": updates})

    def _handle_create_forum_topic(self, params: dict[str, Any]) -> httpx.Response:
        thread_id = next(self._next_thread_id)
        name = str(params.get("name", ""))
        self.created_topics.append(
            CreatedTopic(chat_id=int(params["chat_id"]), name=name, message_thread_id=thread_id)
        )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"message_thread_id": thread_id, "name": name, "icon_color": 0},
            },
        )

    def _handle_send_message(self, params: dict[str, Any]) -> httpx.Response:
        message_id = next(self._next_message_id)
        thread = params.get("message_thread_id")
        self.sent_messages.append(
            SentMessage(
                chat_id=int(params["chat_id"]),
                text=str(params["text"]),
                message_thread_id=int(thread) if thread is not None else None,
            )
        )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": message_id,
                    "chat": {"id": int(params["chat_id"])},
                    "text": str(params["text"]),
                    "message_thread_id": thread,
                },
            },
        )
