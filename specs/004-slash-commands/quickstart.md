# Quickstart: Telegram Slash-Command Surface

**Feature**: 004-slash-commands
**Audience**: the operator (you), verifying the slash-command surface end-to-end on your Mac.

This is the manual verification flow. Run it after `/speckit-implement` finishes.

## Prerequisites

- 002 + 003 quickstarts already passed (daemon running, listener live, `ZXTL` project registered, real Telegram bot in a forum group).
- Bot's Privacy Mode is OFF (recommended — clarification Q1). Slash commands will work either way; OFF lets you also test the 003 plain-text path side-by-side.

## Step 1 — confirm registration

Restart the listener so the daemon has a chance to call `setMyCommands`:

```sh
remotask telegram stop
remotask telegram start
remotask telegram status
```

Look for the new line:

```
commands:        registered (last: 2026-05-02T08:30:15)
```

If it reads `not registered (will retry on next restart)`, check `~/.local/share/remotask/logs/audit.log` for `commands_registration_failed` and resolve before continuing.

## Step 2 — observe the autocomplete menu (US1)

Open any chat with the bot — the configured group's main chat, OR a 1:1 DM with the bot. Type `/`. Expected (within ~1 second):

| Slot | Display |
|------|---------|
| 1 | `/run`    — Start a new session |
| 2 | `/done`   — End the current session |
| 3 | `/status` — Show active sessions |

If you see no menu, the registration failed or the Telegram client cached an empty list — restart the Telegram app once.

## Step 3 — `/run` with a Jira-key (US1)

In the configured group's main chat, send:

```
/run ZXTL-1234 also please add a test
```

Expected sequence (same as 003 + `trigger_text` carrying the trailing args):

1. Forum topic `ZXTL-1234` created.
2. `Session starting for ZXTL-1234. Worktree: …`
3. Progress lines.
4. Final: `Status: final iteration N (natural)` then `Status: completed`.

DB check:

```sh
sqlite3 ~/.local/share/remotask/state.db \
  "SELECT issue_key, trigger_text FROM sessions WHERE issue_key='ZXTL-1234';"
# → ZXTL-1234 | also please add a test
```

## Step 4 — `/run` with free-text (US4)

Configure the default project first:

```sh
remotask config set agent.default_project_jira_key ZXTL
```

Then in the group's main chat:

```
/run fix the cache layer please
```

Expected:

1. New topic with a synthetic name like `run-2026-05-02-14-fix-the-cache-a3f9b1`.
2. `Session starting for run-2026-05-02-14-fix-the-cache-a3f9b1. Worktree: …` (using the ZXTL project's repo).
3. Progress lines, completion.

DB check:

```sh
sqlite3 ~/.local/share/remotask/state.db \
  "SELECT issue_key, trigger_text FROM sessions ORDER BY enqueued_at DESC LIMIT 1;"
# → run-2026-05-02-14-fix-the-cache-a3f9b1 | fix the cache layer please
```

## Step 5 — `/done` (US2)

Trigger a session you can interrupt (e.g. another `/run ZXTL-1235 ...`), wait for the first progress line, then **inside that topic** post:

```
/done
```

Expected within ~10 seconds:

- `Status: final iteration <i> (operator_stop)`
- `Session stopped by operator.`
- DB row `status=canceled, error_message=operator_stop`.

## Step 6 — `/status` main chat (US3)

While at least one session is running and at least one terminal session exists, post in the main chat:

```
/status
```

Expected reply (10-line cap, most-recent-first):

```
Active sessions (1):
ZXTL-1235        running    iteration 2/5     45s ago

Type /status inside a topic for that session's detail.
```

If no sessions are active:

```
No active sessions.
```

## Step 7 — `/status` topic-detail (US3)

Inside a session-bound topic post `/status`. Expected:

```
ZXTL-1235
status:    running
iteration: 2/5 @ 2026-05-02T14:32:18Z
started:   45 seconds ago
worktree:  ~/Developments/wt/ZXTL-1235
```

In a stale topic (no active session), expected: `No active session in this topic.`

## Step 8 — negative: empty `/run`

Post `/run` with no arguments (in the main chat or a topic):

```
/run
```

Expected reply (chat-of-origin):

```
Usage: /run <PREFIX>-<NUM>  or  /run <free text> (requires agent.default_project_jira_key)
```

Audit log: `slash_command_rejected` with `reason=empty_args`.

## Step 9 — negative: `/run` free-text without default project

Unset the default project:

```sh
remotask config set agent.default_project_jira_key ""
```

Post `/run fix the cache`. Expected reply (chat-of-origin):

```
No default project configured. Set agent.default_project_jira_key in config.toml or use /run <PREFIX>-<NUM>.
```

Audit log: `slash_command_rejected` with `reason=no_default_project`.

(Restore the default project before continuing.)

## Step 10 — negative: unauthorized `/run`

Have a non-whitelisted account post `/run ZXTL-9000` in the group. Expected:

- No Telegram reply.
- No session inserted.
- Audit log: `slash_command_rejected` with `reason=unauthorized`.

## Step 11 — negative: `/done` in main chat

From your whitelisted account post `/done` in the main chat (NOT inside a topic). Expected:

- No Telegram reply.
- No worker is signalled.
- Audit log: `slash_command_rejected` with `reason=main_chat_done`.

## Step 12 — backwards-compat smoke

Verify 003's plain-text trigger still works (since spec assumption requires Privacy Mode OFF):

In the main chat post `ZXTL-1236` (no slash). Expected: identical happy-path behaviour to before this feature landed.

In an active topic post `done` (no slash). Expected: identical operator-stop behaviour.

If Privacy Mode is ON, both above will silently fail — that is the expected degraded posture.

## Cleanup

```sh
remotask telegram stop
# Optional: restore default project key
remotask config set agent.default_project_jira_key ""
```

The launchd unit installed by 001 is unaffected.
