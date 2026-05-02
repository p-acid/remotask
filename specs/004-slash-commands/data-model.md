# Data Model: Telegram Slash-Command Surface

**Feature**: 004-slash-commands
**Date**: 2026-05-02
**Status**: Phase 1 design

## Schema delta vs V0001

**No new migration in this feature.** V0001 (from 001) covers everything. The feature reuses existing `sessions` columns; the only "new" data shape is in JSON payloads (audit events) and the listener state file.

| Use site | Column / file | New semantics in 004 |
|---|---|---|
| Session originated from `/run` (free-text) | `sessions.issue_key` | Stores synthetic id `run-<YYYY-MM-DD-HH-MM>-<slug>-<6-hex>` |
| `/run` free-text args | `sessions.trigger_text` | Stores the verbatim text after the command (and after the leading Jira-key, if any) |
| Slash-command audit | `session_events.type` | New session-bound type `slash_command_received` |
| Slash-command audit | `audit.log` | New unbound types `slash_command_rejected`, `commands_registered`, `commands_registration_failed` |
| setMyCommands status | `listener.state` | New fields `commands_registered`, `commands_registered_at` |
| Default project | `config.toml` `[agent]` | New optional field `default_project_jira_key` |

## Synthetic `issue_key` shape (free-text `/run`)

```text
run-2026-05-02-14-fix-the-cache-a3f9b1
└─ prefix     └─ minute        └─ slug         └─ 6 hex chars
   ("run")    (YYYY-MM-DD-HH-MM)   (≤20 chars,    (collision avoidance)
                                    lowercase
                                    alnum + dash)
```

Slug derivation:

1. Take `args` after the command (`/run fix THE Cache!` → `fix THE Cache!`).
2. Lowercase: `fix the cache!`.
3. Replace non-`[a-z0-9]` runs with single dash: `fix-the-cache-`.
4. Trim leading/trailing dashes: `fix-the-cache`.
5. Truncate to ≤ 20 chars at the last dash boundary if possible: `fix-the-cache`.
6. If the slug ends up empty (e.g. emoji-only args), use `untitled`.

Hex suffix:

- `secrets.token_hex(3)` — six lowercase hex chars.
- Independent per session insert; collision probability with the same minute+slug ≈ 1/16.7M per pair.

The full string fits well within Telegram's 128-char forum-topic-name limit:

- `run-` (4) + `YYYY-MM-DD-HH-MM` (16) + `-` (1) + slug (≤ 20) + `-` (1) + 6 hex (6) = ≤ 48 chars.

The session row's `issue_key` MUST be unique among non-terminal sessions per 002 FR-010. The 6-char hex suffix makes accidental same-minute / same-slug collisions astronomically unlikely (~ 1 in 16.7 million per pair) — not a hard guarantee, but in practice indistinguishable from one. If a collision ever does occur, the existing same-issue concurrency check (002 FR-010) rejects the second insertion with the standard "already in flight" reply, which is the same UX as a deliberate same-issue retrigger.

## `sessions.trigger_text` semantics (extended)

| Origin | What lives in `trigger_text` |
|---|---|
| 002 plain-text Jira-key trigger | The raw inbound text (e.g. `"please look at ZXTL-1234"`) |
| 003 plain-text `done`/`stop`/`finish` | n/a — these don't insert sessions |
| 004 `/run ZXTL-1234 also add tests` | `"also add tests"` (everything after the leading Jira key) |
| 004 `/run fix the cache layer` | `"fix the cache layer"` (the entire args string) |
| 004 `/run` (no args) | n/a — request is rejected before insert |

`trigger_text` may be empty for `/run ZXTL-1234` with no trailing text. That is allowed.

## Audit event taxonomy additions

Four new event-type constants in `daemon/audit.py`:

