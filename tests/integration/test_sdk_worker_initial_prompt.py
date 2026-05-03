"""FR-017 (a): the driver's first SDK message MUST be ``/work-start <key>``.

We don't actually spin up the ``claude`` CLI here — instead we hand the
driver a duck-typed mock client that records ``query()`` calls and yields
a single Stop-shaped message so the run loop terminates immediately.
"""
from __future__ import annotations

import asyncio
import io
from collections import deque
from typing import Any

import pytest

from remotask.agent.sdk_worker import DriverState, SdkDriver


class MockClient:
    """Duck-typed minimal stand-in for ``ClaudeSDKClient``.

    Captures ``query()`` calls in ``self.queries`` and yields the messages
    queued via ``feed()`` from ``receive_messages()``.
    """

    def __init__(self) -> None:
        self.queries: list[str] = []
        self._inbox: deque[Any] = deque()
        self._closed = asyncio.Event()
        self.interrupt_calls: int = 0

    def feed(self, msg: Any) -> None:
        self._inbox.append(msg)

    def close(self) -> None:
        self._closed.set()

    async def query(self, prompt: str, session_id: str = "default") -> None:
        self.queries.append(prompt)

    async def receive_messages(self):
        while True:
            while self._inbox:
                yield self._inbox.popleft()
            if self._closed.is_set() and not self._inbox:
                return
            await asyncio.sleep(0)

    async def interrupt(self) -> None:
        self.interrupt_calls += 1


@pytest.mark.asyncio
async def test_initial_prompt_is_work_start_with_issue_key() -> None:
    state = DriverState(
        issue_key="ZXTL-1234",
        session_id="sess-1",
        stdout=io.StringIO(),
    )
    client = MockClient()
    driver = SdkDriver(client, state=state)
    client.close()  # no inbox messages → loop exits immediately

    rc = await driver.run()
    assert rc == 0

    assert client.queries == ["/work-start ZXTL-1234"], (
        f"first SDK query was {client.queries!r}; expected /work-start ZXTL-1234"
    )
