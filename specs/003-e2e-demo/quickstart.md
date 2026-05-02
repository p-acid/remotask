# Quickstart: End-to-End Demo Workflow

**Feature**: 003-e2e-demo
**Audience**: the operator (you), verifying the full trigger → progress → stop loop on your Mac.

This is the manual verification flow that exercises every layer of 002 + 003 with the placeholder workload. Run it after `/speckit-implement` finishes.

## Prerequisites

- 002 quickstart already passed (Telegram bot, group, whitelist configured; `remotask init`, `remotask install`, `remotask telegram start` all working).
- One registered project for a Jira prefix you'll use for the demo, e.g.:
  ```sh
  remotask projects add ZXTL ~/Developments/curious-frontend-next --base-branch main
  ```

## Step 1 — confirm daemon + listener health

```sh
remotask daemon status
remotask telegram status
```

Both should report running. If `telegram status` shows `degraded: yes` or no `last_poll_ok_at`, fix that before continuing (most likely: bot not in chat).

## Step 2 — happy path: trigger and observe progress

In the configured Telegram forum group's **main chat**, send:

```
ZXTL-DEMO
```

Expected sequence:

1. Within ~5 seconds: a new forum topic named `ZXTL-DEMO` is created.
2. The topic receives:
   - `Session starting for ZXTL-DEMO. Worktree: <abs path>. Branch: agent/ZXTL-DEMO`
   - `Status: starting`
   - `Status: running`
3. Every 30 seconds (default `REMOTASK_DEMO_INTERVAL_SECONDS`), a progress line:
   - `Status: iteration 1/5 @ 2026-05-02T08:30:15Z`
   - `Status: iteration 2/5 @ 2026-05-02T08:30:45Z`
   - … and so on.
4. After all 5 iterations:
   - `Status: final iteration 5 (natural)`
   - `Status: completed`

Verify in the database:

```sh
sqlite3 ~/.local/share/remotask/state.db \
  "SELECT id, issue_key, status, error_message FROM sessions ORDER BY enqueued_at DESC LIMIT 1;"
```

Expected: one row with `status=completed`, `error_message` empty (or NULL).

## Step 3 — operator stop: graceful

Trigger another session:

```
ZXTL-DEMO2
```

(Yes, a different issue key — same prefix is fine since 002's same-issue rule rejects only same-key concurrents.)

Wait until you see `Status: iteration 2/5 @ …`, then **inside the topic** (not the main chat) post:

```
done
```

Expected:

1. Within ~10 seconds the topic receives:
   - `Status: final iteration 2 (operator_stop)`
   - `Session stopped by operator.`
2. The session DB row:
   ```sh
   sqlite3 ~/.local/share/remotask/state.db \
     "SELECT issue_key, status, error_message FROM sessions WHERE issue_key='ZXTL-DEMO2';"
   ```
   shows `status=canceled`, `error_message=operator_stop`.

Try the synonyms `stop` and `finish` too — same behaviour.

## Step 4 — operator stop: forced (escalation)

This step needs a worker that ignores SIGUSR1 — useful if you want to see the escalation path. The simplest way is to start a session with the stock placeholder worker, and verify graceful is what you actually get (no escalation). If you want to *force* escalation:

1. Edit `~/.config/remotask/config.toml` and set `agent.operator_stop_grace_seconds = 1` (1-second grace).
2. Restart the daemon: `remotask daemon stop && remotask daemon start`.
3. Trigger a session and post `done` immediately after the first progress line.

Even with the stock worker the grace should be enough; to truly trigger forced kill you would need a worker that ignores SIGUSR1 (out of scope for this demo). What you should *not* see is a stuck session — if grace expires, the SIGTERM ladder always fires.

If a forced kill happens, the topic receives:

- `Session force-stopped by operator (grace window exceeded).`

and the row's `error_message` is `operator_stop_forced`.

## Step 5 — negative case: unauthorized stop

Have a friend (or a second Telegram account NOT on `allowed_user_ids`) post `done` inside an active session's topic.

Expected:

- No Telegram reply.
- The worker keeps running.
- An entry appears in `~/.local/share/remotask/logs/audit.log`:
  ```jsonc
  {"event_type":"telegram_termination_rejected","reason":"unauthorized","sender_id":<their id>,...}
  ```

## Step 6 — negative case: stop in main chat

From your whitelisted account, post `done` in the **main chat** (not in a topic).

Expected:

- No Telegram reply.
- No active session is affected.
- The audit log shows nothing for this message (it harmlessly falls through the dispatcher's main-chat branch as a non-trigger; we do not audit-log every casual main-chat utterance).

## Step 7 — negative case: stop in a wrong / stale topic

Trigger and let one session complete naturally (`status=completed`). Then post `done` inside that same (now stale) topic.

Expected:

- No Telegram reply.
- An audit log entry with `reason=no_active_session` and the topic's `message_thread_id`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No progress lines, just `Session starting` | Worker isn't writing to stdout, or daemon crashed before forwarding | `remotask daemon logs --follow`; look for `worker.spawned` and any subsequent stack trace |
| `done` doesn't stop the session | You posted in the main chat, or the message has no `message_thread_id` (e.g. forum mode disabled in the group) | Confirm the message is *inside the topic* — Telegram shows a "↩ ZXTL-DEMO2" pill at the top |
| Forced kill every time | `agent.operator_stop_grace_seconds` set too low | Increase to 5+ in `config.toml`, restart daemon |
| Audit log missing | Logging not initialized (e.g. wrong XDG paths) | Check `XDG_DATA_HOME`; default is `~/.local/share/remotask/logs/audit.log` |

## Cleanup after testing

```sh
# Stop any in-flight demo sessions if they're still running
# (the daemon's natural cleanup handles them; this is just for impatient operators)
remotask daemon stop
remotask daemon start
```

The launchd unit installed by 001 is unaffected by this feature.
