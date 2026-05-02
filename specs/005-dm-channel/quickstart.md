# Quickstart: `/cancel` Rename + `[KEY]` Prefix + Alias Deprecation

**Feature**: 005-dm-channel (narrowed scope)
**Audience**: the operator (you), verifying 005 end-to-end on your Mac.

This is the manual verification flow. Run it after `/speckit-implement` finishes. The 003/004 quickstarts are prerequisites — 005 inherits their setup unchanged.

## Prerequisites

- 002 + 003 + 004 quickstarts already passed (daemon running, listener live, `ZXTL` project registered, real Telegram bot in a forum group, bot has `Manage Topics` permission).
- The bot's Privacy Mode is OFF (recommended — same as 003/004).

## Step 1 — confirm the curated command set delta

Restart the listener so the daemon registers the new payload:

```sh
remotask telegram stop
remotask telegram start
remotask telegram status
```

Look for the existing line (004):

```text
commands:        registered (last: 2026-05-02T08:30:15)
```

If it reads `not registered (will retry on next restart)`, check `~/.local/share/remotask/logs/audit.log` for `commands_registration_failed` and resolve before continuing.

## Step 2 — observe the autocomplete menu (US1, US2)

In the configured forum group, type `/`. Expected (within ~1 second):

| Slot | Display |
|------|---------|
| 1 | `/run`    — Start a new session |
| 2 | `/cancel` — Cancel an active session |
| 3 | `/status` — Show active sessions |

`/done` MUST NOT appear in the menu (FR-004, SC-002). It still works inbound (deprecated alias) — see Steps 5–7.

If you see no menu, the registration failed or the Telegram client cached an empty list — restart the Telegram app once.

## Step 3 — `/cancel` happy path (US1)

Trigger a session you can interrupt:

```text
/run ZXTL-1234 wait around for a while
```

Wait for the first `[ZXTL-1234] Status: …` line (already prefixed — see Step 4). **Inside that topic** (NOT the main chat), post:

```text
/cancel
```

Expected within ~10 seconds (SC-001):

- `[ZXTL-1234] Status: final iteration <i> (operator_stop)`
- `[ZXTL-1234] Session canceled by operator.`

DB check:

```sh
sqlite3 ~/.local/share/remotask/state.db \
  "SELECT status, error_message FROM sessions WHERE issue_key='ZXTL-1234';"
# → canceled | operator_stop
```

Audit check:

```sh
grep '"command": "cancel"' ~/.local/share/remotask/logs/audit.log | tail -3
# → "type": "slash_command_received", "command": "cancel", ...
```

## Step 4 — `[KEY]` prefix verification (US3)

While the session from Step 3 was running (before you cancelled it), each progress message in the topic should have read like:

```text
[ZXTL-1234] Status: iteration 1/5 @ 2026-05-02T14:32:18Z
[ZXTL-1234] Status: iteration 2/5 @ 2026-05-02T14:32:30Z
...
```

The very first message in the topic — `Session starting for ZXTL-1234. Worktree: …` — MUST NOT be prefixed (FR-010). It already names the key.

**Multi-session test** (optional, if `max_concurrent ≥ 2`):

```sh
remotask config set agent.max_concurrent 2
remotask telegram restart
```

```text
/run ZXTL-1235 long task A
/run ZXTL-1236 long task B
```

Open Telegram's "All Topics" view of the parent group. Each new-message preview should begin with `[ZXTL-1235]` or `[ZXTL-1236]` — visible attribution without entering each topic. (SC-005 qualitative.)

Restore single-concurrency:

```sh
remotask config set agent.max_concurrent 1
remotask telegram restart
```

## Step 5 — deprecated `/done` alias still works (US2)

Trigger another session:

```text
/run ZXTL-1237 something
```

Wait for first progress, then **inside the topic** post:

```text
/done
```

Expected:

- The session cancels exactly like `/cancel` would (Step 3 sequence).
- The structured-log file (`~/.local/share/remotask/logs/daemon.log`) contains a WARNING line:

  ```text
  WARNING alias_deprecation alias_token=/done canonical=cancel session_id=...
  ```

- `audit.log` contains an `alias_deprecation_used` event:

  ```sh
  grep '"alias_token": "/done"' ~/.local/share/remotask/logs/audit.log | tail -1
  ```

- The autocomplete menu still does NOT show `/done` (Step 2 unchanged).

## Step 6 — deprecated plain-text alias `stop` (US2)

Trigger another session and let it stream at least one progress line:

```text
/run ZXTL-1238 ...
```

Inside the topic, post plain-text `stop` (no slash, no args):

```text
stop
```

Expected: identical cancellation + WARNING line with `alias_token=stop`. Repeat informally with `done` and `finish` to satisfy yourself that all four aliases route. Each alias_token emits its own WARNING on its first use per session.

## Step 7 — alias idempotency (US2)

Trigger a session, post `/done` to cancel it, **wait until you see the
`[ZXTL-1239] Session canceled by operator.` line in the topic** (which only
appears after the worker has reached its terminal state), then post `/done`
again. The wait is important — sending the second `/done` before the worker
has actually exited would race the cancel handler and could land while the
session is still active, breaking the determinism of the
`reason=no_active_session` outcome the second invocation must hit.

