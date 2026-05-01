"""Thin async wrapper around the three Telegram Bot API methods we use.

Per ``contracts/telegram-protocol.md`` the daemon only ever calls ``getUpdates``,
``createForumTopic``, and ``sendMessage``. The wrapper:

- enforces a minimum 50ms gap between outbound calls (rate-limit politeness),
- honours HTTP 429 ``retry_after``,
- raises a typed ``TelegramAPIError`` on Telegram-side failure so callers can
  distinguish "transport is fine but the Bot API said no" from a network blip.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

# Public Telegram Bot API endpoint. Single host, HTTPS only.
_BASE_URL = "https://api.telegram.org"
# Minimum spacing between outbound calls (50ms — see telegram-protocol.md).
_OUTBOUND_MIN_GAP = 0.05


class TelegramAPIError(Exception):
    """Raised when the Bot API returns ``ok: false`` or an HTTP error.

    ``retry_after`` is set on HTTP 429 responses so callers can sleep before
    retrying; ``error_code`` and ``description`` come from the Telegram payload.
    """

    def __init__(
        self,
        method: str,
        *,
        error_code: int | None = None,
        description: str = "",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(f"telegram {method} failed: {error_code} {description}")
        self.method = method
        self.error_code = error_code
        self.description = description
        self.retry_after = retry_after


@dataclass
class Update:
    update_id: int
    message: dict[str, Any] | None


@dataclass
class ForumTopic:
    message_thread_id: int
    name: str


class TelegramClient:
    """Minimal async client for the three methods we call."""

    def __init__(
        self,
        bot_token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = _BASE_URL,
    ) -> None:
        if not bot_token:
            raise ValueError("bot_token is required")
        self._bot_token = bot_token
        self._client = httpx.AsyncClient(
            base_url=f"{base_url}/bot{bot_token}",
            transport=transport,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
        )
        self._send_lock = asyncio.Lock()
        self._last_send_at = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- Bot API methods -----------------------------------------------------

    async def get_updates(
        self,
        offset: int | None = None,
        timeout: int = 25,
        allowed_updates: list[str] | None = None,
    ) -> list[Update]:
        """Long-poll for inbound updates.

        ``timeout`` is the long-poll seconds passed to Telegram; the HTTP read
        timeout on the underlying client is wider so we don't time out before
        Telegram does.
        """
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        if allowed_updates is not None:
            params["allowed_updates"] = allowed_updates
        result = await self._call("getUpdates", params, throttle=False)
        out: list[Update] = []
        for raw in result:
            out.append(Update(update_id=int(raw["update_id"]), message=raw.get("message")))
        return out

    async def create_forum_topic(self, chat_id: int, name: str) -> ForumTopic:
        """Create a forum topic; returns ``message_thread_id``."""
        result = await self._call(
            "createForumTopic", {"chat_id": chat_id, "name": name}, throttle=True
        )
        return ForumTopic(message_thread_id=int(result["message_thread_id"]), name=str(result["name"]))

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        message_thread_id: int | None = None,
    ) -> dict[str, Any]:
        """Post text to the main chat or a topic."""
        params: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if message_thread_id is not None:
            params["message_thread_id"] = message_thread_id
        return await self._call("sendMessage", params, throttle=True)

    # ---- internals -----------------------------------------------------------

    async def _call(
        self, method: str, params: dict[str, Any], *, throttle: bool
    ) -> Any:
        if throttle:
            await self._respect_outbound_gap()
        try:
            resp = await self._client.post(f"/{method}", json=params)
        except httpx.HTTPError as e:
            raise TelegramAPIError(method, description=str(e)) from e
        if resp.status_code == 429:
            retry = self._parse_retry_after(resp)
            raise TelegramAPIError(
                method,
                error_code=429,
                description="rate limited",
                retry_after=retry,
            )
        try:
            body = resp.json()
        except Exception as e:
            raise TelegramAPIError(method, description=f"non-json body: {e}") from e
        if not body.get("ok"):
            raise TelegramAPIError(
                method,
                error_code=body.get("error_code"),
                description=str(body.get("description", "")),
            )
        return body.get("result")

    async def _respect_outbound_gap(self) -> None:
        async with self._send_lock:
            now = asyncio.get_running_loop().time()
            wait = self._last_send_at + _OUTBOUND_MIN_GAP - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_send_at = asyncio.get_running_loop().time()

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> float | None:
        # Telegram puts retry_after both in the JSON body's ``parameters`` and in
        # the standard Retry-After header. We try the body first.
        try:
            body = resp.json()
            params = body.get("parameters") or {}
            ra = params.get("retry_after")
            if ra is not None:
                return float(ra)
        except Exception:
            pass
        header = resp.headers.get("retry-after")
        if header:
            try:
                return float(header)
            except ValueError:
                return None
        return None
