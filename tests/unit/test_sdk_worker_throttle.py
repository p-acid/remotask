"""Unit coverage for the per-tool STEP throttle (R9 in research.md).

The driver emits at most one STEP line per tool name per
``_STEP_THROTTLE_SECONDS`` window so the topic doesn't fill with one-line
spam when an agent calls e.g. ``Read`` ten times in 200 ms.
"""
from __future__ import annotations

import io

from remotask.agent.sdk_worker import DriverState, should_emit_step


def _state() -> DriverState:
    return DriverState(issue_key="K", session_id="s", stdout=io.StringIO())


def test_first_emit_always_passes() -> None:
    s = _state()
    assert should_emit_step(s, "Read", now=100.0) is True


def test_second_within_window_is_throttled() -> None:
    s = _state()
    assert should_emit_step(s, "Read", now=100.0) is True
    # 0.5 s later → still within the 1 s window → throttled.
    assert should_emit_step(s, "Read", now=100.5) is False


def test_second_after_window_passes() -> None:
    s = _state()
    assert should_emit_step(s, "Read", now=100.0) is True
    # 1.5 s later → past the 1 s window → emit again.
    assert should_emit_step(s, "Read", now=101.5) is True


def test_different_tool_not_throttled_by_other_tool() -> None:
    s = _state()
    assert should_emit_step(s, "Read", now=100.0) is True
    # Different tool name within the same window — independent budget.
    assert should_emit_step(s, "Bash", now=100.1) is True


def test_burst_of_five_collapses_to_one_emit() -> None:
    s = _state()
    emits = sum(
        1
        for t in (100.0, 100.05, 100.1, 100.15, 100.2)
        if should_emit_step(s, "Read", now=t)
    )
    assert emits == 1


def test_post_tool_use_failure_emits_tool_result_event() -> None:
    """Driver-level: a PostToolUseFailure hook event must produce an
    ``EVENT agent.tool_result`` line carrying ``is_error: true`` so the
    daemon-side audit row reflects the failure (data-model.md §2)."""
    import asyncio
    import io
    import json

    from remotask.agent.sdk_worker import DriverState, make_post_tool_use_hook

    state = DriverState(issue_key="K", session_id="s", stdout=io.StringIO())
    hook = make_post_tool_use_hook(state)

    async def run() -> None:
        await hook(
            {
                "hook_event_name": "PostToolUseFailure",
                "tool_name": "Bash",
                "tool_input": {"command": "false"},
            },  # type: ignore[arg-type]
            None,
            {"signal": None},  # type: ignore[arg-type]
        )

    asyncio.run(run())

    out = state.stdout.getvalue()
    event_lines = [ln for ln in out.splitlines() if ln.startswith("EVENT ")]
    assert len(event_lines) == 1, event_lines
    type_token, payload_str = event_lines[0].removeprefix("EVENT ").split(" ", 1)
    assert type_token == "agent.tool_result"
    payload = json.loads(payload_str)
    assert payload["is_error"] is True
    assert payload["tool"] == "Bash"
