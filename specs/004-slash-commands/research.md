# Phase 0 Research: Telegram Slash-Command Surface

**Feature**: 004-slash-commands
**Date**: 2026-05-02

Each entry resolves an open decision raised in `plan.md`. After this phase, no `NEEDS CLARIFICATION` markers remain in Technical Context.

---

## R1. setMyCommands placement in the runtime lifecycle

**Decision**: Invoke `setMyCommands` from `Runtime._async_main()` **after** the listener performs its first successful `getUpdates`. Specifically, the listener's first poll loop iteration sets a "first poll OK" flag; the runtime observes the flag and fires `setMyCommands` once. Failure logs a warning but never blocks the listener.

**Rationale**:
- Sequencing setMyCommands *after* a successful getUpdates proves the bot token is valid and reachable. If we register commands first and the token is bad, we'd see two failures in the log; this way the first failure (auth) is enough.
- "Commands registered" lining up with "listener live" gives the operator a single mental model.
- Best-effort posture (FR-002) is naturally enforced — the call is in a try/except and a fail just toggles a flag in `listener.state`.

**Alternatives rejected**:
- *Register before listener starts*: misleading on bad credentials; double error noise.
- *Register on every getUpdates success*: wasteful, and Telegram rate-limits `setMyCommands` per bot.
- *Re-register periodically*: complexity for no operator-visible benefit (Telegram caches the command set persistently).

---

## R2. bot_command entity offset semantics

**Decision**: A message qualifies as a slash-command invocation if and only if its `entities` array contains a `bot_command` entity at `offset == 0`. Entities at non-zero offsets are treated as ordinary text within the args.

**Rationale**:
- Matches BotFather convention and Telegram's own client behaviour (autocomplete only triggers when typing `/` at start).
- Avoids unwanted dispatch from a casual sentence like "I think we should `/cancel` that idea" — that `/cancel` is at offset > 0 and is therefore plain text.
- Keeps the parser deterministic: one command per message, always at the front.

**Alternatives rejected**:
- *Match any bot_command entity*: opens up accidental dispatch from quoted text, replies, etc.
- *Regex on raw text without entities*: ignores Telegram's own annotation, which is the source of truth and handles edge cases (e.g. `/run` inside a code block — an entity is *not* emitted there).

---

## R3. `@<botname>` suffix handling

**Decision**: When normalising the command, strip a trailing `@<botname>` segment (case-insensitive). The bot's own username is fetched once at startup via `getMe` and cached in the runtime. Commands `/run` and `/run@curious_claude_notification_bot` collapse to the same canonical `run`.

**Rationale**:
- Telegram clients automatically append `@<botname>` in groups when multiple bots are present, but never in 1:1 DMs. Both forms must work without operator awareness.
- The bot identity is already authoritative (we hold the token), so the suffix carries no new information.
- Caching `getMe` once at startup avoids one extra round-trip per dispatch.

**Alternatives rejected**:
- *Reject suffix forms*: breaks the multi-bot-in-group case.
- *Match suffix dynamically per call*: redundant network calls.

---

## R4. Synthetic topic naming for free-text `/run`

**Decision**: Topic name = `run-<YYYY-MM-DD-HH-MM>-<slug>-<6-hex>` where:

- `<YYYY-MM-DD-HH-MM>` is the daemon's UTC time at session insert.
- `<slug>` is the first ≤ 20 chars of the args, lowercased, ASCII alnum + dash only (collapsed runs of disallowed chars to a single dash, trailing dashes stripped).
- `<6-hex>` is `secrets.token_hex(3)` — six lowercase hex digits.

The full string is also stored in `sessions.issue_key`, satisfying 002's same-issue concurrency rule (FR-010) trivially because the hex suffix makes collisions astronomically unlikely.

**Rationale**:
- Human-readable in the Telegram topic list — operators can scan their topics and recognise what each was about without opening it.
- Hex suffix prevents accidental collision when two `/run` invocations land in the same minute with similar args (e.g. dictation on a phone retry).
- Stays under Telegram's 128-char topic name limit comfortably.

**Alternatives rejected**:
- *UUID v4 only*: opaque, not human-readable.
- *Sub-second timestamp*: harder to read in topic titles, no real benefit over the hex suffix.
- *LLM-generated topic name*: latency + LLM cost for a tiny benefit; out of scope per spec.

---

## R5. `/status` snapshot atomicity and limit handling

**Decision**: A single SQL query:

```sql
SELECT id, issue_key, status, started_at, log_path
FROM sessions
WHERE status IN ('enqueued','starting','running')
ORDER BY enqueued_at DESC
LIMIT 11;
```

If 11 rows return, the reply renders the first 10 with a trailing "+ 1 more (truncated)" hint. The shape is:

```
ZXTL-1234        running    iteration 3/5     2 min ago
run-2026-05-02…  starting   —                  18s ago
+ 0 more
```

**Rationale**:
- Single read = consistent snapshot.
- 11 = 10 + 1 lets us detect overflow without a separate COUNT query.
- Fixed-width-ish layout (fixed-pitch font in Telegram) makes the reply scannable.
- Iteration index is read from the most recent `PROGRESS` line in the per-session log; for sessions that haven't emitted a PROGRESS yet, dash.

**Alternatives rejected**:
- *Pagination*: out of scope per spec.
- *Real-time progress query*: would need a runtime API; fixing this in DB is enough for the use case.

