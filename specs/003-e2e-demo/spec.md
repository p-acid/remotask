# Feature Specification: End-to-End Demo Workflow

**Feature Branch**: `003-e2e-demo`
**Created**: 2026-05-02
**Status**: Draft
**Input**: User description: "End-to-end demonstrable test workflow that exercises the full trigger -> background work -> progress reporting -> graceful termination loop on a single host. The operator posts a Jira-shaped issue key in the configured Telegram forum group (auth + topic creation already provided by 002). The daemon spawns a real background worker process on the registered host that performs a placeholder long-running task (e.g. timed iterations) while streaming periodic progress updates back into the bound forum topic so the operator can confirm the worker is alive without leaving Telegram. Crucially, the operator can send a 'finish' / 'stop' command from Telegram (in the bound topic, or as a reply addressing the session) and the daemon must propagate that signal to the worker, giving it a brief grace period to flush a final status before the session is marked terminal. Out of scope: real code-writing via the Claude Agent SDK, multi-host execution, persistent progress checkpoints. The goal is a runnable MVP demo that proves every layer (listener, dispatcher, worker, topic, operator-initiated termination) actually works end-to-end with a placeholder workload."

## Clarifications

### Session 2026-05-02

- Q: Where can the operator post the termination command? → A: Topic-only — termination commands posted in the main chat are silently ignored, regardless of whether they reference the issue key. This eliminates ambiguity about which session a single global command would terminate when multiple are running.
- Q: What terminal `status` should operator-initiated termination land on? → A: Both graceful and forced terminations land on `canceled` (operator intent is the same in both); `error_message` carries `operator_stop` (graceful) or `operator_stop_forced` (escalated to SIGKILL) so audit can distinguish.
- Q: What are the default placeholder workload parameters? → A: `iterations=5`, `interval=30s` (total ~2.5 minutes). Long enough for an operator to observe several progress posts and try a stop mid-run, short enough that an unattended demo doesn't drag. Tests override via the `REMOTASK_DEMO_ITERATIONS` / `REMOTASK_DEMO_INTERVAL_SECONDS` env vars.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Background worker actually runs after a trigger and reports progress (Priority: P1)

The operator posts a Jira-shaped issue key in the configured Telegram forum group. The daemon, already running on the operator's home machine, accepts the trigger (using the 002 pipeline), spawns a real background worker subprocess on that machine, and the worker begins running a placeholder long-running task. While the task runs, the operator sees periodic progress updates in the per-session forum topic ("iteration 1/N", "iteration 2/N", …) so they can leave their desk confident the work is actually happening — not just that the trigger was *accepted*.

**Why this priority**: Without this story, the 002 feature ends with "session is starting…" and silence. There is no way to validate from Telegram alone that the worker is alive on the registered PC, which is the entire user-visible promise of the system. This is the demoable proof that all layers actually connect end-to-end.

**Independent Test**: With one whitelisted operator and one registered project, send a valid issue key from Telegram and confirm: (a) a forum topic is created, (b) the topic shows the "session starting" line and at least three progress updates over time, (c) the session row in the database moves through `enqueued → starting → running` and reaches a terminal state when the placeholder task naturally finishes.

**Acceptance Scenarios**:

1. **Given** an authorized operator triggers a session with `ZXTL-1234`, **When** the worker is spawned, **Then** within 5 seconds the bound topic receives a "Session starting" message followed by the first progress update; subsequent progress updates arrive at the configured cadence until the workload completes naturally.
2. **Given** a session whose placeholder workload has finished naturally, **When** the worker exits cleanly, **Then** the topic receives a final completion message and the session row reaches `completed`.
3. **Given** the worker is running, **When** the operator inspects the topic from their phone, **Then** every progress update is visible in chronological order and clearly identifies the session (issue key + iteration index).

---

### User Story 2 - Operator can stop a running session from Telegram (Priority: P1)

