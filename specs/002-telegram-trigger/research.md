# Phase 0 Research: Telegram Trigger

**Feature**: 002-telegram-trigger
**Date**: 2026-05-01

Each entry below documents a decision, why it was taken, and which alternatives were considered and rejected. Items here resolve all `NEEDS CLARIFICATION` candidates from the plan's Technical Context so Phase 1 design can proceed without open questions.

---

## R1. Telegram delivery mode: long-poll vs webhook

**Decision**: Long-poll using `getUpdates` with a 25-second timeout.

**Rationale**:
- The daemon runs on a personal Mac behind NAT. Webhooks require a publicly reachable HTTPS endpoint, which violates the constitution's "no external exposure during MVP" rule (Principle IV) and would force a tunnel dependency (Tailscale, Cloudflare).
- Long-poll's outbound-only model fits the security-by-default posture (Principle VI); the daemon never opens an inbound port for Telegram.
- A 25-second long-poll timeout means at most one Telegram round-trip per ~25 s of idle time — negligible cost on a home network.

**Alternatives rejected**:
- **Webhook**: Requires public HTTPS + public DNS; explicitly out-of-scope per PRD §12 / Principle IV.
- **Telegram MTProto (user account, not bot)**: Different auth model; bot API is the right fit for a service trigger.

---

## R2. Worker invocation: subprocess vs in-process

**Decision**: Each worker runs as a child subprocess of the daemon, executing a small Python entrypoint that itself drives `claude-agent-sdk`.

**Rationale**:
- Crash isolation: an SDK panic, infinite loop, or pathological prompt cannot bring down the daemon (which holds the listener and the PID lock).
- Per-session timeout enforcement is straightforward via `os.killpg` on the worker's process group.
- Resource accounting (CPU, FDs) per session is trivially attributable.
- Future hardening (cgroups, jails, sandbox-exec on macOS) becomes incremental — no architectural rewrite.

**Alternatives rejected**:
- **In-process worker** (asyncio task within daemon): SDK lifecycle bugs would corrupt daemon state; signal handling becomes ambiguous; one bad session could deadlock the listener.
- **External job queue (Celery, RQ)**: Massive over-engineering for ≤ 3 sessions/day; introduces broker dependency. Constitution Principle IV.

---

## R3. Forum topic creation contract

**Decision**: Use `createForumTopic` with `name=<issue_key>` (e.g., `ZXTL-1234`); store the returned `message_thread_id` in `sessions.topic_id`.

**Rationale**:
- `topic_id` column already exists in V0001 with the right type (`INTEGER`).
- Topic name = issue key gives the operator instant visual mapping in the Telegram client.
- All subsequent `sendMessage` calls for that session pass `message_thread_id` to route into the topic.
- If creation fails (group is not a forum, bot lacks `manage_topics` permission), the daemon posts a single error in the main chat and rejects the trigger; it does not retry the create indefinitely.

**Alternatives rejected**:
- **One topic per project, threads-by-issue**: Telegram has no concept of nested threads; clutters the topic with multiple sessions and breaks 1:1:1:1 (Principle III).
- **Reuse the same topic across same-issue retriggers**: Conflicts with "session = topic" mapping; complicates audit because two distinct workers would post to one topic.

---

## R4. Listener concurrency model

**Decision**: A single asyncio event loop hosted in a dedicated thread launched by the daemon main process. The asyncio loop runs the long-poll listener and the post-message-to-topic outbound queue. Worker subprocesses are spawned via `asyncio.create_subprocess_exec` so their lifecycle integrates cleanly.

**Rationale**:
- The existing daemon `lifecycle.Lifecycle` uses signal handlers and a `threading.Event` for shutdown — already thread-friendly.
- Telegram's API is naturally request/response; a single-threaded async loop is sufficient for one chat.
- Putting asyncio in a dedicated thread (not the main thread) keeps signal handling working on the main thread, which is required for SIGTERM/SIGINT to be received reliably on macOS.

**Alternatives rejected**:
- **Pure threaded listener with `requests`**: Would require thread pool + locks for the outbound queue; harder to write robust backoff and cancellation.
- **`trio` / `anyio`**: Added dependency without enough payoff at this scale.
- **asyncio on the main thread**: Conflicts with the existing signal-based shutdown; would force a rewrite of `lifecycle.py`.

---

## R5. CLI ↔ daemon control transport (interim)

**Decision**: For MVP, `remotask telegram start/stop` write a small command file to `~/.local/share/remotask/listener.cmd` and signal the daemon (SIGUSR1) to read it. `remotask telegram status` reads `~/.local/share/remotask/listener.state` (JSON, written by the daemon at most once per second).

**Rationale**:
- Avoids introducing the daemon HTTP API in this feature (deferred per Constitution Check entry).
- File + signal is portable across macOS and Linux without extra deps.
- Atomic-write pattern (write to `.tmp`, rename) keeps the state-file readable at any time.
- The "command file + SIGUSR1" channel is intentionally minimal — not a generic RPC, just `start | stop` plus a sequence number to detect re-issued commands.

