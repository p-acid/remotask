# Data Model: `/cancel` Rename + `[KEY]` Prefix + Alias Deprecation

**Feature**: 005-dm-channel (narrowed scope — see spec.md "Scope decision")
**Date**: 2026-05-02
**Status**: Phase 1 design (rev 2)

## Schema delta vs V0001

**No new migration in this feature.** V0001 (from 001) covers everything. The feature reuses existing `sessions` columns; the only "new" data shape is in JSON payloads (audit events) and a tiny in-memory set on `Runtime`.

| Use site                                  | Column / file              | New semantics in 005 |
|-------------------------------------------|----------------------------|---|
| Slash command `/cancel`                   | `session_events.type`      | Existing `slash_command_received` row gains the value `cancel` in its `command` field |
| `/cancel` rejected from main chat         | `audit.log`                | `slash_command_rejected` row's `reason` field gains `main_chat_cancel` |
| Deprecated alias used                     | `audit.log`                | New unbound type `alias_deprecation_used` |
| Curated command registry                  | `telegram/commands.py`     | `CURATED_COMMANDS` becomes `(run, cancel, status)` (drop `done`) |
| Outbound message templates                | `daemon/topic.py`          | New helper `format_progress(issue_key, body)` applies `[KEY] ` prefix |

## Runtime in-memory state addition

`Runtime` (the singleton in `daemon/runtime.py`) gains one small in-memory set. It is not persisted; it is cleared on listener stop and on per-session terminal transition.

```python
class Runtime:
    # ... existing fields (operator_stop_in_flight, worker_pid_by_session, etc.)

    # 005 addition:

    # Idempotency for the deprecation WARNING. Members are tuples of
    # (alias_token, session_id). The first occurrence emits the WARNING
    # and an alias_deprecation_used audit row; subsequent occurrences on
    # the same session are silent. Cleared when the session terminates.
    alias_deprecation_warned: set[tuple[str, str]]
```

### Lifecycle of `alias_deprecation_warned`

| Stage                                           | Operation                                                     | Owner                |
|-------------------------------------------------|---------------------------------------------------------------|----------------------|
| Alias use detected (`/done`, `done`, `stop`, `finish`) | Check `(token, session_id) in set`. If absent: emit WARNING + audit, then add. If present: silent. | dispatcher (asyncio thread) |
| Session reaches terminal state                   | Drop all `(_, session_id)` tuples from set                    | sessions transition helper |
| Listener stop                                    | Set is dropped with the Runtime                               | n/a                  |
| Daemon restart                                   | Set lost (in-memory only); first alias use post-restart re-emits WARNING | recovery path        |

`alias_token` values (canonical lower-cased):

```python
ALIAS_TOKENS: frozenset[str] = frozenset({
    "/done",        # 004 slash form
    "done",         # 003 plain-text form
    "stop",         # 003 plain-text form
    "finish",       # 003 plain-text form
})
```

## Audit event taxonomy additions

One new event-type constant in `daemon/audit.py`:

| Type                       | Storage     | Payload fields |
|----------------------------|-------------|----------------|
| `alias_deprecation_used`   | `audit.log` | `{alias_token, canonical: "cancel", session_id, sender_id, message_id, chat_id, message_thread_id}` |

Two existing event types gain new field values:

| Event                       | Field         | New value           | Rationale |
|-----------------------------|---------------|---------------------|-----------|
| `slash_command_received`    | `command`     | `cancel`            | Canonical command introduced in 005 |
| `slash_command_rejected`    | `reason`      | `main_chat_cancel`  | `/cancel` posted in main chat (no topic context) |

The existing `main_chat_done` reason value is **retained** for audit lines produced by the deprecated `/done` alias — this lets reviewers grep "operators still using `/done`" via simple log analysis (R5).

`session_events.type` retains `slash_command_received`; the `command` discriminator carries the variation. No change to the `session_events` table shape.

## Curated command registry delta

`telegram/commands.py`:

```python
CURATED_COMMANDS: tuple[CuratedCommand, ...] = (
    CuratedCommand(
        name="run",
        description="Start a new session",
        requires_topic=False,
        requires_args=True,
    ),
    # 005 NEW
    CuratedCommand(
        name="cancel",
        description="Cancel an active session",
        requires_topic=True,
        requires_args=False,
    ),
    # 005 REMOVED: CuratedCommand(name="done", ...) — alias path still routes inbound, just not advertised
    CuratedCommand(
        name="status",
        description="Show active sessions",
        requires_topic=False,
        requires_args=False,
    ),
)
```