A long-running session is in flight. The operator decides — for any reason (the wrong issue, no longer needed, taking too long) — to end it early. They send a short termination command (e.g. `done`, `stop`, or `finish`) inside the session's forum topic. The daemon recognises the command, signals the worker, and the worker terminates within a small grace window. The topic receives a final "stopped by operator" message and the session is marked terminal.

**Why this priority**: Without operator-initiated termination, the only ways to stop a session are (a) wait for the natural end or (b) wait for the per-session timeout from 002. Both are operationally awful: the operator cannot reclaim their machine, and a mistakenly-triggered session burns CPU until timeout. This story closes the control loop — the operator triggers and stops from the same surface.

**Independent Test**: Trigger a session, wait for at least one progress update, then post `done` in the bound topic from a whitelisted account. Confirm: the worker exits within the grace period, the topic receives a "Session stopped by operator" message, and the session row's terminal status is recorded with a reason of `operator_stop`.

**Acceptance Scenarios**:

1. **Given** a session is running with the worker streaming progress, **When** the whitelisted operator posts `done` in the bound topic, **Then** within 10 seconds the worker exits, the topic receives a final "Session stopped by operator" message, and the session row reaches a terminal state with reason `operator_stop`.
2. **Given** a session is running, **When** a non-whitelisted user posts `done` in the bound topic, **Then** the command is silently ignored — the worker keeps running, no Telegram reply is sent, and an audit-log entry records the rejected attempt.
3. **Given** no session is currently running for an issue, **When** an operator posts `done` in a stale topic, **Then** the daemon ignores the command and posts no reply.
4. **Given** an operator posts `done` in the **main chat** (not in a topic), **When** the listener receives the message, **Then** the daemon ignores it (termination commands must reference a specific session via its topic).

---

### User Story 3 - Worker flushes a final status before exiting on a stop signal (Priority: P2)

When the worker receives the operator's stop signal, it should not vanish silently. It should publish a final progress message — at minimum the iteration index it reached and a timestamp — so the operator can see "where" the work was when stopped. After that flush, the worker exits cleanly within the configured grace window; if it does not, the daemon escalates to a forced kill (reusing the 002 SIGTERM/SIGKILL ladder).

**Why this priority**: P2 because US2 already gives the operator a way to stop. This story improves the *quality* of the stop — without it, a stopped session looks indistinguishable from a hung one to the operator. P2 rather than P1 because the stop itself works without it.

**Independent Test**: Trigger a session, wait until iteration 3 progress message arrives, post `done`. Confirm the topic shows a final progress line at or near iteration 3 followed by the "stopped by operator" message — i.e., the operator can read where the worker was when stopped.

**Acceptance Scenarios**:

1. **Given** a worker is at iteration N when stop is signalled, **When** the worker receives the signal, **Then** it posts a "stopped at iteration N" final status to the topic before exiting.
2. **Given** a worker fails to exit within the grace window after stop, **When** the grace window elapses, **Then** the daemon escalates to forced termination (process-group SIGKILL) and posts a "force-stopped" message to the topic.

---

### Edge Cases

- **Stop command in the wrong topic**: A whitelisted operator posts `done` inside a topic for issue `ZXTL-1234`, but the active session is for `ZXTL-5678`. The daemon scopes the command by `message_thread_id`; the wrong-topic command is ignored (no reply), and an audit log entry records the mismatch for diagnostic purposes.
- **Multiple stop commands in quick succession**: Two `done` messages arrive within the grace window. The second is treated as a no-op (the worker is already shutting down). No duplicate stop messages are posted.
- **Worker has already finished naturally when stop arrives**: A stop command arrives one second after natural completion. The daemon ignores it (no active worker to signal), and posts no reply.
- **Daemon restart while a placeholder workload is running**: The 002 daemon-restart-recovery path applies — the session is marked `failed` with reason `daemon_restart` and the topic receives the existing restart-cleanup message. There is no auto-resume.
- **Operator sends a malformed termination command** (e.g. `done please`, `Stop?`, `STAHP`): The grammar is strict (case-insensitive single token from a small set). Anything else is treated as ordinary chat and ignored without reply.
- **Telegram outage between trigger and stop**: 002's listener-degraded backoff applies; once connectivity returns, queued stop commands are processed. Workers continue running locally regardless of Telegram availability.
- **Network partition between worker and daemon**: Workers and the daemon run as parent/child on the same host; they communicate via OS signals, not Telegram. A partition with `api.telegram.org` therefore cannot prevent stop signal delivery — only the operator's ability to *request* a stop.

