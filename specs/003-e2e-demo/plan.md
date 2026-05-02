# Implementation Plan: End-to-End Demo Workflow

**Branch**: `003-e2e-demo` | **Date**: 2026-05-02 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/003-e2e-demo/spec.md`

## Summary

Fill in the production worker entry point that 002 left behind as `NotImplementedError`, and add an operator-initiated termination loop on top of the existing 002 trigger pipeline. The daemon's worker subprocess becomes a deterministic placeholder script that loops `N` iterations × `T` seconds while streaming `PROGRESS i/N <ts>` lines to its bound forum topic. The listener gains a second message-handling branch: when an authorized whitelisted user posts `done` / `stop` / `finish` in a session-bound topic, the daemon resolves the topic to its session, sends `SIGUSR1` to the worker, the worker's signal handler flushes a final-status line and exits, and the session lands on `canceled` with `error_message='operator_stop'`. If the worker doesn't exit within a small grace window, the existing 002 SIGTERM/SIGKILL ladder fires and the row is marked `canceled` with `operator_stop_forced`.

This is explicitly a demo / test feature: no real AI, no Jira fetch, no PR creation. The point is to exercise every layer (listener → dispatcher → worker → topic → operator-initiated stop) end-to-end so the operator can prove the full loop works using only their phone.

## Technical Context

**Language/Version**: Python 3.11+ (constraint inherited from constitution and 001/002).
**Primary Dependencies**:
- existing: `httpx`, `claude-agent-sdk` (installed but not invoked here), `typer`, `pydantic`, `structlog`, `pytest-asyncio`. No new runtime dependencies.
- standard library: `signal`, `asyncio`, `subprocess`, `os`, `re`.
**Storage**: existing SQLite at `~/.local/share/remotask/state.db`. **V0001 schema is sufficient — no migration.** All new behaviour is captured via existing `sessions` columns and `session_events` row inserts (new event types).
**Testing**: `pytest` + `pytest-asyncio` (already in 002), `tests/fakes/fake_telegram.py` reused, **a new tiny placeholder worker subprocess** invoked from integration tests instead of `tests/fakes/fake_agent` (the demo worker is itself the production worker; tests use it directly with shortened iteration parameters).
**Target Platform**: macOS (primary; signals + process groups already exercised by 002), Linux (best-effort).
**Project Type**: single-project CLI + long-running daemon. Same layout as 002.
**Performance Goals**: trigger-to-first-progress under 5 seconds (SC-001, mirrors 002). stop-command-to-final-status under 10 seconds (SC-002). Subprocess exit under 15 s graceful / 20 s forced (SC-003).
**Constraints**:
- Single-host, single-user.
- No new external bindings; everything goes through the existing 002 long-poll listener and on-host signals.
- The worker MUST run inside the per-session git worktree to keep the spawn path identical to a future real-agent path (003 is the production worker even if its workload is synthetic).
- No new database migration; if the implementer hits a missing column, that's a sign to revisit V0001 in a focused PR rather than improvise.
**Scale/Scope**: 1–3 sessions per day, 5 iterations × 30 s default workload (~2.5 min), single concurrent session (matches 002 default `max_concurrent=1`).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **I. Jira as Single Source of Truth**
  - The demo worker performs no Jira reads or writes. It is a synthetic loop. No new local task/issue domain is introduced.
- [x] **II. Daemon-Centric Architecture**
  - All new logic — termination parsing, session-by-topic lookup, signal dispatch, audit events — lives in the daemon (`src/remotask/daemon/*`). The worker subprocess is itself spawned by the daemon, not by any client. CLI surface is unchanged from 002.
- [x] **III. Strict Session Isolation**
  - The 1:1:1:1 mapping (issue / worktree / branch / topic) from 002 is preserved. The placeholder workload runs *inside* the session worktree even though it doesn't modify the working tree. Termination is scoped strictly by `topic_id` (FR-010).
- [x] **IV. MVP-First, Incremental Hardening**
  - This feature is explicitly the test/demo cut. It does NOT introduce: real AI, multi-host, persistent checkpoints, two-way conversational replies, web GUI. Each is named in the spec's Out-of-scope or Assumptions.
- [x] **V. Spec-Driven Development**
  - This plan derives from `specs/003-e2e-demo/spec.md` (with three clarifications recorded in the spec's Clarifications section).
- [x] **VI. Security by Default**
  - Whitelist gate applies to termination commands too (FR-009). No new tokens, no new external bindings, no denylist additions. The worker subprocess inherits the daemon's process-group kill ladder.
- [x] **VII. Observability & Auditability**
  - Two new event types (`telegram_termination_received`, `telegram_termination_rejected`); rejected commands always produce a structured warning in `audit.log`. The per-session log file (002) continues to capture all worker stdout/stderr including the `FINAL` line.

All seven gates **PASS**. No Complexity Tracking entries needed.

## Project Structure

### Documentation (this feature)

```text
specs/003-e2e-demo/
├── plan.md                 # This file
├── research.md             # Phase 0 output (signal choice, IPC protocol, dispatcher branching)
├── data-model.md           # Phase 1 output (new event taxonomy + termination parse model)
├── contracts/
│   ├── termination-protocol.md  # message grammar + stop signal contract
│   └── worker-stdout-protocol.md# PROGRESS / FINAL line shapes
├── quickstart.md           # Manual demo flow (trigger → progress → stop → exit)
├── checklists/
│   └── requirements.md     # Spec quality (already passing)
└── tasks.md                # Created later by /speckit-tasks
```

### Source Code (repository root)

```text
src/remotask/
├── agent/
│   ├── __init__.py            # NEW package
│   └── demo_worker.py         # NEW: placeholder iterating worker (the *production* entry point for 003)
├── daemon/
│   ├── dispatcher.py          # MODIFIED: add second branch — termination command vs trigger
│   ├── worker.py              # MODIFIED: SIGUSR1 plumbed end-to-end; FINAL stdout line parsed; default argv now points at agent.demo_worker
│   ├── topic.py               # MODIFIED: add 3 new templates (progress, final, operator-stopped)
│   ├── audit.py               # MODIFIED: add 2 new event constants
│   ├── sessions.py             # MODIFIED: thin "set canceled by operator" helper
│   └── ...                    # listener, runtime, listener_state, listener_cmd unchanged
├── telegram/
│   └── parser.py              # MODIFIED: add `match_termination_command(text) -> Command | None`
├── core/
│   └── db.py                  # MODIFIED: add get_active_session_by_topic(conn, topic_id)
└── ...

tests/
├── unit/
│   ├── test_telegram_parser.py    # MODIFIED: add cases for the termination grammar
│   ├── test_dispatcher.py         # MODIFIED: termination accept + reject branches
│   └── test_demo_worker.py        # NEW: placeholder loop semantics (iteration count, env-var override, signal handler)
└── integration/
    ├── test_demo_natural_completion.py  # NEW: trigger → 3 progress lines → exit 0 → completed
    ├── test_operator_stop.py            # NEW: trigger → stop → SIGUSR1 → FINAL line → canceled
    ├── test_operator_stop_forced.py     # NEW: trigger → stop → worker ignores signal → SIGKILL → operator_stop_forced
    └── test_termination_rejection.py    # NEW: wrong topic / non-whitelisted / no active session
```

**Structure Decision**: Add a new `src/remotask/agent/` package (just `demo_worker.py` + `__init__.py`). Everything else is incremental modification of files that 002 introduced. No reorganisation of `daemon/` or `telegram/`. The dispatcher gains a *single* new branch (termination command); the worker gains a *single* new signal handler path. No new daemon module is needed because the operator-stop dispatch is a thin adaptation of code that already exists.

## Phase 0: Outline & Research

(see `research.md`)

Key research items (all resolved before Phase 1):

1. **Signal selection — operator stop vs timeout**: 002 already uses SIGTERM for the timeout watchdog. Reusing SIGTERM for operator-stop would force the worker to disambiguate via a side-channel (env var, file). Decision: **use `SIGUSR1`** for operator-initiated stop. SIGUSR1 is unused by 002, has no default action other than terminate (we replace it), and clearly separates "intentional stop" from "ran out of time". 002's SIGTERM ladder still fires *after* the SIGUSR1 grace window if the worker ignores the cooperative signal — graceful → forced is the same code path.
2. **Worker stdout protocol extension**: 002's `_stream_subprocess_output` already parses one line shape (`PR_URL=…`). Decision: add two more line shapes — `PROGRESS i/N <iso8601>` and `FINAL <iteration> <reason>` — and a generic "stream this stdout line directly to the topic" pass-through for everything that doesn't match. This keeps a single IPC channel (stdout) and avoids new file descriptors / sockets.
3. **Topic-to-session resolution**: termination commands arrive as Telegram updates with `message_thread_id` = the topic id. The dispatcher has the connection and the cfg; we add `core.db.get_active_session_by_topic(conn, topic_id)` returning the latest non-terminal row for that topic_id, mirroring `get_active_session_for_issue`. No new index needed (sessions are few; `topic_id` already populated).
4. **Termination grammar and parser placement**: matches the 002 issue-key parser pattern. Pure module-level regex `^(done|stop|finish)$` (case-insensitive, after stripping). Lives in `telegram/parser.py` next to the issue-key extractor. Returns either `None` or a typed `TerminationCommand` with the canonical lowercase form.
5. **Dispatcher branching order**: when a text message arrives in the configured chat, we check (in this order) (a) whitelist, (b) is there a `message_thread_id`? if yes → run termination parser first; if termination match → handle. Otherwise fall through to the existing issue-key trigger path. This ordering means `done` typed in a topic is not accidentally interpreted as a (failed) issue key, and `done` typed in the main chat falls through and is ignored (no issue key match, no termination because no thread).
6. **Worker signal handler implementation**: Python's `signal.signal(signal.SIGUSR1, ...)` from the worker's main thread. The handler sets a `threading.Event`-like flag; the main loop checks the flag at the top of each iteration AND between sleeps using a short `signal.sigwait`/`time.sleep(small)` loop so a stop in the middle of a 30-second sleep wakes promptly.
7. **Grace window value**: `SIGUSR1` then 5 s grace then SIGTERM (002's existing watchdog). 5 s is plenty for a placeholder that just prints one line and exits; real agents will need a separate setting in a future feature.
8. **Audit event taxonomy additions**: `telegram_termination_received` (accepted, session-bound) and `telegram_termination_rejected` (unauthorised / wrong-topic / no-session, unbound — written to `audit.log`).
9. **Manual end-to-end recipe**: spec's quickstart needs to walk an operator through `done`, `stop`, `finish`, an unauthorised attempt, and a wrong-topic attempt, asserting expected behaviour each time.
10. **Test strategy**: unit covers parser + dispatcher branches; integration covers each acceptance scenario. The demo worker is invoked directly (it is the production module after all), so we don't need a separate `fake_agent` for these tests — we just pass `iterations=3, interval_seconds=0.05` via env vars.

## Phase 1: Design & Contracts

(see `data-model.md`, `contracts/`, `quickstart.md`)

1. **Data model** (`data-model.md`):
   - No schema delta. V0001 stays.
   - Refines `error_message` semantics: adds the values `operator_stop` and `operator_stop_forced` to the documented set (alongside 002's `daemon_restart` and `timeout`).
   - Documents the two new `session_events.type` values (`telegram_termination_received`, `telegram_termination_rejected`).
   - Documents the worker's stdout protocol (`PROGRESS`, `FINAL`, free-form passthrough).

2. **Contracts**:
   - `termination-protocol.md`: the inbound message grammar (lowercase token, in topic, by whitelist), the daemon's accept/reject decision tree, the audit-log shape for rejections, the `SIGUSR1`-then-grace-then-SIGTERM ladder.
   - `worker-stdout-protocol.md`: the three stdout line shapes, the daemon's parser behaviour, and the topic-bound message templates that result.

3. **Quickstart** (`quickstart.md`): manual operator flow on a real Telegram group — trigger, observe progress, send `done`, see final + stopped messages, verify DB row. Plus failure-case smoke (post `done` from a second account, post `done` in main chat).

4. **Agent context update**: switch the active feature pointer in `CLAUDE.md` to `specs/003-e2e-demo/plan.md`. 002 stays referenced as the foundational predecessor, just like 001 does for 002.

## Phase 2 (deferred to /speckit-tasks)

Task decomposition is produced by the next command. This plan stops here per template instructions.

## Complexity Tracking

> No violations. Section intentionally empty.