The `setMyCommands` payload is the same idempotent-overwrite call from 004; the bot's advertised command list flips from `(run, done, status)` to `(run, cancel, status)` on the next listener startup.

## Outbound message catalogue (where the `[KEY]` prefix applies)

The `[KEY]` prefix is applied via `topic.format_progress(issue_key, body)` (R3).
Coverage table:

| Message                                                | Prefixed? | Rationale |
|--------------------------------------------------------|-----------|-----------|
| `Session starting for ZXTL-1234. Worktree: …`          | **No**    | Already names the key in the body |
| `Draft PR opened: <url>`                               | **No**    | One-shot; PR description carries the key |
| `Status: iteration N/M @ <ts>`                         | **Yes**   | `[ZXTL-1234] Status: iteration 2/5 @ …` |
| `Status: final iteration N (natural)`                  | **Yes**   | `[ZXTL-1234] Status: final iteration 5 (natural)` |
| `Status: final iteration N (operator_stop)`            | **Yes**   |  |
| `Status: completed` / `Status: canceled` / `Status: failed` | **Yes**  |  |
| `Session canceled by operator.`                        | **Yes**   |  |
| `Session stopped (forced) by operator.`                | **Yes**   |  |
| `Session timed out` / `Session failed: <reason>`       | **Yes**   |  |
| `/run` empty-args usage hint                           | **No**    | Not session-bound |
| `/run` no-default-project hint                         | **No**    | Not session-bound |
| `/status` reply (main-chat list)                       | **No**    | Already lists keys per row |
| `/status` reply (topic-detail)                         | **No**    | Body is a fielded summary; prefix would be visual noise |

The single chokepoint (R3) makes "did 005 forget to prefix?" a one-line review question instead of a per-template inspection.

## `format_progress` helper

```python
# daemon/topic.py

def format_progress(issue_key: str, body: str) -> str:
    """Apply the [KEY] prefix to a session-bound message body.

    Body templates that already name the issue_key (e.g. "Session starting
    for ZXTL-1234. ...") MUST NOT pass through this helper — the caller
    composes those bodies directly. See "Outbound message catalogue".
    """
    return f"[{issue_key}] {body}"
```

That is the entire helper. Reviewers checking "did 005 forget to prefix any session message?" inspect the worker's call sites: every prefixed message goes through `format_progress`, every key-bearing template is composed inline. No third path.

## Worker integration

```python
# daemon/worker.py — pseudocode delta

async def run_worker(self, spec: WorkerSpec) -> None:
    chat_id = self.cfg.telegram.group_chat_id
    thread_id = spec.topic_id  # the forum topic; unchanged from 003/004

    async def post_progress(body: str) -> None:
        body_prefixed = topic.format_progress(spec.issue_key, body)
        await self.client.send_message(
            chat_id=chat_id,
            text=body_prefixed,
            message_thread_id=thread_id,
        )

    async def post_template(body: str) -> None:
        # For "Session starting…" and similar templates that already name
        # the issue_key in the body — see Outbound message catalogue above.
        await self.client.send_message(
            chat_id=chat_id,
            text=body,
            message_thread_id=thread_id,
        )

    await post_template(f"Session starting for {spec.issue_key}. Worktree: {spec.worktree}")
    # ... launch subprocess, stream PROGRESS lines, etc.
    async for line in stdout_lines:
        if line.startswith("PROGRESS "):
            await post_progress(line.removeprefix("PROGRESS "))
        elif line.startswith("FINAL "):
            await post_progress(line.removeprefix("FINAL "))
        # ...
```

The 003/004 channel-routing (chat_id + thread_id) is unchanged. The only 005 delta in `worker.py` is the use of `format_progress` for prefixed posts.

## Dispatcher integration

