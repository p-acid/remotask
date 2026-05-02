# Contract: `/cancel` Dispatch + Alias Deprecation Protocol

**Feature**: 005-dm-channel (narrowed scope)
**Status**: Phase 1 design (rev 2)

This contract defines:

1. How `/cancel` (canonical) routes from inbound recognition to worker termination.
2. How `/done` (slash alias) and `done` / `stop` / `finish` (plain-text aliases) route through the same handler with a deprecation WARNING side effect.
3. How the `[KEY]` prefix is applied to outbound session-bound messages via `topic.format_progress`.

It is read alongside 004's slash-command protocol contract (`specs/004-slash-commands/contracts/slash-command-protocol.md`); this file describes only what changes or is added in 005.

## Inbound recognition (unchanged from 004)

A text message qualifies as a slash-command invocation when:

1. It has a non-empty `entities` array.
2. At least one entity has `{type: "bot_command", offset: 0}`.

The entity's `length` field gives the number of UTF-16 code units the command name occupies. Args = everything after, with one leading `\s+` consumed.

## Curated command set (delta from 004)

`/run`, `/cancel`, `/status`. `/done` is no longer in the curated set but is still recognised inbound (and routes through the deprecation path). Anything else is *unknown* and rejected with audit-only `slash_command_rejected reason=unknown_command`.

## Dispatcher decision tree (post-005)

```
text message arrives in cfg.telegram.group_chat_id
        │
        ├─ sender_id NOT in whitelist
        │    ├─ message has bot_command at offset 0 → audit-log: slash_command_rejected (reason=unauthorized)
        │    ├─ message_thread_id != null AND text matches termination grammar
        │    │       → audit-log: telegram_termination_rejected (reason=unauthorized)
        │    └─ otherwise → audit-log: telegram_unauthorized
        │   return.
        │
        ├─ sender_id IN whitelist
        │   │
        │   ├─ chat_id != cfg.telegram.group_chat_id
        │   │    ├─ message has bot_command → audit-log: slash_command_rejected (reason=wrong_chat)
        │   │    └─ otherwise → silent ignore
        │   │   return.
        │   │
        │   ├─ message has bot_command at offset 0  ← slash-command branch
        │   │    │
        │   │    ├─ name not in {run, cancel, status, done}
        │   │    │    → audit-log: slash_command_rejected (reason=unknown_command)
        │   │    │   return.
        │   │    │
        │   │    ├─ name == "run"
        │   │    │    └─ → 004 run_handler (unchanged)
        │   │    │
        │   │    ├─ name == "cancel"   ← 005 NEW canonical
        │   │    │    │
        │   │    │    ├─ message_thread_id is null (main chat)
        │   │    │    │    → audit-log: slash_command_rejected (reason=main_chat_cancel)
        │   │    │    │   return.
        │   │    │    │
        │   │    │    ├─ resolve session by core.db.get_active_session_by_topic(thread_id)
        │   │    │    │    │
        │   │    │    │    ├─ no active session → audit-log: slash_command_rejected (reason=no_active_session)
        │   │    │    │    │   return.
        │   │    │    │    │
        │   │    │    │    └─ session_id resolved
        │   │    │    │         → record session_events: slash_command_received (command="cancel")
        │   │    │    │         → 003 termination ladder: SIGUSR1 → grace watchdog → SIGTERM
        │   │    │    │
        │   │    │
        │   │    ├─ name == "done"   ← 005 deprecated alias, slash form
        │   │    │    │
        │   │    │    ├─ message_thread_id is null (main chat)
        │   │    │    │    → audit-log: slash_command_rejected (reason=main_chat_done)   ← retained value from 004
        │   │    │    │   return.
        │   │    │    │
        │   │    │    ├─ resolve session_id
        │   │    │    │    │
        │   │    │    │    ├─ no active session → audit-log: slash_command_rejected (reason=no_active_session)
        │   │    │    │    │   return.
        │   │    │    │    │
        │   │    │    │    └─ session_id resolved
        │   │    │    │         → emit_alias_warning(alias_token="/done", session_id=…)
        │   │    │    │         → record session_events: slash_command_received (command="done")
        │   │    │    │         → same termination ladder as /cancel
        │   │    │    │
        │   │    │
        │   │    ├─ name == "status"
        │   │    │    └─ → 004 status_handler (unchanged)
        │   │    │
        │   │    return.    ← slash branch terminates here
        │   │
        │   ├─ message_thread_id != null AND match_termination_command(text)
        │   │    ← 005: 003 plain-text alias path with deprecation hook added
        │   │    │
        │   │    ├─ resolve session_id
        │   │    │    │
        │   │    │    ├─ no active session → silent ignore + audit-log: telegram_termination_rejected
        │   │    │    │   return.
        │   │    │    │
        │   │    │    └─ session_id resolved
        │   │    │         → alias_token = text.strip().lstrip("/").lower()  # "done" / "stop" / "finish"
        │   │    │         → emit_alias_warning(alias_token=alias_token, session_id=…)
        │   │    │         → record session_events: telegram_termination_received (003 event type retained)
        │   │    │         → same termination ladder
        │   │    │
        │   │
        │   ├─ extract_first_issue_key(text) is non-null AND prefix is registered
        │   │    → 002 trigger handler (unchanged).
        │   │
        │   ├─ extract_first_issue_key(text) is non-null AND prefix is NOT registered
        │   │    → 002 unknown-prefix reply (unchanged).
        │   │
        │   └─ otherwise → silent ignore (casual chat).
```

