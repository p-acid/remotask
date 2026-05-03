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
        # Long-form flags
        "git push --force",
        "git push origin main --force",
        "git reset --hard HEAD~1",
        "rm -rf /etc/passwd",
        "rm -rf /Users/somebody/important",
        "sudo whoami",
        "sudo apt install foo",
        # Short-form / permuted flags (the regex bypasses CodeRabbit flagged)
        "git push -f origin main",
        "git push -fu origin main",  # combined short flags
        "git clean -fd",
        "git clean -xfd",
        "git clean -d -f",  # split short flags
        "git clean -d --force",
        "rm -fr /etc",  # f before r in short bundle
        "rm -r -f /etc",  # split short flags
        "rm -r --force /etc",
        "rm --recursive --force /etc",
        # Chained / piped — must still be caught even when wrapped in benign prefix
        "git status; git push --force",
        "true && rm -rf /etc",
        "false || sudo whoami",
        "git push --force | tee /tmp/log",
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
        "git clean --dry-run",
        "rm -rf /tmp/scratch",  # /tmp is exempt
        "rm -rf /tmp",  # literal /tmp also exempt
        "rm -rf /var/folders/abc",  # macOS tmp dirs exempt
        "rm -f relative/path",  # no recursive flag
        "rm -r relative/path",  # no force flag
        "sudoku --solve",  # head != sudo (tokenized)
        "echo sudo whoami",  # head=echo; token-based correctly allows
        "git log | grep --force",  # second segment head=grep, not git
    ],
)
def test_allowed_commands_have_no_deny_reason(command: str) -> None:
    assert deny_reason_for(command) is None, command


@pytest.mark.parametrize(
    "command",
    [
        'git commit -m "missing close quote',  # unbalanced quote
        "git push 'unterminated",
    ],
)
def test_unparseable_command_is_conservatively_rejected(command: str) -> None:
    """Defensive: if the agent hands us a shell string we can't tokenise we
    err on the side of blocking. This is the ``shlex.split`` ValueError
    branch — keeps the deny-list from being trivially bypassed via quote
    smuggling."""
    assert deny_reason_for(command) is not None, command


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
