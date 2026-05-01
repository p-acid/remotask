# Data Model: Telegram Trigger

**Feature**: 002-telegram-trigger
**Date**: 2026-05-01
**Status**: Phase 1 design

## Schema delta vs V0001

**No new migration in this feature.** V0001 (from 001-cli-bootstrap) already provides every column required for the trigger flow:

| Table | Column | Use in this feature |
|-------|--------|---------------------|
| `sessions` | `topic_id` (INTEGER) | Telegram forum topic's `message_thread_id` |
| `sessions` | `trigger_user` (INTEGER) | Telegram sender id of the trigger message |
| `sessions` | `trigger_text` (TEXT) | Raw trigger message text (for audit) |
| `sessions` | `pr_url`, `pr_number` | Filled by the worker on `pr_created` transition |
| `sessions` | `worktree_path`, `branch` | Filled by the worker during `starting` |
| `session_events` | `type`, `payload` | Audit-event taxonomy below |
| `locks` | `resource`, `holder_session` | Per-issue advisory lock |

A V0002 migration is **not** introduced. If a future iteration needs additional columns (e.g., `trigger_chat_id` to support multi-chat), that migration will land in a separate, focused PR.

## Session state machine

```
        +-----------+   accepted    +----------+   spawn ok    +---------+
trigger | enqueued  | ------------> | starting | -----------> | running |
   ---> +-----------+               +----------+              +---------+
                                          |                        |
                                          | spawn fail             | exit 0 + PR
                                          v                        v
                                     +--------+              +-------------+
                                     | failed |              | pr_created  |
                                     +--------+              +-------------+
                                          ^                        |
                                          | exit !=0 / timeout     | (terminal)
                                          |                        v
                                          |                  +-----------+
                                     +---------+             | completed |
                                     | running |------------>+-----------+
                                     +---------+
                                          ^
                                          | (also reachable from running on
                                          |  any unhandled exception)
```

State semantics (matching the `CHECK` constraint in V0001):

| State | Meaning | Exit transitions |
|-------|---------|------------------|
| `enqueued` | Trigger accepted; row inserted; worker not yet started | → `starting` (normal), → `failed` (pre-spawn validation failure), → `canceled` (operator stop) |
| `starting` | Worktree being created, branch checkout in progress | → `running` (success), → `failed` (worktree/checkout failure) |
| `running` | Worker subprocess executing the agent | → `pr_created` (PR opened), → `completed` (no PR but exit 0), → `failed` (exit ≠ 0 / timeout / exception) |
| `pr_created` | Agent opened a draft PR; **terminal for state purposes**, but allows retrigger on the same issue (R7) | (terminal) |
| `completed` | Agent finished without a PR; **terminal**; allows retrigger | (terminal) |
| `failed` | Worker did not finish successfully; **terminal**; allows retrigger | (terminal) |
| `canceled` | Operator-initiated stop; **terminal** | (terminal) |

**Invariants**:
- A non-terminal state implies the daemon has an active worker subprocess (or is about to spawn one). On daemon startup, all rows in non-terminal states are forcibly transitioned to `failed` with `error_message='daemon_restart'` (R10).
- `topic_id` MUST be non-NULL once `status` ≠ `enqueued`.
- `worktree_path` and `branch` MUST be non-NULL once `status` = `running`.
- `pr_url` and `pr_number` MUST be non-NULL once `status` = `pr_created`.

## Concurrency rules

| Rule | Mechanism |
|------|-----------|
| Same issue cannot have two active sessions | Pre-insert query: reject if a row exists for `issue_key` with `status IN ('enqueued','starting','running')`. The check + insert is wrapped in a single transaction holding `BEGIN IMMEDIATE`. |
| `max_concurrent` cap (config: `agent.max_concurrent`, default 1) | Counted as `SELECT COUNT(*) WHERE status IN ('enqueued','starting','running')`; new triggers above the cap are rejected with a clear in-channel reply. |
| Per-issue advisory lock | `locks.resource = 'issue:<KEY>'`, `holder_session = <session_id>`. Released in the same transaction as the terminal state transition. |

