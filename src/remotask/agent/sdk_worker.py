"""007 SDK worker driver — bridges ``claude-agent-sdk`` ↔ daemon stdout protocol.

Spawned by ``daemon/worker.py`` as a child subprocess (one per active session).
The daemon hands us:

- ``REMOTASK_ISSUE_KEY`` (env) — the Jira issue key used to compose the
  initial slash-skill prompt ``/work-start <key>``.
- ``REMOTASK_SESSION_ID`` (env) — the session id, included in audit payloads
  for cross-references.
- ``cwd`` set to the per-session worktree.

We translate the SDK's bidirectional event stream into the line-oriented
stdout protocol the daemon already understands (see
``specs/007-agent-sdk-integration/contracts/sdk-worker-protocol.md``):

- assistant text matching ``PR_URL=(\\S+)`` → stdout ``PR_URL=<url>`` (003).
- each ``PostToolUse`` hook → stdout ``EVENT agent.tool_use {...}`` (always)
  + a throttled ``STEP <body>`` line (007).
- ``PostToolUseFailure`` → stdout ``EVENT agent.tool_result {is_error: true}``.
- ``Stop`` hook → stdout ``EVENT agent.stop {...}`` + ``FINAL <i> natural`` (007).
- SIGUSR1 → ``client.interrupt()`` → ``EVENT agent.interrupt {...}``
  + ``FINAL <i> operator_stop``, exit 0 (003 cooperative ladder, R3).

The driver enforces the constitution §VI deny-list via a ``PreToolUse`` hook
matching ``Bash`` so even under ``permission_mode="bypassPermissions"`` the
banned commands cannot run (R2).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Any, TextIO

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher
from claude_agent_sdk.types import (
    HookContext,
    HookInput,
    HookJSONOutput,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PR_URL_RE: re.Pattern[str] = re.compile(r"PR_URL=(\S+)")
_STEP_THROTTLE_SECONDS: float = 1.0
_INTERRUPT_DRAIN_TIMEOUT: float = 5.0

# 헌법 §VI deny-list — these patterns are rejected at the PreToolUse hook
# regardless of permission_mode. Operator-side overrides require a separate
# spec/feature.
_DENY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bgit\s+push\s+.*--force(?!-with-lease)"),
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f"),
    re.compile(r"\brm\s+-rf\s+/(?!tmp/|var/folders/)"),
    re.compile(r"\bsudo(\s|$)"),
]


# ---------------------------------------------------------------------------
# Driver state (mutable; lives for the lifetime of one session)
# ---------------------------------------------------------------------------


@dataclass
class DriverState:
    """Per-process mutable state. Kept out of module globals to keep tests pure."""

    issue_key: str
    session_id: str
    stdout: TextIO
    iter: int = 0
    pr_url_emitted: bool = False
    last_step_emit: dict[str, float] = field(default_factory=dict)
    interrupt_requested: asyncio.Event = field(default_factory=asyncio.Event)


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested directly)
# ---------------------------------------------------------------------------


def deny_reason_for(command: str) -> str | None:
    """Return a deny reason if ``command`` matches any deny-list pattern; else None."""
    for pat in _DENY_PATTERNS:
        if pat.search(command):
            return f"blocked by remotask deny-list: {pat.pattern}"
    return None


def step_body_for(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Produce a one-line human-readable STEP body for a tool invocation."""
    if tool_name == "Bash":
        cmd = str(tool_input.get("command", "")).splitlines()[0][:80]
        body = f"Bash: {cmd}" if cmd else "Bash"
    elif tool_name in ("Edit", "Write", "MultiEdit"):
        path = str(tool_input.get("file_path", ""))[:200]
        body = f"{tool_name}: {path}" if path else tool_name
    elif tool_name == "Read":
        path = str(tool_input.get("file_path", ""))[:200]
        body = f"Read: {path}" if path else "Read"
    else:
        body = tool_name
    return body[:500]


def should_emit_step(
    state: DriverState, tool_name: str, *, now: float
) -> bool:
    """Per-tool throttle (R9): at most one STEP per tool per second."""
    last = state.last_step_emit.get(tool_name, 0.0)
    if now - last < _STEP_THROTTLE_SECONDS:
        return False
    state.last_step_emit[tool_name] = now
    return True


def scan_pr_url(text: str) -> str | None:
    """Find the first ``PR_URL=<url>`` in an assistant text block, or None."""
    m = _PR_URL_RE.search(text)
    return m.group(1) if m else None


