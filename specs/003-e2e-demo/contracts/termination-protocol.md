# Contract: Operator-initiated Termination Protocol

**Feature**: 003-e2e-demo
**Status**: Phase 1 design

This document defines the message-level contract for stopping an in-flight session from Telegram, plus the on-host signal contract between the daemon and the worker subprocess.

## Inbound message grammar

A text message in the configured `group_chat_id` is a **termination candidate** if and only if:

1. The message has a non-null `message_thread_id` (i.e., it was posted *inside* a forum topic, not in the main chat).
2. The trimmed text matches the regex `^(done|stop|finish)$` (case-insensitive).

Note that this grammar deliberately does **not** include any session-identifier — the topic id provides that.

## Decision tree per inbound termination candidate

```
text message arrives in configured chat
        │
        ├─ sender_id NOT in whitelist
        │    → audit.log: telegram_termination_rejected (reason=unauthorized)
        │    → no Telegram reply, no signal sent
        │
        ├─ sender_id IN whitelist
        │    │
        │    ├─ message_thread_id is null (main chat)
        │    │    → fall through to the 002 trigger pipeline
        │    │      (which itself ignores non-issue-key text)
        │    │
        │    └─ message_thread_id is non-null
        │         │
        │         ├─ termination grammar does NOT match
        │         │    → fall through to issue-key trigger pipeline
        │         │
        │         └─ termination grammar matches
        │              │
        │              ├─ get_active_session_by_topic(conn, message_thread_id)
        │              │
        │              ├─ no active session in this topic
        │              │    → audit.log: telegram_termination_rejected
        │              │      (reason=no_active_session)
        │              │    → no reply
        │              │
        │              ├─ session.issue_key topic mismatch (defensive)
        │              │    → audit.log: telegram_termination_rejected
        │              │      (reason=wrong_topic)
        │              │    → no reply
        │              │
        │              └─ matched active session
        │                   ├─ session_events insert: telegram_termination_received
        │                   ├─ runtime sets `operator_stop_in_flight` on the session
        │                   ├─ os.kill(worker.pid, SIGUSR1)
        │                   ├─ start grace timer (operator_stop_grace_seconds)
        │                   └─ when worker exits OR grace expires:
        │                        ├─ exit happened in time → status=canceled,
        │                        │  error_message=operator_stop, post
        │                        │  "Session stopped by operator" to topic
        │                        └─ grace expired → reuse 002 SIGTERM ladder,
        │                           then status=canceled,
        │                           error_message=operator_stop_forced, post
        │                           "Session force-stopped by operator" to topic
```

The "main chat fall-through" branch is what enforces clarification Q1 ("topic-only") without any explicit reject — main-chat termination tokens harmlessly become a non-trigger because `done` doesn't match the issue-key regex either.

## Outbound message templates (new)

| Trigger | Template | Channel |
|---|---|---|
| Stop accepted | `Session stopped by operator.` | Topic-bound |
| Force-stop after grace expired | `Session force-stopped by operator (grace window exceeded).` | Topic-bound |
| Per-iteration progress | `Status: iteration {i}/{n} @ {iso8601}` | Topic-bound |
| Final flush after operator stop | `Status: final iteration {i} (operator_stop)` | Topic-bound |
| Final flush on natural completion | `Status: final iteration {n} (natural)` | Topic-bound |

(All other 002 templates — `Session starting…`, `Status: <state>`, `Session failed: …` — stay as-is.)

## Stop signal contract (daemon ↔ worker)

| Step | Sender | Receiver | Signal / mechanism | Effect |
|---|---|---|---|---|
| 1 | dispatcher (daemon) | worker subprocess | `os.kill(pid, SIGUSR1)` | Worker's installed handler sets a "stop_requested" flag |
| 2 | worker main loop | (self) | next loop check (≤ 0.5 s) | Print `FINAL <i> operator_stop` to stdout, flush, exit 0 |
| 3 | daemon's stdout streamer | (its own process) | line match on `FINAL` | Post the final-status template to the bound topic |
| 4 | daemon-side waiter | (kernel) | `proc.wait()` returns | Apply state transition: `canceled, error_message='operator_stop'` |
| **escalation: only if step 2 doesn't happen within `operator_stop_grace_seconds`** ||||
| 5 | escalation watchdog | worker pgroup | `os.killpg(pgid, SIGTERM)` | Reuses 002's ladder |
| 6 | escalation watchdog | worker pgroup | `os.killpg(pgid, SIGKILL)` | After 002's 10-second grace |
| 7 | daemon-side waiter | (kernel) | `proc.wait()` | Apply state transition: `canceled, error_message='operator_stop_forced'` + post force-stop message |

## Audit event payloads

All four rejected-termination payloads include the same base fields plus a `reason` discriminator:

```jsonc
// telegram_termination_rejected
{
  "reason": "unauthorized" | "wrong_topic" | "no_active_session" | "malformed",
  "sender_id": <int>,
  "message_id": <int>,
  "chat_id": <int>,
  "message_thread_id": <int|null>,
  "command_text": "<truncated to 32 chars>"
}
```

Accepted termination payload:

```jsonc
// telegram_termination_received
{
  "command": "done" | "stop" | "finish",
  "sender_id": <int>,
  "message_id": <int>,
  "chat_id": <int>,
  "message_thread_id": <int>
}
```

## Failure modes (what happens when…)

| Scenario | Behaviour |
|---|---|
| Worker exits 0 *before* SIGUSR1 arrives (race: natural completion + concurrent stop) | The signal is delivered to a defunct PID and ignored by the kernel. The daemon's exit-code path runs first; transition lands on `completed`. Audit shows `telegram_termination_received` followed by no signal (best-effort). |
| Worker is unresponsive (caught in a C-extension that ignores Python signal handlers) | Grace expires → SIGTERM → 002 ladder. State lands on `canceled` / `operator_stop_forced`. |
| Two `done` messages arrive within the grace window | The second is treated as a no-op: `operator_stop_in_flight` flag is checked on entry; if already set, the dispatcher records `telegram_termination_received` (audit-only) and does not re-send SIGUSR1. |
| Worker emits `FINAL` without operator stop (i.e., natural completion line) | Daemon posts the natural-completion template, transitions to `completed`. |
| `done` posted in a topic whose `topic_id` doesn't match any active session | Treated as `no_active_session`: silent in Telegram, audit-logged. (Intentional — no operator-visible spam.) |

## Out of scope (explicit)

The following are **NOT** in this contract; future features may add them:

- Multi-token commands (`done please`, `cancel ZXTL-1234`).
- Confirmation prompts (e.g. "are you sure?" inline keyboard).
- Resumable / partial stops (e.g. "stop after this iteration").
- Cross-topic stop commands.
- Operator-issued forced kill (operator can request stop, but cannot demand SIGKILL bypass; that path is reserved for the daemon's own watchdog).