## Audit event taxonomy

`session_events.type` values introduced by this feature:

| Type | When written | `payload` (JSON) shape |
|------|--------------|------------------------|
| `telegram_message_received` | Every parsed inbound message that contains an issue-key pattern (regardless of accept/reject) | `{message_id, sender_id, chat_id, text, parsed_key}` |
| `telegram_unauthorized` | Sender id not in whitelist | `{message_id, sender_id, chat_id}` |
| `telegram_unknown_prefix` | Issue key prefix not in `projects` | `{prefix, registered_prefixes}` |
| `telegram_already_in_flight` | Same-issue retrigger rejected | `{existing_session_id, existing_topic_id}` |
| `telegram_topic_create_failed` | `createForumTopic` returned an error | `{error_code, description}` |
| `state_transition` | Every session state change (`enqueued`→…→terminal) | `{from, to, at}` |
| `worker_spawn` | Worker subprocess started | `{pid, cmd}` |
| `worker_exit` | Worker subprocess exited | `{pid, exit_code, signal}` |
| `worker_timeout` | Per-session timeout fired | `{pid, timeout_s}` |
| `daemon_restart` | Session terminated due to daemon restart (R10) | `{prior_status}` |
| `listener_degraded` | ≥10 consecutive `getUpdates` failures (R8) | `{consecutive_failures, last_error}` |

All non-`state_transition` types may be written without an attached session (`session_id` is then NULL — which V0001 currently disallows because `session_id NOT NULL` and `REFERENCES sessions(id) ON DELETE CASCADE`).

**Constraint clarification**: For events not tied to a specific session (`telegram_unauthorized`, `telegram_unknown_prefix`, `listener_degraded`), the daemon writes a structured-log line at level `WARNING` with the same `payload` shape, but does not insert into `session_events`. This preserves the V0001 schema invariants while still providing an audit trail. The audit-log file location is `~/.local/share/remotask/logs/audit.log` (already created by the existing logging setup).

## Listener state file

Path: `~/.local/share/remotask/listener.state`
Format: JSON, written atomically (write-tmp + rename).
Writer: daemon, at most once per second (or on state change).
Readers: `remotask telegram status`, future health-check tooling.

```json
{
  "running": true,
  "started_at": 1746115200,
  "last_poll_ok_at": 1746115245,
  "consecutive_failures": 0,
  "active_sessions": 1,
  "whitelist_size": 2,
  "degraded": false
}
```

## Listener command file

Path: `~/.local/share/remotask/listener.cmd`
Format: JSON, single-line.
Writer: CLI (`remotask telegram start|stop`).
Reader: daemon, on receipt of `SIGUSR1`.

```json
{"seq": 17, "command": "stop"}
```

`seq` is monotonic per-CLI-invocation to disambiguate rapid sequences. The daemon stores the last applied `seq` in memory and ignores commands with `seq <= last_applied`.

## Project resolution

`Project.by_prefix(prefix: str) -> Project | None` (new helper in `core/projects.py`):
- Looks up `projects.jira_key` field where `jira_key` is exactly the prefix (e.g., `ZXTL`). The existing schema stores per-project rows keyed by `jira_key`, which is the project prefix in this design.
- If `enabled = 0`, treat as not registered (the dispatcher replies "unknown prefix" — same UX).

## Configuration extension

The `[telegram]` section in `core/config.py` already exists:

```toml
[telegram]
bot_token = "<secret>"
group_chat_id = -100123456789
allowed_user_ids = [11111111, 22222222]
```

This feature adds two **optional** fields with safe defaults:

```toml
poll_timeout_seconds = 25       # long-poll timeout passed to getUpdates
backoff_max_seconds = 60        # cap on exponential backoff
```

And a new field on `[agent]`:

```toml
session_timeout_seconds = 1800  # per-session worker timeout (default 30 min)
```

All three are added to the existing pydantic models in `core/config.py`. Defaults match R8 / R9 above.

## Secret redaction

`telegram.bot_token` is already in the `SECRET_KEYS` set (verified in 001-cli-bootstrap). No change.