## Requirements *(mandatory)*

### Functional Requirements

#### Background workload

- **FR-001**: The system MUST spawn a real background worker subprocess on the daemon's host when a trigger is accepted, replacing the 002 placeholder that raised `NotImplementedError`.
- **FR-002**: The worker MUST execute a deterministic placeholder workload consisting of a configurable number of iterations spaced by a configurable delay, so end-to-end behaviour can be exercised without invoking any external AI service. The defaults are **5 iterations × 30 seconds** (~2.5 minutes total) and MUST be overridable via the `REMOTASK_DEMO_ITERATIONS` and `REMOTASK_DEMO_INTERVAL_SECONDS` environment variables.
- **FR-003**: The worker MUST emit a progress update at the start of each iteration, including the iteration index, total iterations, and a wall-clock timestamp, formatted for Telegram readability.
- **FR-004**: When the placeholder workload completes naturally, the worker MUST exit with code 0 and the daemon MUST transition the session to `completed`.

#### Progress reporting

- **FR-005**: Each progress update MUST be posted to the session's bound forum topic; main-chat posts are not used for progress.
- **FR-006**: The system MUST rate-limit outbound progress messages to respect Telegram's per-bot limits (the 50ms spacing already enforced by 002 covers this; this requirement keeps the constraint visible).
- **FR-007**: The progress messages MUST clearly identify the session (issue key) so two parallel sessions in two topics cannot be confused if the operator scrolls between them.

#### Operator-initiated termination

