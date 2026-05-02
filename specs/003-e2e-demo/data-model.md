# Data Model: End-to-End Demo Workflow

**Feature**: 003-e2e-demo
**Date**: 2026-05-02
**Status**: Phase 1 design

## Schema delta vs V0001

**No new migration in this feature.** V0001 (from 001-cli-bootstrap, reused by 002) already provides every column needed for the demo + termination flows.

| Use site | Column / table | New semantics in 003 |
|---|---|---|
| Termination terminal status | `sessions.status` | New entries land on `canceled` (existing enum value) |
| Termination reason | `sessions.error_message` | Adds two documented values: `operator_stop`, `operator_stop_forced` |
| Worker progress / final lines | `sessions.log_path` | Same per-session log file from 002; the new line shapes are written there alongside everything else |
| Termination audit | `session_events.type`, `payload` | Adds one new session-bound event type |
| Rejected-termination audit | (file) `~/.local/share/remotask/logs/audit.log` | Adds one new event type emitted via the audit logger |

## `sessions.error_message` documented values (running list)

The schema declares `error_message` as a free-form `TEXT`. We pin a small enum-by-convention so dashboards / queries can group by it.

| Value | Source feature | When set |
|---|---|---|
| `daemon_restart` | 002 | Daemon restart recovery (R10 in 002) |
| `timeout` | 002 | Per-session timeout watchdog fired |
| `operator_stop` | **003** | Operator posted termination command, worker honoured SIGUSR1, exited within grace |
| `operator_stop_forced` | **003** | Operator posted termination command, worker missed grace window, daemon escalated to SIGTERM/SIGKILL |
| _(other free-form strings)_ | various | Worker stderr-tail messages on exit-nonzero |

## Audit event taxonomy additions

Two new `session_events.type` candidates introduced by this feature; one is session-bound (DB row), the other is unbound (audit.log line):

| Type | Storage | Payload fields |
|---|---|---|
| `telegram_termination_received` | `session_events` row (session_id = the affected session) | `{command, sender_id, message_id, chat_id, message_thread_id}` |
| `telegram_termination_rejected` | `audit.log` (no session FK; reason makes session unknowable in some cases) | `{reason, sender_id, message_id, chat_id, message_thread_id, command_text}` where `reason ∈ {unauthorized, wrong_topic, no_active_session, malformed}` |

Constants for both live in `daemon/audit.py` next to the 002 set.

## Session state machine

No new states. The diagram from 002 remains correct. The change is which arrow operator-stop walks:

```
            running ----- SIGUSR1 honoured ----> canceled (error_message='operator_stop')
                  \
                   `---- SIGUSR1 ignored, SIGTERM/SIGKILL ladder fired ---->
                          canceled (error_message='operator_stop_forced')
```

Note: `operator_stop` and `operator_stop_forced` are **not** new `status` values — both transitions land on the existing `canceled` terminal state, with the reason captured in `error_message`. This is the answer to clarification Q2.

## Worker stdout line protocol (extended)

The 002 worker subprocess wrapper (`daemon/worker.py:_stream_subprocess_output`) reads the worker's stdout line-by-line. 003 keeps that single channel and adds two new line shapes:

| Pattern | Origin | Daemon action |
|---|---|---|
| `^PR_URL=(\S+)\s*$` | 002 | capture pr_url → set on session, post `Draft PR opened: …` |
| `^PROGRESS (\d+)/(\d+) (\S+)\s*$` | **003** | format and post a topic message: `Status: iteration <i>/<N> @ <iso8601>` |
| `^FINAL (\d+) (\S+)\s*$` | **003** | format and post: `Status: final iteration <i> (<reason>)`. `reason ∈ {natural, operator_stop}`. The terminal session transition is driven by exit code + presence of FINAL — see below |
| _(anything else)_ | both | append to the per-session log file only — not posted to Telegram |

**Exit code → state transition mapping** (003 worker, summary):

| Exit code | Last `FINAL` line emitted? | Resulting transition |
|---|---|---|
| 0 | `FINAL <N> natural` | `running → completed` (workload exhausted iterations) |
| 0 | `FINAL <i> operator_stop` | `running → canceled` (`error_message='operator_stop'`) |
| 0 | (none) | `running → completed` (worker exited cleanly without the line; treated as natural) |
| ≠ 0 | (any) | `running → failed` (002 generic-failure path; reason = stderr tail) |
| killed by SIGTERM/SIGKILL | (any) | `running → canceled` (`error_message='operator_stop_forced'`) when escalation came from operator-stop; otherwise `failed` reason `timeout` (002 path) |

The daemon-side wrapper distinguishes "escalation from operator stop" from "escalation from timeout" by tracking who initiated the kill: an `operator_stop_in_flight` flag set on the session-tracking object when the dispatcher first sends SIGUSR1.

## Termination command parse model

A pure in-memory record produced by `telegram/parser.py:match_termination_command`. Not persisted as a row.

```python
@dataclass(frozen=True)
class TerminationCommand:
    canonical: Literal["done", "stop", "finish"]  # always lowercase
```

Parser rules (regex `^(done|stop|finish)$`, `re.IGNORECASE`, applied to `text.strip()`):

- Match returns the lowercase canonical value.
- Anything else returns `None`.

Dispatch rules (in `daemon/dispatcher.py`):

- A non-`None` parse only triggers termination handling when the message has a non-null `message_thread_id`. (Main-chat parses are dropped silently — clarification Q1.)
- The active session for the topic is resolved via `core.db.get_active_session_by_topic(conn, message_thread_id)`. If `None`, the termination command is **rejected** with reason `no_active_session` (no Telegram reply, audit-log entry only).

## Configuration extension

One new optional field on `[agent]` (in addition to 002's `session_timeout_seconds`):

```toml
[agent]
# ... existing fields ...
operator_stop_grace_seconds = 5    # SIGUSR1 → SIGTERM escalation window
```

Validation: `int`, `≥ 1`, `≤ 30`. Default `5`. Tests override to a sub-second value via the same pydantic schema (no env var needed because tests use the schema directly).

## Placeholder worker configuration (env vars only)

The worker reads its iteration parameters from environment variables passed by the daemon at spawn time. These are **not** in `config.toml` because they are testing knobs, not operator preferences.

| Env var | Default | Range | Override surface |
|---|---|---|---|
| `REMOTASK_DEMO_ITERATIONS` | `5` | `1..1000` | tests; future "demo length" CLI flag |
| `REMOTASK_DEMO_INTERVAL_SECONDS` | `30.0` | `0.05..600` | tests use sub-second; demos use the default |

The daemon's worker module (`daemon/worker.py`) is responsible for forwarding these to the worker's environment. They are not part of the production `config.toml` schema.

## Listener / runtime / dispatcher impact (summary)

- `listener.py`: **unchanged**. It already forwards every text update to the dispatcher.
- `dispatcher.py`: gains one new branch (termination) ahead of the issue-key path; no change to whitelist / unknown-prefix / concurrency branches.
- `worker.py`: extends the stdout parser; learns to recognise `operator_stop_in_flight`; sends SIGUSR1 on operator stop; existing SIGTERM ladder reused for escalation.
- `runtime.py`: **unchanged**.
- `core/db.py`: gains `get_active_session_by_topic`.

## Secret redaction

No new secret-bearing fields. `bot_token` redaction from 002 unchanged.
