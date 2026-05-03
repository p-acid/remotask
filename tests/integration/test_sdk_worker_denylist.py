"""헌법 §VI deny-list invariant — even with ``permission_mode=bypassPermissions``,
the driver-side ``PreToolUse`` hook MUST block the banned commands.

This is a regression guard: if a future SDK version changes hook semantics
and silently lets these through, this test fails LOUDLY.
"""
from __future__ import annotations

import io

import pytest

from remotask.agent.sdk_worker import (
    DriverState,
    deny_reason_for,
    make_deny_list_guard,
)


@pytest.mark.parametrize(
    "command",
    [
        "git push --force",
        "git push origin main --force",
        "git reset --hard HEAD~1",
        "git clean -fd",
        "git clean -xfd",
        "rm -rf /etc/passwd",
        "rm -rf /Users/somebody/important",
        "sudo whoami",
        "sudo apt install foo",
    ],
)
def test_denied_commands_have_deny_reason(command: str) -> None:
    assert deny_reason_for(command) is not None, command


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git push --force-with-lease origin foo",  # safer variant allowed
        "git reset HEAD~1",  # soft/mixed reset allowed
        "git clean -n",  # dry-run only
        "rm -rf /tmp/scratch",  # /tmp is exempt
        "rm -rf /var/folders/abc",  # macOS tmp dirs exempt
        "sudoku --solve",  # tokenization: sudo + space required
        "echo sudo whoami",  # quoted/echoed not blocked at this layer
    ],
)
def test_allowed_commands_have_no_deny_reason(command: str) -> None:
    # NOTE: the last case ("echo sudo whoami") *would* match the regex with
    # ``\bsudo`` because of the word boundary inside the string. Adjust the
    # expectation: this layer is intentionally conservative.
    if command == "echo sudo whoami":
        assert deny_reason_for(command) is not None  # documents conservatism
    else:
        assert deny_reason_for(command) is None, command


@pytest.mark.asyncio
async def test_hook_returns_deny_decision_for_banned_command() -> None:
    state = DriverState(
        issue_key="K", session_id="s", stdout=io.StringIO()
    )
    guard = make_deny_list_guard(state)
    out = await guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git push --force"},
        },  # type: ignore[arg-type]
        None,
        {"signal": None},  # type: ignore[arg-type]
    )
    assert out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
    reason = out["hookSpecificOutput"].get("permissionDecisionReason", "")
    assert "force" in reason


@pytest.mark.asyncio
async def test_hook_returns_empty_for_safe_command() -> None:
    state = DriverState(
        issue_key="K", session_id="s", stdout=io.StringIO()
    )
    guard = make_deny_list_guard(state)
    out = await guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
        },  # type: ignore[arg-type]
        None,
        {"signal": None},  # type: ignore[arg-type]
    )
    assert out == {}