- **FR-008**: The system MUST recognise a termination command consisting of a single word from a small fixed set (`done`, `stop`, `finish`), case-insensitive, posted as a text message in the session's bound topic.
- **FR-009**: The system MUST accept termination commands ONLY from senders present in the configured whitelist (same whitelist as 002's trigger gate); commands from other senders are silently ignored and audit-logged.
- **FR-010**: The system MUST scope termination commands by topic — a `done` command MUST affect only the session whose `topic_id` matches the message's `message_thread_id`. Stop commands posted in the main chat or in an unrelated topic MUST NOT terminate any session.
- **FR-011**: The system MUST relay an accepted termination command to the worker process via an OS signal that the worker handles cooperatively (giving it a chance to flush a final status before exiting).
- **FR-012**: The worker MUST install a signal handler that, on receipt of the stop signal, posts a single final-status message to its topic (or to a side channel the daemon reads) and exits cleanly within the configured grace window.
- **FR-013**: If the worker does not exit within the grace window, the daemon MUST escalate to forced termination (process-group SIGKILL via the 002 pathway) and mark the session terminal with reason `operator_stop_forced`.
- **FR-014**: On any operator-initiated stop, the daemon MUST mark the session as `canceled` (per the existing V0001 schema). `error_message` MUST be set to `operator_stop` for graceful termination and `operator_stop_forced` when the worker had to be killed via SIGKILL after exceeding the grace window.
- **FR-015**: Termination commands MUST NOT bypass the running-session lookup — if the topic has no active session, the command is dropped without reply.

#### Audit and observability

- **FR-016**: Every accepted termination command MUST insert a `session_events` row of a new event type tied to the affected session, capturing the sender id and message id of the command.
- **FR-017**: Every rejected termination command (wrong sender, wrong topic, no active session, malformed body) MUST be recorded in the audit log with sufficient context to investigate later.
- **FR-018**: Worker output (progress lines, final status, stderr) MUST continue to be persisted to the per-session log file introduced in 002.

### Key Entities *(include if feature involves data)*

- **Session** (extension of existing entity): Adds a new audit-event taxonomy entry and refines the `error_message` semantics for operator-initiated termination. No new columns; the V0001 schema remains sufficient.
- **TerminationCommand**: A parsed inbound text message that matches the termination-command grammar in a session's bound topic. Carries `command` (one of the fixed set), `session_id` (resolved by topic), `sender_id`, `message_id`. Lives only in memory; not persisted as an entity, but its acceptance/rejection produces audit rows.
- **PlaceholderWorker**: A subprocess that owns a sequence of iterations. Configured via environment variables passed by the daemon (`REMOTASK_DEMO_ITERATIONS`, `REMOTASK_DEMO_INTERVAL_SECONDS`). Owns its own signal handler for the stop signal.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From the moment a valid trigger is posted in Telegram, an operator sees the first progress message in the bound topic within 5 seconds on a typical home network. (Reuses the SC-001 budget from 002.)
- **SC-002**: From the moment a stop command is posted in the bound topic, the operator sees the worker's final-status message and a "stopped by operator" message within 10 seconds, on a typical home network.
- **SC-003**: When the operator stops a session, the actual subprocess on the host exits within 15 seconds (graceful path) — verified by absence of the worker PID — or is force-killed by 20 seconds.
- **SC-004**: The end-to-end happy path (trigger → progress → natural completion) and the end-to-end stopped path (trigger → progress → operator stop → flush → exit) each pass an automated integration test using fake Telegram + a real worker subprocess.
- **SC-005**: A whitelisted operator can demonstrate the full loop (trigger, observe progress, stop, see final status) using **only** the Telegram client on their phone — no SSH, no terminal, no manual database inspection.
- **SC-006**: 100% of stop commands from non-whitelisted senders produce zero visible Telegram response and 100% audit-log coverage.

## Assumptions

- The 002 trigger pipeline (listener, dispatcher, topic creation, worktree, audit, sessions table) is in place and functional. This feature only **fills in** the worker entrypoint and **adds** the operator-initiated termination path.
- The placeholder workload is a synthetic CPU-light loop; resource usage is negligible compared to a real agent run, so timeout and concurrency caps from 002 do not need adjustment.
- The default workload parameters (5 iterations × 30 seconds) yield a ~2.5-minute run — short enough to keep an unattended demo bearable, long enough that an operator can observe several progress posts and trigger a mid-run stop. Integration tests override these to single-digit-second runs via the documented env vars.
- The grace window for graceful shutdown (FR-012) is short — single-digit seconds — because the placeholder has nothing real to checkpoint. Real agents will need a longer window in a future feature.
- Stop commands are a *thin* grammar — single token, fixed set. A future feature may broaden this (e.g. `/cancel ZXTL-1234` from the main chat, free-form replies that the agent interprets), but those are explicitly out of scope here.
- The signal used for termination is `SIGTERM` (per the 002 ladder): `SIGTERM` then grace then `SIGKILL`. The worker's cooperative handler is the only new code path on the kill side.
- Operator identity for termination commands is the same Telegram-side whitelist used for triggers; there is no separate authorisation layer for stop.
- The placeholder worker writes progress to **stdout** in a small protocol (`PROGRESS i/N <timestamp>` lines) that the existing worker subprocess wrapper streams to the topic. This mirrors how 002 already extracts `PR_URL=` lines from stdout, so no new IPC channel is required.
- All Telegram traffic remains via the existing long-poll listener; no new external bindings.
- This feature does not introduce a new database migration. The existing V0001 schema continues to be sufficient.
- The worker still creates and uses an isolated git worktree (per 002), even though the placeholder doesn't modify it. This keeps the spawn path identical to a real-agent path so the demo exercises every layer.