Order is fixed (same as 004 with the new `/cancel` and `/done` alias branches inserted).

## `emit_alias_warning` semantics

```python
def emit_alias_warning(alias_token: str, session_id: str, *, sender_id: int, message_id: int, chat_id: int, message_thread_id: int) -> None:
    key = (alias_token, session_id)
    if key in runtime.alias_deprecation_warned:
        return                                    # silent — already warned for this (alias, session) pair
    runtime.alias_deprecation_warned.add(key)
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
            "sender_id": sender_id,
            "message_id": message_id,
            "chat_id": chat_id,
            "message_thread_id": message_thread_id,
        },
    )
```

Membership invariant: `(alias_token, session_id)` is the key. The same operator using both `/done` and plain-text `done` on the same session would produce **two** WARNING lines (one per alias_token). This is correct — each alias is its own deprecation signal.

Cleanup: when `session_id` reaches a terminal state, the sessions transition helper drops every `(_, session_id)` tuple from the set:

```python
runtime.alias_deprecation_warned = {
    tup for tup in runtime.alias_deprecation_warned if tup[1] != session_id
}
```

## `/cancel` execution sequence

Once the dispatcher resolves a `session_id` for `/cancel` (or `/done` alias, or plain-text alias):

1. Record `session_events` row of type `slash_command_received` (or `telegram_termination_received` for plain-text path) with the relevant `command` discriminator.
2. Send SIGUSR1 to the worker (003 mechanism unchanged).
3. Launch the grace watchdog (003 unchanged).
4. The worker emits `FINAL iteration <i> (operator_stop)` on stdout.
5. The worker exits 0; daemon transitions session to `canceled` with `error_message=operator_stop`.
6. Daemon posts (via `format_progress`) `[ZXTL-1234] Status: final iteration <i> (operator_stop)` and `[ZXTL-1234] Session canceled by operator.` to the topic.
7. Sessions transition helper clears `alias_deprecation_warned` entries for this `session_id`.

Steps 2–5 are 003 unchanged; steps 1, 6, 7 carry 005's deltas (audit field value, prefix application, set cleanup).

## `[KEY]` prefix application

```python
# daemon/topic.py

def format_progress(issue_key: str, body: str) -> str:
    return f"[{issue_key}] {body}"
```

Call-site discipline (worker.py):

```python
async def post_progress(body: str) -> None:
    body_prefixed = topic.format_progress(spec.issue_key, body)
    await self.client.send_message(chat_id=chat_id, text=body_prefixed, message_thread_id=thread_id)

async def post_template(body: str) -> None:
    # For "Session starting..." and similar — already names the key.
    await self.client.send_message(chat_id=chat_id, text=body, message_thread_id=thread_id)
```

The catalogue of which message goes through which call lives in `data-model.md` "Outbound message catalogue".

## Outbound message templates (no new ones in 005)

005 does not introduce any new outbound message templates. It only changes the **formatting** of existing 003/004 progress / final / canceled messages by routing them through `format_progress`. Existing templates from 004 (`/run` usage hint, `/run` no-default-project hint, `/status` empty list, etc.) are unchanged.

## Audit payloads (deltas from 004)

`session_events` row, type `slash_command_received`, `command` field gains the value `"cancel"`:

```jsonc
{
  "command": "cancel",
  "args_text_truncated": "",                   // /cancel has no args in 005
  "sender_id": <int>,
  "message_id": <int>,
  "chat_id": <int>,
  "message_thread_id": <int>                   // never null for accepted /cancel
}
```

`audit.log` event `slash_command_rejected`, `reason` field gains `main_chat_cancel`:

```jsonc
{
  "reason": "main_chat_cancel",
  "command": "cancel",
  "sender_id": <int>,
  "message_id": <int>,
  "chat_id": <int>,
  "message_thread_id": null,
  "args_text_truncated": ""
}
```

`audit.log` event `alias_deprecation_used` (new):

```jsonc
{
  "alias_token": "/done" | "done" | "stop" | "finish",
  "canonical": "cancel",
  "session_id": <str>,
  "sender_id": <int>,
  "message_id": <int>,
  "chat_id": <int>,
  "message_thread_id": <int>
}
```

## Backwards-compat invariants

- 002's `extract_first_issue_key` path runs unchanged. Plain-text `ZXTL-1234` in the main chat continues to trigger sessions.
- 003's `match_termination_command` matcher (`done`/`stop`/`finish`, optional leading slash, alone on a line, case-insensitive, inside a topic) is unchanged at the regex level. The only delta is the deprecation WARNING wrapper at the dispatcher.
- 004's `/run`, `/status` paths are unchanged.
- 004's `slash_command_received` and `slash_command_rejected` event shapes are unchanged; only the field value sets grow.
- 004's curated-command idempotency rule (next `setMyCommands` call overwrites) is unchanged.

## Out of scope

- Explicit-key cancel grammar (`/cancel ZXTL-1234`). The topic context resolves the session unambiguously; an arg form would be redundant (R1).
- Multi-issue cancel (`/cancel A B C`).
- A canonical plain-text alias for `cancel` (e.g. bare `cancel` in a topic). 003's matcher is preserved; the canonical command is slash-only (R6).
- `reply_to_message_id` plumbing on outbound posts. Dropped from rev 2.
- Per-user-language autocomplete menus. Out of scope (004 inheritance).
- Inline keyboards / callback queries.