```python
# daemon/dispatcher.py — pseudocode delta

async def _handle_slash_command(self, inbound: Update, invocation: SlashCommandInvocation) -> None:
    # ... whitelist + chat_id gates (unchanged from 004) ...

    if invocation.name == "cancel":
        await self._handle_cancel(inbound, invocation, source="slash")

    elif invocation.name == "done":  # deprecated alias, slash form
        await self._emit_alias_warning(invocation, alias_token="/done", session_id=resolve_session_from_topic(invocation))
        await self._handle_cancel(inbound, invocation, source="slash_alias")

    elif invocation.name == "run":
        # 004 unchanged
        ...
    elif invocation.name == "status":
        # 004 unchanged
        ...
    else:
        # audit-log: slash_command_rejected (reason=unknown_command)
        ...

async def _maybe_handle_plaintext_alias(self, inbound: Update) -> bool:
    """Returns True if handled, False if not a plain-text alias."""
    if inbound.message.message_thread_id is None:
        return False                   # 003: aliases only inside topics
    text = inbound.message.text or ""
    if not match_termination_command(text):    # 003 matcher unchanged
        return False
    alias_token = text.strip().lstrip("/").lower()  # "done" / "stop" / "finish"
    session_id = resolve_session_from_topic(inbound)
    if session_id is None:
        # silent ignore + audit reason=no_active_session (003 behaviour)
        return True
    await self._emit_alias_warning(inbound, alias_token=alias_token, session_id=session_id)
    await self._handle_cancel(inbound, _synthetic_invocation_for_alias(inbound), source="plaintext_alias")
    return True

async def _emit_alias_warning(
    self, inbound_or_invocation, alias_token: str, session_id: str
) -> None:
    key = (alias_token, session_id)
    if key in self.runtime.alias_deprecation_warned:
        return
    self.runtime.alias_deprecation_warned.add(key)
    structlog.get_logger().warning(
        "alias_deprecation",
        alias_token=alias_token,
        canonical="cancel",
        session_id=session_id,
    )
    audit.write_event(
        type=audit.EV_ALIAS_DEPRECATION_USED,
        payload={
            "alias_token": alias_token,
            "canonical": "cancel",
            "session_id": session_id,
            # ... sender / message / chat ids from inbound
        },
    )
```

## Cancel handler

```python
async def _handle_cancel(self, inbound, invocation, source: str) -> None:
    # FR-002: resolve via message_thread_id (topic context)
    if invocation.message_thread_id is None:
        await audit.write_event(
            type=audit.EV_SLASH_COMMAND_REJECTED,
            payload={
                "reason": "main_chat_cancel" if source == "slash" else "main_chat_done",
                "command": invocation.name,
                # ... sender / message / chat ids
            },
        )
        return

    session_id = resolve_session_from_topic(invocation.message_thread_id)
    if session_id is None:
        await audit.write_event(
            type=audit.EV_SLASH_COMMAND_REJECTED,
            payload={"reason": "no_active_session", ...},
        )
        return

    # 003/004 unchanged from here: SIGUSR1 → grace → SIGTERM ladder
    await self._signal_worker_stop(session_id)
```

## Backwards-compat invariants

- 002 plain-text Jira-key trigger in main chat: pass-through, no behaviour change. (FR-015)
- 003 plain-text `done`/`stop`/`finish` inside topic: now wrapped with deprecation WARNING but otherwise identical behaviour. (FR-007, FR-016)
- 004 `/run`: pass-through, no behaviour change.
- 004 `/status` main-chat list and topic-detail: pass-through.
- 004 same-issue concurrency rule: unchanged.
- 003 SIGUSR1 / grace / SIGTERM ladder: unchanged.
- DB schema V0001: unchanged. `sessions.topic_id` continues to be populated by `createForumTopic` for every session.

## Worker / runtime impact (summary)

- `core/db.py`: no change.
- `core/config.py`: no change.
- `daemon/audit.py`: `+ EV_ALIAS_DEPRECATION_USED`, `+ "main_chat_cancel"` reason value (constant).
- `daemon/listener_state.py`: no change.
- `daemon/runtime.py`: `+ alias_deprecation_warned set`, `+ clear-on-terminal hook` in sessions transition.
- `daemon/dispatcher.py`: `+ /cancel branch`, `+ /done deprecation wrapper`, `+ plain-text alias deprecation wrapper`, `+ main_chat_cancel reason routing`.
- `daemon/worker.py`: `+ route prefixed posts through topic.format_progress`. Channel routing unchanged.
- `daemon/topic.py`: `+ format_progress(issue_key, body)`. `create_topic_for_session` unchanged.
- `telegram/client.py`: no change.
- `telegram/parser.py`: `+ /cancel` to recognised slash-command set; `match_termination_command` unchanged.
- `telegram/commands.py`: registry delta above.
- `commands/telegram.py`: no change.
- `daemon/sessions.py`: terminal transition gains the alias_deprecation_warned cleanup hook.

## Out of scope (data-model)

- A `sessions.cancel_message_id` column. The trigger / cancel message is referenced only by the dispatcher's transient context; not persisted.
- `reply_to_message_id` plumbing across outbound posts. Dropped from rev 2 — topic separation already provides visual structure.
- Any chat-type detection / migration metadata. Dropped from rev 2.
- Explicit-key cancel grammar (`/cancel ZXTL-1234`). Out of scope; topic resolution is sufficient (R1).
- Persisting the deprecation-warning idempotency set across restarts. Not worth the storage cost; restart legitimately re-emits the WARNING for active sessions.
