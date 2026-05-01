"""Telegram long-poll listener.

This is one asyncio task that loops calling ``getUpdates`` and hands each
message off to the dispatcher. The listener is the *only* writer of inbound
messages into the dispatcher — there are no callbacks or webhooks here.

Backoff is exponential with a configurable cap (R8 in research.md). On a
successful poll we reset ``consecutive_failures``; on a failed poll we double
the wait time, with a small jitter, capped at ``backoff_max_seconds``. The
``listener_degraded`` marker is added by US5 once we have ≥10 consecutive
failures.
"""
from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from remotask.daemon.listener_state import HeartbeatWriter, ListenerState
from remotask.telegram.client import TelegramAPIError, TelegramClient

_log = structlog.get_logger().bind(component="listener")

_BACKOFF_BASE = 1.0  # seconds — first retry waits ~1s
_DEGRADED_THRESHOLD = 10
_DEGRADED_LOG_INTERVAL = 300.0  # 5 minutes between degraded warnings


class Listener:
    """Owns the long-poll loop and the persisted listener state.

    Parameters
    ----------
    client:
        TelegramClient instance bound to the bot token in config.
    chat_id:
        Configured group chat id; messages from any other chat are ignored.
    on_message:
        Async function called once per inbound text message — typically
        ``dispatcher.dispatch``.
    poll_timeout_seconds, backoff_max_seconds:
        From ``cfg.telegram``.
    whitelist_size:
        Used only for the persisted state file (so ``status`` can show it).
    state_writer:
        Throttled writer that persists ``ListenerState`` snapshots.
    """

    def __init__(
        self,
        *,
        client: TelegramClient,
        chat_id: int,
        on_message: Callable[[dict[str, Any]], Awaitable[None]],
        poll_timeout_seconds: int,
        backoff_max_seconds: int,
        whitelist_size: int,
        state_writer: HeartbeatWriter | None = None,
        initial_offset: int = 0,
    ) -> None:
        self._client = client
        self._chat_id = chat_id
        self._on_message = on_message
        self._poll_timeout = poll_timeout_seconds
        self._backoff_max = backoff_max_seconds
        self._whitelist_size = whitelist_size
        self._state_writer = state_writer or HeartbeatWriter()
        self._offset = initial_offset
        self._stop_event = asyncio.Event()
        # ``_unpaused`` is set when the listener is allowed to poll. Pausing
        # via SIGUSR1 (CLI ``telegram stop``) clears it; ``telegram start``
        # sets it again. Started in the unpaused state so plain
        # ``listener.run()`` works without explicit unpause.
        self._unpaused = asyncio.Event()
        self._unpaused.set()
        self._last_degraded_log_at = 0.0
        self._state = ListenerState(
            running=False,
            whitelist_size=whitelist_size,
            last_update_id=initial_offset,
        )

    @property
    def state(self) -> ListenerState:
        return self._state

    def stop(self) -> None:
        """Signal the loop to exit cleanly after the current poll completes."""
        self._stop_event.set()
        # Make sure a paused listener wakes up so it can observe the stop.
        self._unpaused.set()

    def pause(self) -> None:
        """Tell the listener to stop accepting triggers (no new polling)."""
        self._unpaused.clear()
        self._state.running = False
        self._flush_state()

    def resume(self) -> None:
        """Re-enable polling after a previous pause."""
        self._state.running = True
        self._flush_state()
        self._unpaused.set()

    @property
    def paused(self) -> bool:
        return not self._unpaused.is_set()

    async def run(self) -> None:
        """Main long-poll loop. Returns when ``stop()`` is called."""
        self._state.running = True
        self._state.started_at = time.time()
        self._flush_state()

        consecutive_failures = 0
        while not self._stop_event.is_set():
            # Always yield so the cooperative scheduler can run other tasks
            # (notably the shutdown signal handler) even if every awaited call
            # below resolves synchronously — which happens with httpx's
            # MockTransport in tests and with very short long-poll responses.
            await asyncio.sleep(0)
            if self._stop_event.is_set():
                break
            # When paused (CLI ``telegram stop``), wait until either resumed
            # or stopped. We don't update last_poll_ok_at while paused so the
            # ``status`` command keeps showing the timestamp of the last
            # *real* poll.
            if not self._unpaused.is_set():
                await self._unpaused.wait()
                if self._stop_event.is_set():
                    break
            try:
                # ``offset`` of None on the first call means "all available";
                # subsequent calls use ``last_update_id + 1`` to acknowledge.
                offset = self._offset + 1 if self._offset > 0 else None
                updates = await self._client.get_updates(
                    offset=offset,
                    timeout=self._poll_timeout,
                    allowed_updates=["message"],
                )
            except TelegramAPIError as e:
                consecutive_failures += 1
                self._state.consecutive_failures = consecutive_failures
                # Mark degraded on the 10th consecutive failure (R8); the flag
                # surfaces in ``remotask telegram status`` so the operator
                # learns the listener is in trouble without paging on every
                # retry.
                if consecutive_failures >= _DEGRADED_THRESHOLD:
                    self._state.degraded = True
                    self._maybe_log_degraded(consecutive_failures, str(e))
                self._flush_state()
                wait = self._backoff_seconds(consecutive_failures, e)
                _log.warning(
                    "listener.poll_failed",
                    error=str(e),
                    consecutive_failures=consecutive_failures,
                    backoff_seconds=round(wait, 2),
                )
                await self._sleep_or_stop(wait)
                continue

            consecutive_failures = 0
            self._state.consecutive_failures = 0
            self._state.degraded = False
            self._state.last_poll_ok_at = time.time()

            for update in updates:
                if update.update_id > self._offset:
                    self._offset = update.update_id
                    self._state.last_update_id = update.update_id
                if update.message is None:
                    continue
                if (update.message.get("chat") or {}).get("id") != self._chat_id:
                    # Ignore messages from any chat that isn't the configured one.
                    continue
                if "text" not in update.message:
                    # Photos / voice / etc. — silently ignored per protocol contract.
                    continue
                try:
                    await self._on_message(update.message)
                except Exception as e:  # pragma: no cover — defensive
                    _log.exception("listener.dispatch_failed", error=str(e))

            self._flush_state()

        self._state.running = False
        self._flush_state()

    # ---- internals -----------------------------------------------------------

    async def _sleep_or_stop(self, seconds: float) -> None:
        """Sleep for ``seconds``, but bail out early if ``stop()`` is signalled."""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except TimeoutError:
            return

    def _backoff_seconds(self, attempt: int, err: TelegramAPIError) -> float:
        """Exponential backoff with jitter; honours Telegram's retry_after when set."""
        if err.retry_after is not None:
            return min(float(err.retry_after), float(self._backoff_max))
        # 1s, 2s, 4s, … capped.
        base = min(_BACKOFF_BASE * (2 ** (attempt - 1)), float(self._backoff_max))
        # ±20% jitter to avoid thundering herd on shared outages.
        jitter = base * 0.2 * (random.random() - 0.5)
        return max(0.1, base + jitter)

    def _flush_state(self) -> None:
        self._state_writer.maybe_write(self._state, now=time.time())

    def _maybe_log_degraded(self, failures: int, last_error: str) -> None:
        """Emit a single ``listener_degraded`` warning at most every 5 minutes."""
        now = time.time()
        if now - self._last_degraded_log_at < _DEGRADED_LOG_INTERVAL:
            return
        self._last_degraded_log_at = now
        # Use the audit logger so ``audit.log`` carries a record of degradation
        # alongside the structured stderr line.
        from remotask.daemon import audit as rt_audit

        rt_audit.log_unbound_event(
            rt_audit.EV_LISTENER_DEGRADED,
            {"consecutive_failures": failures, "last_error": last_error},
        )
        _log.warning(
            "listener.degraded",
            consecutive_failures=failures,
            last_error=last_error,
        )
