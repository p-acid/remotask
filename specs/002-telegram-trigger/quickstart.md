# Quickstart: Telegram Trigger

**Feature**: 002-telegram-trigger
**Audience**: the operator (you), verifying the trigger flow end-to-end on a personal Mac.

This is the manual verification flow that exercises US1 (happy path), US2 (unknown prefix), US3 (unauthorized sender), and US4 (CLI control). Run it after `/speckit-implement` finishes the feature.

## Prerequisites

- 001-cli-bootstrap installed: `remotask init`, `remotask install` succeed; daemon runs under launchd.
- A Telegram bot created via [@BotFather](https://t.me/BotFather). You have its token.
- A Telegram **forum group** (Settings → group → "Topics" enabled) where the bot is a member with the **Manage Topics** permission.
- The numeric `chat_id` of that group, and your own Telegram `user_id`. (Easiest: forward any message to [@userinfobot](https://t.me/userinfobot).)
- A registered project mapping for at least one Jira prefix:
  ```
  remotask projects add ZXTL ~/Developments/curious-frontend-next --base-branch main
  ```

## Step 1 — configure the listener

```sh
remotask config set telegram.bot_token "<bot token>"
remotask config set telegram.group_chat_id <chat id>
remotask config set telegram.allowed_user_ids <your user id>
remotask config get telegram.bot_token   # should print ***redacted***
remotask config get telegram.allowed_user_ids
```

The daemon must already be running (it is, if `remotask install` succeeded).

## Step 2 — start the listener

```sh
remotask telegram start
```

Expected: exit 0, output `listener started (whitelist=1, last_poll=just now)`.

```sh
remotask telegram status
```

Expected: `listener: running`, `degraded: no`, `active sessions: 0`, `whitelist size: 1`.

## Step 3 — happy path (US1)

In the configured Telegram forum group's **main chat** (not in any existing topic), send a message containing a registered issue key:

```
ZXTL-1234
```

Expected sequence (within ~5 seconds for the topic, longer for the worker):

1. A new forum topic named `ZXTL-1234` is created in the group.
2. The topic receives a message: `Session starting for ZXTL-1234. Worktree: <path>. Branch: <name>`.
3. The topic receives `Status: starting`, then `Status: running`.
4. (After the worker finishes) the topic receives `Draft PR opened: https://github.com/.../pull/...`.

Verify in the database:

```sh
sqlite3 ~/.local/share/remotask/state.db \
  "SELECT id, issue_key, status, topic_id, pr_url FROM sessions ORDER BY enqueued_at DESC LIMIT 1;"
```

Expected: one row with `status='pr_created'`, `topic_id` non-null, `pr_url` set.

## Step 4 — unknown prefix (US2)

Still in the main chat, send:

```
NOPE-1
```

Expected:
- A reply in the main chat: `Unknown project prefix 'NOPE'. Registered prefixes: ZXTL`.
- No new topic. No new session row.

## Step 5 — unauthorized sender (US3)

Have a friend (or a second test account) send `ZXTL-9999` from a Telegram user id NOT in `allowed_user_ids`.

Expected:
- No reply in the chat.
- No new topic.
- An entry in `~/.local/share/remotask/logs/audit.log` with `event: telegram_unauthorized`.

## Step 6 — stop the listener (US4)

```sh
remotask telegram stop
remotask telegram status
```

Expected: status shows `listener: stopped`. Sending another trigger from the whitelist now produces no response (silent — by design; the listener is off).

Restart with `remotask telegram start` to resume.

## Step 7 — failure surfacing (US5, manual induction)

To verify failure handling without writing buggy code, intentionally point a project at a non-existent path:

```sh
remotask projects add BAD /tmp/does-not-exist
```

Send `BAD-1` from a whitelisted account. Expected: a topic is created, then almost immediately receives `Session failed: <reason mentioning the missing path>`. The session row's `status` is `failed`.

Clean up: `remotask projects remove BAD`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `remotask telegram start` exits 5 | Required field missing/invalid | Check the error text; common: empty `allowed_user_ids` |
| `remotask telegram start` exits 4 | Daemon did not flip state file | Check `~/.local/share/remotask/logs/daemon.log`; Telegram API reachability? |
| Trigger ignored, status shows `degraded: yes` | ≥ 10 consecutive `getUpdates` failures | Check connectivity, then check that the bot is a member of the chat |
| Topic creation fails | Bot lacks Manage Topics permission | Re-grant in Telegram group settings; the daemon will recover on the next trigger |
| All triggers ignored | Listener not started, or whitelist empty | `remotask telegram status`; check `telegram.allowed_user_ids` |

## Cleanup after testing

```sh
remotask telegram stop
# optional: remove test projects
remotask projects remove ZXTL
```

The daemon and launchd setup remain — they were installed by 001-cli-bootstrap and are not part of this feature's lifecycle.