def _emit(state: DriverState, line: str) -> None:
    """Write one line to stdout with trailing newline + flush.

    All driver-side stdout writes flow through this so a fragment cannot leak
    out half-formatted (helps the daemon-side parser stay strict).
    """
    state.stdout.write(line + "\n")
    state.stdout.flush()


def _emit_event(state: DriverState, type_: str, payload: dict[str, Any]) -> None:
    _emit(state, f"EVENT {type_} {json.dumps(payload, separators=(',', ':'))}")


# ---------------------------------------------------------------------------
# Hook factories — each returns an async callback closing over DriverState
# ---------------------------------------------------------------------------


def make_deny_list_guard(state: DriverState):
    async def deny_list_guard(
        hook_input: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> HookJSONOutput:
        tool_input = hook_input.get("tool_input", {}) or {}
        command = str(tool_input.get("command", ""))
        reason = deny_reason_for(command)
        if reason is None:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            },
        }

    return deny_list_guard


def make_post_tool_use_hook(state: DriverState):
    async def on_post_tool_use(
        hook_input: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> HookJSONOutput:
        state.iter += 1
        tool_name = str(hook_input.get("tool_name", "?"))
        tool_input = hook_input.get("tool_input", {}) or {}
        is_error = bool(hook_input.get("is_interrupt", False)) or (
            hook_input.get("hook_event_name") == "PostToolUseFailure"
        )

        # EVENT is always emitted (full audit trail, no throttle).
        if is_error:
            _emit_event(
                state,
                "agent.tool_result",
                {"tool": tool_name, "iter": state.iter, "is_error": True},
            )
        else:
            _emit_event(
                state,
                "agent.tool_use",
                {"tool": tool_name, "iter": state.iter},
            )

        # STEP is throttled per-tool to keep the topic readable (R9).
        if should_emit_step(state, tool_name, now=time.monotonic()):
            _emit(state, f"STEP {step_body_for(tool_name, tool_input)}")
        return {}

    return on_post_tool_use


def make_stop_hook(state: DriverState):
    async def on_stop(
        hook_input: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> HookJSONOutput:
        # If an interrupt was already in flight, the watchdog handles the
        # FINAL emission with reason="operator_stop". Don't double-emit here.
        if state.interrupt_requested.is_set():
            return {}
        _emit_event(
            state,
            "agent.stop",
            {"iter": state.iter, "reason": "natural"},
        )
        _emit(state, f"FINAL {state.iter} natural")
        return {}

    return on_stop


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def build_options(state: DriverState) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        permission_mode="bypassPermissions",
        system_prompt={"type": "preset", "preset": "claude_code"},
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="Bash", hooks=[make_deny_list_guard(state)])
            ],
            "PostToolUse": [HookMatcher(hooks=[make_post_tool_use_hook(state)])],
            "PostToolUseFailure": [
                HookMatcher(hooks=[make_post_tool_use_hook(state)])
            ],
            "Stop": [HookMatcher(hooks=[make_stop_hook(state)])],
        },
    )


