"""FR-017 (c): SIGUSR1 → cooperative interrupt path.

We don't deliver a real OS signal here — instead we set the driver's
asyncio Event directly, which is exactly what the SIGUSR1 handler does.
This isolates the driver behaviour under test from the noisy details of
process signal delivery (those are exercised by 003's existing
``test_operator_stop`` integration suite).
"""
from __future__ import annotations

import asyncio
import io
import json

import pytest

from remotask.agent.sdk_worker import DriverState, SdkDriver
from tests.integration.test_sdk_worker_initial_prompt import MockClient


@pytest.mark.asyncio
async def test_interrupt_event_drives_cooperative_finalisation() -> None:
    state = DriverState(
        issue_key="ZXTL-CANCEL",
        session_id="sess-cancel",
        stdout=io.StringIO(),
    )
    # Make the iter advance non-trivially by hand (mimicking that some
    # tool calls already happened before the operator hit /cancel).
    state.iter = 7

    client = MockClient()
    driver = SdkDriver(client, state=state)

    async def trigger_after_tick():
        await asyncio.sleep(0.01)
        state.interrupt_requested.set()
        # Closing the inbox causes receive_messages() to exit cleanly so the
        # main loop returns after seeing the interrupt flag.
        client.close()

    trigger = asyncio.create_task(trigger_after_tick())
    rc = await driver.run()
    await trigger  # ensure no orphan task at teardown
    assert rc == 0

    # Drain stdout
    out = state.stdout.getvalue()
    lines = out.splitlines()

    # Exactly one EVENT agent.interrupt with the iter snapshot, exactly one
    # FINAL <iter> operator_stop, and no FINAL natural.
    interrupt_events = [
        ln for ln in lines if ln.startswith("EVENT agent.interrupt ")
    ]
    assert len(interrupt_events) == 1, (
        f"expected one agent.interrupt EVENT, got {interrupt_events!r}"
    )
    payload = json.loads(interrupt_events[0].split(" ", 2)[2])
    assert payload == {"iter_at_interrupt": 7}

    final_lines = [ln for ln in lines if ln.startswith("FINAL ")]
    assert final_lines == ["FINAL 7 operator_stop"], (
        f"expected one FINAL operator_stop line, got {final_lines!r}"
    )

    # client.interrupt() was awaited.
    assert client.interrupt_calls == 1


@pytest.mark.asyncio
async def test_natural_stop_when_no_interrupt() -> None:
    """If no interrupt is fired, the Stop hook (not under test here, exercised
    elsewhere) is the one that emits FINAL natural — the watchdog stays
    silent. This test simply asserts: no FINAL operator_stop comes out of a
    quiet inbox closing on its own.
    """
    state = DriverState(
        issue_key="ZXTL-NORMAL",
        session_id="sess-normal",
        stdout=io.StringIO(),
    )
    client = MockClient()
    client.close()

    driver = SdkDriver(client, state=state)
    rc = await driver.run()
    assert rc == 0
    assert "operator_stop" not in state.stdout.getvalue()
