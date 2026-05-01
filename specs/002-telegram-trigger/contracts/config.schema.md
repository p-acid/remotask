# Config Contract: `[telegram]` and `[agent]` deltas

**Feature**: 002-telegram-trigger
**Status**: Phase 1 design

The existing `core/config.py` already defines the `[telegram]` section (see 001-cli-bootstrap). This feature only **adds optional fields with safe defaults** — no breaking change to the on-disk format, no migration of existing config files needed.

## `[telegram]` final shape

```toml
[telegram]
# REQUIRED for trigger to function.
# Bot token from @BotFather. Stored verbatim; redacted in logs.
bot_token = ""

# REQUIRED for trigger to function.
# Telegram chat id of the group where triggers are posted.
# Find via the @userinfobot or by inspecting the bot's getUpdates response.
group_chat_id = 0

# REQUIRED — fail closed.
# Telegram user ids allowed to issue triggers.
# An empty list causes the daemon to reject every message.
allowed_user_ids = []

# NEW — optional, defaults shown.
# Long-poll timeout passed to getUpdates (seconds).
poll_timeout_seconds = 25

# NEW — optional, defaults shown.
# Cap for exponential backoff on getUpdates failures (seconds).
backoff_max_seconds = 60
```

## `[agent]` delta

The existing `[agent]` section gains one new field:

```toml
[agent]
# ... existing fields ...

# NEW — per-session worker timeout in seconds.
# 30 minutes by default. Workers exceeding this are SIGTERM'd, then SIGKILL'd
# after a 10-second grace period.
session_timeout_seconds = 1800
```

## Validation rules (pydantic)

| Field | Type | Constraints | Default |
|-------|------|-------------|---------|
| `telegram.bot_token` | str | length 0 OR matches `^\d+:[A-Za-z0-9_-]{30,}$` (Telegram bot token shape) | `""` |
| `telegram.group_chat_id` | int | any int (Telegram allows negative supergroup ids) | `0` |
| `telegram.allowed_user_ids` | list[int] | each ≥ 1 | `[]` |
| `telegram.poll_timeout_seconds` | int | ≥ 1, ≤ 60 | `25` |
| `telegram.backoff_max_seconds` | int | ≥ 1, ≤ 600 | `60` |
| `agent.session_timeout_seconds` | int | ≥ 60, ≤ 86400 | `1800` |

## Listener startup precondition

When the listener is asked to start (via `remotask telegram start`, or implicitly by the daemon), the daemon validates:

1. `bot_token` is non-empty AND matches the regex above.
2. `group_chat_id` is non-zero.
3. `allowed_user_ids` is non-empty.

Any failure → listener does not start, the CLI receives exit code 5, and the structured log records which field failed validation (without leaking secret values).

## Secret handling

- `telegram.bot_token` is already in `SECRET_KEYS` (`core/secrets.py`); `remotask config get telegram.bot_token` shows `***redacted***`.
- `remotask config set telegram.bot_token <value>` writes to disk at 0600 (existing behaviour).
- The bot token is never written to `session_events.payload` or to the listener state file.

## Backwards compatibility

- New fields are all optional; existing config files continue to load.
- No rewrite of existing config sections.
- `remotask init` will populate the new fields with defaults on fresh installs.