| Type | Storage | Payload fields |
|---|---|---|
| `slash_command_received` | `session_events` row (session_id = the affected session) | `{command, args_text_truncated, sender_id, message_id, chat_id, message_thread_id}` |
| `slash_command_rejected` | `audit.log` | `{reason, command, sender_id, message_id, chat_id, message_thread_id, args_text_truncated}` where `reason ∈ {unauthorized, wrong_chat, unknown_command, main_chat_done, no_active_session, no_default_project, empty_args}` |
| `commands_registered` | `audit.log` | `{commands: [{name, description}, ...], registered_at: <epoch>}` |
| `commands_registration_failed` | `audit.log` (level WARNING) | `{error: <str>, attempted_at: <epoch>}` |

`args_text_truncated` is the args string capped at 64 chars to keep audit rows compact (full args lives in `sessions.trigger_text`).

## Listener state file additions

```jsonc
// ~/.local/share/remotask/listener.state — V0001 fields + 004 additions
{
  "running": true,
  "started_at": 1746115200,
  "last_poll_ok_at": 1746115245,
  "consecutive_failures": 0,
  "active_sessions": 1,
  "whitelist_size": 2,
  "degraded": false,
  "last_update_id": 5294,

  // 004 additions:
  "commands_registered": true,
  "commands_registered_at": 1746115201
}
```

`commands_registered`: `true` after the first successful `setMyCommands` of the listener's lifetime; `false` if the most recent attempt failed; absent on first start (treated as `false`).

`commands_registered_at`: epoch seconds of the last successful registration; absent if never registered. Keeps the operator informed via `remotask telegram status` ("commands registered: yes (last: 2026-05-02T08:30:15Z)").

## Configuration extension

```toml
[agent]
# ... existing fields (max_concurrent, worktree_root, default_base_branch,
#                     permission_mode, session_timeout_seconds,
#                     operator_stop_grace_seconds) ...

# NEW — 004. The Jira project key (e.g. "ZXTL") to fall back on when /run
# is invoked with free-text args (no Jira key in the args). Empty / unset
# disables the free-text fallback — /run with non-key args then replies
# with a setup hint.
default_project_jira_key = ""
```

Validation (pydantic):
- `str`, default `""`.
- When non-empty, MUST match the existing project-key regex `^[A-Z]{2,10}$` (same as `core/projects.py`).

## Configuration extension — Telegram (none)

`[telegram]` is unchanged. setMyCommands uses the same `bot_token` already required by the listener.

## Curated command registry

A code-only data structure (no DB / config presence) — see `contracts/set-my-commands.md` for the canonical list. The runtime imports the registry once; setMyCommands serialises it; the dispatcher dispatches by it; tests pin it.

## Worker / runtime impact (summary)

- `core/db.py`: no change.
- `core/config.py`: `+ default_project_jira_key`.
- `daemon/audit.py`: `+ 4 constants`.
- `daemon/listener_state.py`: `+ 2 fields` (with migrations-on-load via `ListenerState.from_json`'s field-filter).
- `daemon/runtime.py`: `+ setMyCommands invocation, + getMe cache for botname`.
- `daemon/dispatcher.py`: `+ slash-command branch ahead of issue-key branch`.
- `daemon/topic.py`: `+ status reply formatter, + /run usage hint template`.
- `telegram/client.py`: `+ set_my_commands(), + get_me()`.
- `telegram/parser.py`: `+ match_slash_command()`.
- `telegram/commands.py`: NEW — registry.
- `daemon/worker.py`: no change.
- `daemon/sessions.py`: no change (existing `insert_enqueued_session` reused with synthetic `issue_key`).

## Secret redaction

No new secret-bearing fields. `bot_token` redaction (002) is unchanged; `setMyCommands` reuses the same Bearer-style URL pattern that `sendMessage` does.

## Backwards compatibility invariants

- 003 plain-text Jira-key trigger: pass-through, no behaviour change.
- 003 plain-text `done`/`stop`/`finish`: pass-through, no behaviour change.
- 002 same-issue concurrency rule: still applies. Synthetic `issue_key` from `/run` collides with itself only if hex matches — astronomically rare and the dispatcher's same-issue check still rejects it cleanly.
- 002 max_concurrent cap: still applies.
- 003 SIGUSR1 / grace / SIGTERM ladder: unchanged.