```text
/run ZXTL-1239 ...
...
/done
# wait until the topic shows: [ZXTL-1239] Session canceled by operator.
/done
```

Expected:

- The first `/done` cancels the session and logs WARNING.
- The second `/done` finds no active session (worker already exited) and audit-rejects with `reason=no_active_session`. **No second WARNING is logged for this (alias=/done, session_id) pair.**

```sh
# First, find the session_id for the most recent ZXTL-1239 session:
SID=$(sqlite3 ~/.local/share/remotask/state.db \
  "SELECT id FROM sessions WHERE issue_key='ZXTL-1239' ORDER BY enqueued_at DESC LIMIT 1;")
# Then count the alias_deprecation_used rows keyed by session_id (NOT issue_key —
# the alias_deprecation_used payload carries session_id, not issue_key).
grep '"alias_token": "/done"' ~/.local/share/remotask/logs/audit.log \
  | grep "\"session_id\": \"$SID\"" | wc -l
# → 1
```

## Step 8 — `/cancel` from main chat is rejected (US1 negative)

Trigger a session, then post `/cancel` in the **main chat** (NOT inside the topic):

```text
/run ZXTL-1240 ...
... (still running)
```

In the main chat:

```text
/cancel
```

Expected:

- No reply.
- The `ZXTL-1240` session continues unaffected.
- `audit.log` contains `slash_command_rejected reason=main_chat_cancel`:

  ```sh
  grep '"reason": "main_chat_cancel"' ~/.local/share/remotask/logs/audit.log | tail -1
  ```

Cancel `ZXTL-1240` properly (inside its topic) before continuing.

## Step 9 — distinguish `/cancel` and `/done` rejections in audit log (R5)

Repeat Step 8 with `/done` instead of `/cancel`:

```text
/run ZXTL-1241 ...
```

In the main chat:

```text
/done
```

Expected: `audit.log` records `slash_command_rejected reason=main_chat_done` (NOT `main_chat_cancel`).

```sh
grep -E '"reason": "(main_chat_cancel|main_chat_done)"' \
  ~/.local/share/remotask/logs/audit.log | tail -5
```

You should see both reason values appearing — they distinguish "operator typed `/cancel` in the wrong place" from "operator typed (deprecated) `/done` in the wrong place" for downstream analysis.

## Step 10 — backwards-compat smoke

The 002 plain-text trigger and 004 `/run` / `/status` MUST be unchanged:

In the main chat:

```text
ZXTL-1242
```

Expected: identical 002 happy path (topic created, session starts, `[KEY]`-prefixed progress).

```text
/run ZXTL-1243 add a logging line
```

Expected: identical 004 happy path with `[KEY]`-prefixed progress.

```text
/status
```

Expected: identical 004 main-chat list (no `[KEY]` prefix on the list itself — it already shows keys per row).

Inside any active topic:

```text
/status
```

Expected: identical 004 topic-detail summary (no `[KEY]` prefix on the summary body).

## Step 11 — alias deprecation idempotency across sessions (R2)

Trigger session A, `/done` it, then trigger session B and `/done` it:

```text
/run ZXTL-1244 ...
... (cancel with /done)
/run ZXTL-1245 ...
... (cancel with /done)
```

Expected: WARNING fires twice (once per session).

```sh
# Resolve session_ids for the two issue keys, then count alias_deprecation_used
# rows keyed by session_id. (The audit payload carries session_id, not
# issue_key, so grepping for the issue key directly would miss matches.)
SID_A=$(sqlite3 ~/.local/share/remotask/state.db \
  "SELECT id FROM sessions WHERE issue_key='ZXTL-1244' ORDER BY enqueued_at DESC LIMIT 1;")
SID_B=$(sqlite3 ~/.local/share/remotask/state.db \
  "SELECT id FROM sessions WHERE issue_key='ZXTL-1245' ORDER BY enqueued_at DESC LIMIT 1;")
grep '"alias_token": "/done"' ~/.local/share/remotask/logs/audit.log \
  | grep -E "\"session_id\": \"($SID_A|$SID_B)\"" | wc -l
# → 2
```

This proves the per-session keying — operators get a recurring migration signal across many sessions, not just a single warn-once-then-silent.

## Cleanup

```sh
remotask telegram stop
```

The launchd unit installed by 001 is unaffected.

## Troubleshooting

| Symptom                                          | Probable cause                                         | Fix |
|--------------------------------------------------|--------------------------------------------------------|-----|
| `/cancel` autocomplete missing, `/done` still showing | `setMyCommands` registration cached on Telegram client | Restart Telegram app; force the daemon listener to restart |
| WARNING fires every time on the same session     | `alias_deprecation_warned` set not being populated     | Check that the dispatcher's `_emit_alias_warning` is called BEFORE the cancel handler (set add must happen on first call) |
| WARNING never fires                              | Set is being cleared too eagerly                       | Check the sessions transition helper — only clear on terminal status |
| Progress line missing `[KEY]` prefix              | Bug — the call site bypassed `format_progress`         | Inspect the worker call site emitting that template |
| `Session starting for ZXTL-1234.` reads `[ZXTL-1234] Session starting for ZXTL-1234.` | Bug — template was routed through `format_progress` by mistake | Move the call back to `post_template` (no prefix) |