---

## R6. `/run` argument parsing

**Decision**: Split args on the first `\s+` once. If the first token matches the 002 issue-key regex (`^[A-Z][A-Z0-9_]{1,9}-\d{1,6}$`), use it for routing and store the rest as `sessions.trigger_text`. Otherwise the whole args string is free-text → fall back to `agent.default_project_jira_key`.

**Rationale**:
- Single token detection is unambiguous and matches operator intuition (`/run ZXTL-1234 also add tests` is "run on ZXTL-1234, also do this").
- Free-text path lets operators dictate intent without remembering Jira keys (the headline UX win).
- Storing the rest as `trigger_text` preserves the operator's request verbatim for audit and future LLM use.

**Alternatives rejected**:
- *Always treat first token as Jira-key candidate even when no `-`*: wasteful.
- *Require explicit prefix flag (`--key=ZXTL-1234`)*: friction; operators will forget.

---

## R7. setMyCommands failure recovery

**Decision**: A failed `setMyCommands` call (network error, 5xx, 429) logs a `WARNING` and sets `listener.state.commands_registered = false`. **No in-process retry.** The next listener restart re-attempts. Inbound dispatch continues to work — only the autocomplete menu is potentially stale.

**Rationale**:
- A retry loop here is hard to bound (we'd need backoff that doesn't conflict with the listener's own backoff). Simpler to lean on listener restarts.
- The cost of a stale menu is small (operator types the command anyway) so we don't need aggressive recovery.
- Audit log gets a `commands_registration_failed` entry so the operator can see the failure on `remotask telegram status`.

**Alternatives rejected**:
- *Retry with backoff in-process*: extra state machine for tiny win.
- *Crash the daemon on registration failure*: violates fail-soft posture.

---

## R8. Privacy Mode interaction with backwards compatibility

**Decision**: The dispatcher's slash-command branch and 003 plain-text branch are independent. Slash commands work regardless of Privacy Mode. Plain-text triggers continue to depend on Privacy Mode being OFF (the bot must be allowed to read non-mention text).

We document Privacy Mode OFF as the recommended posture (clarification Q1) but do **not** force it in code — the operator may flip it on for slash-only UX.

**Rationale**:
- Forcing Privacy Mode OFF would require a `setMyCommands`-adjacent call (`setMyDefaultAdministratorRights`?) we don't otherwise need.
- Leaving the choice to the operator preserves user agency.

**Alternatives rejected**:
- *Auto-disable Privacy Mode at startup*: reaches into BotFather settings the operator may have intentionally configured.
- *Refuse to start unless Privacy Mode is OFF*: too restrictive given slash-only is a valid mode.

---

## R9. Audit-event taxonomy

**Decision**: Four new event constants in `daemon/audit.py`:

| Constant | Bound to session? | Where written |
|---|---|---|
| `EV_SLASH_COMMAND_RECEIVED` | yes (the affected session) | `session_events` row |
| `EV_SLASH_COMMAND_REJECTED` | no | `audit.log` only |
| `EV_COMMANDS_REGISTERED` | no | `audit.log` (one line per success) |
| `EV_COMMANDS_REGISTRATION_FAILED` | no | `audit.log` + WARNING |

Reject reasons (`EV_SLASH_COMMAND_REJECTED.payload.reason`):
`unauthorized` | `wrong_chat` | `unknown_command` | `main_chat_done` | `no_active_session` | `no_default_project` | `empty_args`

**Rationale**:
- Mirrors 003's audit pattern — session-bound when we know the session, unbound otherwise.
- Reject reasons are explicit enums so dashboards / log searches stay clean.

**Alternatives rejected**:
- *Single `slash_command_attempted` with status field*: harder to filter "show me only rejections".

---

## R10. Curated command registry as source of truth

**Decision**: A single new module `src/remotask/telegram/commands.py` exports a frozen list of dataclasses:

```python
@dataclass(frozen=True)
class CuratedCommand:
    name: str          # "run", "done", "status" — no leading slash
    description: str   # ≤ 256 chars, BotFather-style
    requires_topic: bool       # /done is True; /run, /status are False
    requires_args: bool        # /run is True; /done, /status are False

CURATED_COMMANDS: tuple[CuratedCommand, ...] = (
    CuratedCommand(name="run",    description="Start a new session", requires_topic=False, requires_args=True),
    CuratedCommand(name="done",   description="End the current session", requires_topic=True,  requires_args=False),
    CuratedCommand(name="status", description="Show active sessions", requires_topic=False, requires_args=False),
)
```

`setMyCommands` serialises `name`+`description`. The dispatcher imports the same tuple and dispatches by `name`. A unit test pins the tuple shape so accidental drift is caught at PR time.

**Rationale**:
- Single source of truth eliminates the failure mode where the menu shows a command the dispatcher doesn't handle (or vice versa).
- `requires_topic` / `requires_args` flags push validation logic out of the handlers and into a single guard.
- The frozen tuple is trivially testable.

**Alternatives rejected**:
- *Define commands inside the dispatcher itself*: fine for now but creates coupling between menu and dispatch logic that grows over time.
- *YAML / TOML registry*: over-engineering for three commands.

---

## Summary

All 10 items resolved; no `NEEDS CLARIFICATION` markers remain. Phase 1 (data-model, contracts, quickstart) proceeds.