class SdkDriver:
    """Orchestrates one SDK session.

    The client is injected so tests can pass a mock instead of constructing
    a real ``ClaudeSDKClient`` (which would spawn the ``claude`` CLI).
    """

    def __init__(
        self,
        client: Any,  # duck-typed: ClaudeSDKClient or a test double
        *,
        state: DriverState,
    ) -> None:
        self.client = client
        self.state = state

    async def run(self) -> int:
        """Drive the session to completion. Returns the desired exit code (0 or 1)."""
        # Pin the SDK session id to ours so the request never falls back to
        # the SDK's "default" session — the daemon's audit/lock model assumes
        # a 1:1 mapping between session_events.session_id and the SDK side.
        await self.client.query(
            f"/work-start {self.state.issue_key}",
            session_id=self.state.session_id,
        )
        watchdog = asyncio.create_task(self._interrupt_watchdog())
        try:
            async for msg in self.client.receive_messages():
                if self.state.interrupt_requested.is_set():
                    break
                self._handle_message(msg)
        finally:
            if self.state.interrupt_requested.is_set():
                # Let the watchdog finish emitting EVENT agent.interrupt + FINAL.
                # Suppress only the expected race conditions during shutdown;
                # log anything else so SDK regressions stay visible.
                try:
                    await asyncio.wait_for(watchdog, timeout=10.0)
                except (TimeoutError, asyncio.CancelledError):
                    pass
                except Exception as e:  # pragma: no cover — defensive log only
                    sys.stderr.write(
                        f"sdk_worker: watchdog cleanup error: {e!r}\n"
                    )
            else:
                watchdog.cancel()
                try:
                    await watchdog
                except asyncio.CancelledError:
                    pass
                except Exception as e:  # pragma: no cover — defensive log only
                    sys.stderr.write(
                        f"sdk_worker: watchdog teardown error: {e!r}\n"
                    )
        return 0

    def _handle_message(self, msg: Any) -> None:
        """Scan one SDK message for assistant text containing PR_URL."""
        if self.state.pr_url_emitted:
            return
        text = _extract_assistant_text(msg)
        if not text:
            return
        url = scan_pr_url(text)
        if url is None:
            return
        _emit(self.state, f"PR_URL={url}")
        self.state.pr_url_emitted = True

    async def _interrupt_watchdog(self) -> None:
        await self.state.interrupt_requested.wait()
        # Try the SDK interrupt FIRST, then emit the audit event. The audit
        # row therefore reflects an *attempted* interrupt that has already
        # returned (or errored). Emitting before the await would have logged
        # a successful-looking interrupt even on timeout/SDK failure.
        try:
            await asyncio.wait_for(
                self.client.interrupt(), timeout=_INTERRUPT_DRAIN_TIMEOUT
            )
        except TimeoutError:
            sys.stderr.write(
                "sdk_worker: client.interrupt() timed out — emitting FINAL anyway\n"
            )
        except Exception as e:  # pragma: no cover — defensive log only
            sys.stderr.write(f"sdk_worker: client.interrupt() failed: {e!r}\n")
        _emit_event(
            self.state,
            "agent.interrupt",
            {"iter_at_interrupt": self.state.iter},
        )
        _emit(self.state, f"FINAL {self.state.iter} operator_stop")


def _extract_assistant_text(msg: Any) -> str:
    """Best-effort text extraction across the SDK's message shapes.

    The SDK yields typed message objects (``AssistantMessage`` etc.). We probe
    a small set of shapes so the driver works against the current API and
    stays resilient to minor type-renames in future SDK versions.
    """
    # Class-style: AssistantMessage with a list of content blocks.
    content = getattr(msg, "content", None)
    if content is not None:
        parts: list[str] = []
        if isinstance(content, list):
            for block in content:
                t = getattr(block, "text", None)
                if isinstance(t, str):
                    parts.append(t)
                elif isinstance(block, dict):
                    bt = block.get("text")
                    if isinstance(bt, str):
                        parts.append(bt)
        elif isinstance(content, str):
            parts.append(content)
        if parts:
            return "\n".join(parts)
    # Dict-style fallback (custom transports yielding raw dicts).
    if isinstance(msg, dict):
        message = msg.get("message", {}) or {}
        c = message.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return "\n".join(b.get("text", "") for b in c if isinstance(b, dict))
    return ""


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------


def install_sigusr1_handler(state: DriverState) -> None:
    """Register a SIGUSR1 handler that flips the interrupt event.

    Per Python signal-safety: the handler does no I/O and only schedules a
    set on the asyncio Event from the running loop's thread.

    Must be called from inside the running event loop — Python ≥3.10 made
    ``asyncio.get_event_loop()`` deprecated outside one. The driver's
    ``main()`` invokes us under ``asyncio.run`` so ``get_running_loop`` is
    the canonical accessor.
    """
    loop = asyncio.get_running_loop()

    def _handler(_signum: int, _frame: object) -> None:
        # Schedule from the signal context — Event.set is thread-safe enough
        # for our purpose because asyncio Events use a deque + futures.
        loop.call_soon_threadsafe(state.interrupt_requested.set)

    signal.signal(signal.SIGUSR1, _handler)


# ---------------------------------------------------------------------------
# Production entrypoint
# ---------------------------------------------------------------------------


async def main() -> int:
    issue_key = os.environ.get("REMOTASK_ISSUE_KEY")
    session_id = os.environ.get("REMOTASK_SESSION_ID", "unknown")
    if not issue_key:
        sys.stderr.write("sdk_worker: REMOTASK_ISSUE_KEY missing\n")
        return 2

    state = DriverState(
        issue_key=issue_key,
        session_id=session_id,
        stdout=sys.stdout,
    )
    install_sigusr1_handler(state)

    options = build_options(state)
    async with ClaudeSDKClient(options) as client:
        driver = SdkDriver(client, state=state)
        return await driver.run()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
