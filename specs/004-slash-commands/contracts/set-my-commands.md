# Contract: setMyCommands Registration

**Feature**: 004-slash-commands
**Status**: Phase 1 design

This contract defines exactly what the daemon registers with Telegram via `setMyCommands` and when. The Telegram client uses this registration to drive the autocomplete menu when an operator types `/`.

## Curated command set

The single source of truth lives in `src/remotask/telegram/commands.py`:

```python
@dataclass(frozen=True)
class CuratedCommand:
    name: str            # "run" | "done" | "status" — never with leading slash
    description: str     # ≤ 256 chars, BotFather-style sentence
    requires_topic: bool # /done is True; the rest are False
    requires_args: bool  # /run is True; the rest are False

CURATED_COMMANDS: tuple[CuratedCommand, ...] = (
    CuratedCommand(
        name="run",
        description="Start a new session",
        requires_topic=False,
        requires_args=True,
    ),
    CuratedCommand(
        name="done",
        description="End the current session",
        requires_topic=True,
        requires_args=False,
    ),
    CuratedCommand(
        name="status",
        description="Show active sessions",
        requires_topic=False,
        requires_args=False,
    ),
)
```

Adding or removing commands is a code change + redeploy + listener restart. Per-user customisation is explicitly out of scope (spec Assumptions).

## Bot API call shape

Default scope, English-only, payload constructed from the registry:

```jsonc
POST https://api.telegram.org/bot<TOKEN>/setMyCommands
{
  "commands": [
    {"command": "run",    "description": "Start a new session"},
    {"command": "done",   "description": "End the current session"},
    {"command": "status", "description": "Show active sessions"}
  ]
  // No "scope" field → BotCommandScopeDefault.
  // No "language_code" field → applies to all locales.
}
```

The HTTP wrapper reuses the existing `httpx.AsyncClient` from `telegram/client.py`. The `_call("setMyCommands", payload, throttle=True)` helper applies the same 50ms outbound spacing the rest of the Bot API methods use.

## Lifecycle

```text
Runtime.start() → listener thread spawned
        ↓
asyncio loop opens DB conn, calls getMe (cache bot username)
        ↓
runtime spawns set_my_commands(CURATED_COMMANDS) as a BACKGROUND task
        │   (does not block listener.run() — best-effort per FR-002)
        ↓
listener.run() begins polling immediately (Runtime._ready is set)
        ↓
the background task runs concurrently:
        │
        ├─ success → listener_state.commands_registered = True
        │            listener_state.commands_registered_at = now
        │            audit.log: commands_registered  (event)
        │            structlog INFO: "commands registered"
        │
        └─ failure → listener_state.commands_registered = False
                     audit.log: commands_registration_failed (event, WARNING)
                     structlog WARNING: "command registration failed"
                     NO IN-PROCESS RETRY — next listener restart will try again
```

The dispatch loop runs independently of registration. Even if `setMyCommands`
never succeeds, inbound `bot_command` entities are still parsed and dispatched —
the only operator-visible effect is the autocomplete menu may be missing or
stale.

**Why background instead of "after first getUpdates ok"?** An earlier draft of
this contract sequenced registration after a first successful long-poll, which
implicitly blocked listener readiness on Telegram availability. That coupling
is unnecessary — the listener's own startup precondition validation (002 §III)
already verifies the bot token format before we get here, so failing fast on a
genuinely bad token is handled upstream. The background task model gives
strictly better failure isolation.

## Idempotency

`setMyCommands` overwrites the bot's current command list with whatever payload is sent. Calling it on every listener start is safe — the registered list is always whatever the running daemon thinks it should be. There is no "delete" call needed when removing a command from `CURATED_COMMANDS`; the next registration will reflect the change.

## Failure handling matrix

| Telegram response | Daemon behaviour |
|---|---|
| 200 OK + `{"ok": true}` | Registration recorded as success |
| 401 Unauthorized | Listener startup precondition (002 §III) already rejects malformed bot tokens before this point; if a 401 still surfaces here, treat as a generic failure (warning + audit, no retry) |
| 5xx / network blip | `commands_registered=false`, audit-warning, no in-process retry. Next listener restart re-attempts. |
| 429 (rate-limited) | The shared `_call()` plumbing surfaces `retry_after`; the registration task treats 429 the same as a 5xx (warning + audit, no in-process retry). Operators rarely hit this for setMyCommands, and avoiding an inline retry keeps the background task's failure surface uniform. |

## Visibility to the operator

Two surfaces report the registration state:

1. **`remotask telegram status`** (existing CLI from 002):
   ```
   listener:        running
   since:           2026-05-02T08:00:00 (45 minutes ago)
   last poll:       2026-05-02T08:44:55 (5 seconds ago)
   degraded:        no
   active sessions: 1
   whitelist size:  2
   commands:        registered (last: 2026-05-02T08:00:01)
   ```
   When registration failed, the line reads `commands: not registered (will retry on next restart)`.

2. **`audit.log`** — one line on every attempt (success or failure) with the event types from `data-model.md`.

## Bot identity caching

Adjacent to setMyCommands, the runtime needs the bot's username (to strip `@<botname>` suffixes from inbound slash commands). Decision: **cache `getMe` once at startup, alongside the first poll**. The bot username is stored in memory on `Runtime` and consumed by `telegram/parser.py:match_slash_command()`. If `getMe` fails the listener still runs — `@<botname>` suffix matching simply gets a non-empty placeholder and never matches, so users in groups need to send `/run` without the suffix until next restart. Documented in the spec edge case set.

## Out of scope

- Per-user-language registration (`language_code` parameter). Out of scope per spec.
- Per-chat command set overrides (`scope.type = "chat"`). Out of scope per spec.
- `setMyDefaultAdministratorRights`, `setMyDescription`, `setMyShortDescription`, `setMyName` — all separate Bot API calls; not in this feature.
- Removing the registration on daemon shutdown. We don't bother — the next operator with the same bot will overwrite it on restart, and a stale menu is acceptable while the daemon is off.