**Alternatives rejected**:
- **Full HTTP API right now**: Doubles the feature's surface area; dilutes test coverage; couples Telegram readiness to API readiness. Constitution Principle IV.
- **Unix domain socket**: Constitution D14 forbids a separate IPC alongside HTTP; we'd be introducing one only to remove it.
- **Direct DB-row "intent" inserts**: Polling a DB for control commands is wasteful and fights the existing schema.

---

## R6. Schema delta vs V0001

**Decision**: No new migration in this feature. V0001 already provides `sessions.topic_id`, `sessions.trigger_user`, and `sessions.trigger_text` — exactly the fields needed.

**Rationale**:
- The fewer migrations, the safer the data path — Principle IV.
- An audit-event taxonomy can live in `session_events.type` (already a free-form `TEXT`); no schema change needed.
- If future research finds a missing column (e.g., per-issue cooldown), a V0002 migration will be added in a focused PR; the bar is "migrating costs less than working around it".

**Alternatives considered**:
- **Add `audit_log` table**: Rejected — `session_events` plus structured logs already cover the principle VII requirement; a parallel table would duplicate state.
- **Add per-project `last_triggered_at`**: Rejected as premature optimization (no rate-limit feature in MVP).

---

## R7. "Active session" definition for FR-010

**Decision**: A same-issue retrigger is rejected when `status` is one of `enqueued`, `starting`, `running`. The states `pr_created`, `completed`, `failed`, `canceled` are all considered terminal for retrigger purposes.

**Rationale**:
- `pr_created` means the agent finished its work; reopening the same issue is a legitimate retry (e.g., reviewer asked for changes).
- `failed`/`canceled` retrigger is the natural recovery path.
- Allowing retrigger from `pr_created` keeps the operator's mental model simple: "if the topic shows the PR or shows a failure, you can re-send the issue key".

**Alternatives rejected**:
- **Reject on `pr_created` too**: Would require a manual "release" step, which has no clear UX in Telegram and contradicts SC-005's 10-minute round-trip target.

---

## R8. `getUpdates` failure backoff

**Decision**: Exponential backoff starting at 1 s, doubling on each consecutive failure, capped at 60 s. After 10 consecutive failures, the listener marks itself `degraded` in `listener.state` (still attempting) and emits a warning audit log every 5 minutes.

**Rationale**:
- Telegram occasionally serves 502s during platform maintenance; aggressive retry would amplify the outage.
- Capping at 60 s preserves SC-001 (5-second acknowledgement) once the outage clears.
- Reporting `degraded` in `status` gives the operator a clear signal without paging them with errors on every retry.

**Alternatives rejected**:
- **Crash the daemon on 5xx**: Catastrophic — a Telegram outage would take down the entire trigger system, including in-flight workers.
- **No backoff (tight retry)**: Risks getting the bot rate-limited, which complicates recovery.

---

## R9. Worker timeout enforcement

**Decision**: Per-session timeout (default 30 minutes, configurable via `agent.session_timeout_seconds` — new field) enforced by an asyncio watchdog that calls `os.killpg(worker.pid, SIGTERM)` then `SIGKILL` after a 10-second grace period.

**Rationale**:
- Process-group kill ensures grandchildren (e.g., `git`, `claude`) are terminated, not orphaned.
- 30-minute default reflects realistic agent task duration without needing per-task tuning at MVP.
- The grace period gives the SDK a chance to flush its last status update to the topic.

**Alternatives rejected**:
- **No timeout in MVP**: A hung worker is a real failure mode; without a timeout, US5 fails its acceptance scenario.
- **SIGKILL immediately**: Loses the "what went wrong" tail of the worker log.

---

## R10. Daemon-restart recovery

**Decision**: On startup, the runtime queries `sessions WHERE status IN ('enqueued','starting','running')` and for each row:
1. Updates `status='failed'`, `ended_at=now()`, `error_message='daemon_restart'`.
2. Appends a `session_events` row of type `daemon_restart`.
3. If `topic_id` is set, posts a one-line "session terminated by daemon restart" message to the topic. If the post fails (network, etc.), it is logged but does not block startup.

**Rationale**:
- Auto-resuming a worker is unsafe — its previous state (open file handles, partial git state) is unknowable.
- Marking failed and notifying the operator preserves the audit trail (Principle VII).
- The post-to-topic is best-effort; daemon startup must not block on Telegram availability.

**Alternatives rejected**:
- **Silent cleanup**: Operator would see a stale "running" session indefinitely on retry.
- **Auto-resume**: Out of scope for MVP; would require checkpointing the worker's progress, which `claude-agent-sdk` does not expose.

---

## Summary

All 10 items resolved; no `NEEDS CLARIFICATION` markers remain. Phase 1 design (data model, contracts, quickstart) proceeds.
