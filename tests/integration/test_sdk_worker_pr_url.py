"""FR-017 (b): assistant text containing ``PR_URL=<url>`` flows through the
driver to stdout exactly once and reaches the daemon's existing 003 PR-URL
parser unchanged.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

import pytest

from remotask.agent.sdk_worker import DriverState, SdkDriver
from tests.integration.test_sdk_worker_initial_prompt import MockClient


@dataclass
class FakeAssistantMessage:
    """Class-shaped message: a single text block list under .content."""

    content: list[Any]


@dataclass
class FakeTextBlock:
    text: str


@pytest.mark.asyncio
async def test_pr_url_in_assistant_text_is_emitted_once() -> None:
    state = DriverState(
        issue_key="ZXTL-42",
        session_id="sess-pr",
        stdout=io.StringIO(),
    )
    client = MockClient()
    # First message: assistant text containing the URL pattern.
    client.feed(
        FakeAssistantMessage(
            content=[
                FakeTextBlock(
                    text="Created PR_URL=https://github.com/x/y/pull/42 successfully"
                )
            ]
        )
    )
    # Second message: another assistant text with a different URL — should be
    # ignored because we emit exactly once per session.
    client.feed(
        FakeAssistantMessage(
            content=[
                FakeTextBlock(text="oops, also PR_URL=https://github.com/x/y/pull/9999")
            ]
        )
    )
    client.close()

    driver = SdkDriver(client, state=state)
    rc = await driver.run()
    assert rc == 0

    out = state.stdout.getvalue()
    pr_lines = [
        ln for ln in out.splitlines() if ln.startswith("PR_URL=")
    ]
    assert pr_lines == ["PR_URL=https://github.com/x/y/pull/42"], (
        f"expected exactly one PR_URL line, got {pr_lines!r}"
    )


@pytest.mark.asyncio
async def test_no_pr_url_means_no_emission() -> None:
    state = DriverState(
        issue_key="ZXTL-43",
        session_id="sess-no-pr",
        stdout=io.StringIO(),
    )
    client = MockClient()
    client.feed(
        FakeAssistantMessage(content=[FakeTextBlock(text="just chatter, no URL")])
    )
    client.close()

    driver = SdkDriver(client, state=state)
    rc = await driver.run()
    assert rc == 0

    out = state.stdout.getvalue()
    assert "PR_URL=" not in out
