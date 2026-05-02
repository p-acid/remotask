# Contract: Slash-Command Dispatch Protocol

**Feature**: 004-slash-commands
**Status**: Phase 1 design

This contract defines how inbound Telegram messages carrying a `bot_command` entity become dispatched actions. It is read alongside 002's trigger-protocol contract and 003's termination-protocol contract; this file describes only what is added or refined.

## Inbound recognition

A text message qualifies as a slash-command invocation when:

1. It has a non-empty `entities` array.
2. At least one entity has `{type: "bot_command", offset: 0}`.

The entity's `length` field gives the number of UTF-16 code units the command name occupies, including the leading `/`. Args are everything after that, with a single leading `\s+` consumed.

Pseudocode:

```python
def parse_slash_command(message: dict) -> SlashCommandInvocation | None:
    entities = message.get("entities") or []
    cmd_entity = next(
        (e for e in entities if e.get("type") == "bot_command" and e.get("offset") == 0),
        None,
    )
    if cmd_entity is None:
        return None
    text = message["text"]
    raw = text[cmd_entity["offset"] : cmd_entity["offset"] + cmd_entity["length"]]
    # raw == "/run" or "/run@curious_claude_notification_bot"
    name = raw.lstrip("/").split("@", 1)[0].lower()
    rest = text[cmd_entity["offset"] + cmd_entity["length"] :].lstrip()
    return SlashCommandInvocation(
        name=name,
        args_text=rest,
        sender_id=message["from"]["id"],
        chat_id=message["chat"]["id"],
        message_thread_id=message.get("message_thread_id"),
        message_id=message["message_id"],
    )
```

## Curated command set

`/run`, `/done`, `/status`. Anything else is *unknown* and silently ignored at dispatch (audit-log unbound entry only).

## Dispatcher decision tree (full, post-004)

```
text message arrives in configured chat
        │
        ├─ sender_id NOT in whitelist
        │    ├─ message has bot_command at offset 0 → audit-log: slash_command_rejected (reason=unauthorized)
        │    ├─ message_thread_id != null AND text matches termination grammar
        │    │       → audit-log: telegram_termination_rejected (reason=unauthorized) (003)
        │    └─ otherwise → audit-log: telegram_unauthorized (002)
        │   return.
        │
        ├─ sender_id IN whitelist
        │   │
        │   ├─ chat_id != cfg.telegram.group_chat_id
        │   │    ├─ message has bot_command → audit-log: slash_command_rejected (reason=wrong_chat)
        │   │    └─ otherwise → silent ignore (002)
        │   │   return.
        │   │
        │   ├─ message has bot_command at offset 0  ← 004 NEW BRANCH
        │   │    │
        │   │    ├─ name not in CURATED_COMMANDS
        │   │    │    → audit-log: slash_command_rejected (reason=unknown_command)
        │   │    │   return.
        │   │    │
        │   │    ├─ name == "run"
        │   │    │    └─ → run_handler(args_text)   (see "/run routing" below)
        │   │    │
        │   │    ├─ name == "done"
        │   │    │    ├─ message_thread_id is null (main chat)
        │   │    │    │    → audit-log: slash_command_rejected (reason=main_chat_done)
        │   │    │    │   return.
        │   │    │    └─ → 003 termination-handler (same SIGUSR1 / grace ladder)
        │   │    │
        │   │    ├─ name == "status"
        │   │    │    ├─ message_thread_id is null → main-chat list reply
        │   │    │    └─ message_thread_id non-null → topic-detail reply
        │   │    │
        │   │    return.    ← slash branch terminates here; never falls through to 003
        │   │
        │   ├─ message_thread_id != null AND match_termination_command(text)
        │   │    → 003 plain-text termination handler. (Backwards-compat keep.)
        │   │
        │   ├─ extract_first_issue_key(text) is non-null AND prefix is registered
        │   │    → 002 trigger handler. (Backwards-compat keep.)
        │   │
        │   ├─ extract_first_issue_key(text) is non-null AND prefix is NOT registered
        │   │    → 002 unknown-prefix reply.
        │   │
        │   └─ otherwise → silent ignore (casual chat).
```

Order is fixed. The slash-command branch precedes the 003 / 002 plain-text branches (FR-015) so a `/run` containing what looks like a Jira-key never falls through to plain-text routing.

## `/run` argument routing

```
args_text = "..."
        │
        ├─ args_text is empty / whitespace-only
        │    → reply in chat-of-origin: TPL_RUN_USAGE_HINT
        │    → audit-log: slash_command_rejected (reason=empty_args)
        │
        ├─ first whitespace-split token matches issue-key regex (002)
        │    │
        │    ├─ prefix is registered
        │    │    → insert session(issue_key=token, trigger_text=rest_after_token)
        │    │      then standard 002 accept path (lock, topic, worker)
        │    │
        │    └─ prefix is NOT registered
        │         → 002 unknown-prefix main-chat reply
        │         → audit-log: telegram_unknown_prefix (002 path)
        │
        └─ args_text does NOT start with an issue-key token
             │
             ├─ cfg.agent.default_project_jira_key is empty / unset
             │    → reply in chat-of-origin: TPL_RUN_NO_DEFAULT_PROJECT
             │    → audit-log: slash_command_rejected (reason=no_default_project)
             │
             └─ default project is registered
                  → insert session(issue_key=synthetic, trigger_text=args_text)
                  → standard 002 accept path with that project's repo
```

`reply in chat-of-origin` means: if the `/run` came from the main chat, reply in the main chat; if it came from a topic, reply in that topic with `message_thread_id`.

## `/done` semantics

Equivalent to 003's plain-text termination. The slash-command path:

1. Whitelist gate already applied above.
2. Topic gate already applied above (`/done` in main chat → `slash_command_rejected` reason=main_chat_done).
3. Resolve session by `core.db.get_active_session_by_topic`.
4. If no active session → audit-log `slash_command_rejected` reason=no_active_session, no reply.
5. Otherwise:
   - record `session_events` of type `slash_command_received` (003 also produced `telegram_termination_received`; 004 records `slash_command_received` with the bot_command name as discriminator).
   - send SIGUSR1 to the worker.
   - launch the grace watchdog (existing 003 code).

## `/status` reply rules

`/status` in the main chat:

```
Active sessions (3):
ZXTL-1234        running    iteration 3/5     2 min ago
ZXTL-9000        starting   —                  18s ago
run-2026-05-02-14-fix-the-cache-a3f9b1   running   iteration 1/5   45s ago

Type /status inside a topic for that session's detail.
```

Capped at 10 lines + a "+ N more" trailer.

`/status` inside a topic:

```
ZXTL-1234
status:    running
iteration: 3/5 @ 2026-05-02T14:32:18Z
started:   2 min ago
worktree:  ~/Developments/remotask-wt/ZXTL-1234
```

If no session is bound to the topic, reply: `No active session in this topic.`

## Outbound message templates (new)

| Trigger | Template | Channel |
|---|---|---|
| `/run` empty args | `Usage: /run <PREFIX>-<NUM>  or  /run <free text> (requires agent.default_project_jira_key)` | chat-of-origin |
| `/run` free-text + no default project configured | `No default project configured. Set agent.default_project_jira_key in config.toml or use /run <PREFIX>-<NUM>.` | chat-of-origin |
| `/status` main-chat (formatted as above) | (composed) | main chat |
| `/status` topic-detail (formatted as above) | (composed) | bound topic |
| `/status` empty | `No active sessions.` | main chat |
| `/status` topic-detail with no active session | `No active session in this topic.` | bound topic |

## Audit payloads

Accepted invocation:

```jsonc
// session_events row, type = "slash_command_received"
{
  "command": "run" | "done" | "status",
  "args_text_truncated": "<≤64 chars>",
  "sender_id": <int>,
  "message_id": <int>,
  "chat_id": <int>,
  "message_thread_id": <int|null>
}
```

Rejected invocation (`audit.log` line):

```jsonc
// event_type = "slash_command_rejected"
{
  "reason": "unauthorized" | "wrong_chat" | "unknown_command" | "main_chat_done"
          | "no_active_session" | "no_default_project" | "empty_args",
  "command": "run" | "done" | "status" | "<unrecognized>",
  "sender_id": <int>,
  "message_id": <int>,
  "chat_id": <int>,
  "message_thread_id": <int|null>,
  "args_text_truncated": "<≤64 chars>"
}
```

## Backwards-compat invariants

- 002's `extract_first_issue_key` path is reachable only when there's NO `bot_command` entity at offset 0. Plain-text `ZXTL-1234` continues to work.
- 003's `match_termination_command` path is reachable only when there's NO `bot_command` entity at offset 0 AND `message_thread_id` is non-null. Plain-text `done`/`stop`/`finish` continues to work.
- 002's main-chat unknown-prefix reply continues to work for plain-text-only paths.

## Out of scope

- Multi-token slash commands or sub-commands (`/admin`, `/run --no-pr`).
- Inline keyboards / callback queries.
- Per-chat or per-user command set overrides (clarification Q4 → default scope).
- LLM intent parsing on `/run` args.
- Pagination on `/status`.
