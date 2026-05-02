---
description: "Task list for 003-e2e-demo"
---

# Tasks: End-to-End Demo Workflow

**Feature**: 003-e2e-demo
**Branch**: `003-e2e-demo`
**Input**: `specs/003-e2e-demo/{plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md}`

**Tests**: Included. The plan explicitly enumerates new test files (`tests/unit/test_demo_worker.py`, plus four new integration tests under `tests/integration/`). 002's `tests/unit/test_telegram_parser.py` and `tests/unit/test_dispatcher.py` get new cases rather than new files.

**Organization**: Tasks are grouped by user story (US1 P1, US2 P1, US3 P2). US1 and US2 are both P1 but US2 builds on US1's worker; US3 is P2 polish on top of both. The MVP cut is US1 + US2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Different file, no dependency on an incomplete task → may run in parallel
- **[Story]**: `US1`–`US3`, applied to user-story-phase tasks only

## Path Conventions

Single-project layout, paths relative to repo root:

- Source: `src/remotask/`
- Tests: `tests/{unit,integration,fakes}/`
- Specs: `specs/003-e2e-demo/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: New package skeleton + config field that every user-story phase will consume.

- [X] T001 [P] Create new package skeleton `src/remotask/agent/__init__.py` (one-line module docstring; this is where the production worker entry lives).
- [X] T002 [P] Add `operator_stop_grace_seconds: int = 5` (range 1..30) to `AgentConfig` in `src/remotask/core/config.py`. Pydantic validator inline with the existing `session_timeout_seconds` field.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Pure helpers and contracts that every user-story phase consumes. No story can begin until this phase is complete.

⚠️ **CRITICAL**: Phase 3+ depends on Phase 2.

- [X] T003 [P] Add `get_active_session_by_topic(conn, topic_id) -> sqlite3.Row | None` to `src/remotask/core/db.py`. Mirrors `get_active_session_for_issue`; selects from `sessions` where `topic_id = ?` and `status IN NON_TERMINAL_STATES`, returns most recent.
- [X] T004 [P] Add new audit event constants to `src/remotask/daemon/audit.py`: `EV_TELEGRAM_TERMINATION_RECEIVED`, `EV_TELEGRAM_TERMINATION_REJECTED`. Place next to the existing 002 constants block.
- [X] T005 [P] Add new outbound message templates to `src/remotask/daemon/topic.py`: `TPL_OPERATOR_STOPPED`, `TPL_OPERATOR_STOPPED_FORCED`, `TPL_PROGRESS`, `TPL_FINAL` (verbatim from `contracts/termination-protocol.md` and `contracts/worker-stdout-protocol.md`).
- [X] T006 [P] Add a `_DEMO_PROGRESS_RE` and `_DEMO_FINAL_RE` to `src/remotask/daemon/worker.py` (next to the existing `_PR_URL_RE`); regex patterns from `contracts/worker-stdout-protocol.md`. Helpers stay private to the module.

**Checkpoint**: Foundation ready — user-story implementation can begin.

---

## Phase 3: User Story 1 — Background worker actually runs and reports progress (Priority: P1) 🎯 MVP slice 1

**Goal**: Replace 002's `NotImplementedError` worker entry with a real placeholder subprocess that runs N iterations × T seconds and streams progress messages to its bound topic. End-to-end natural completion: trigger → topic created → progress lines → `Status: completed`.

**Independent Test**: With one whitelisted operator and one registered project, send a valid issue key from Telegram. With env vars `REMOTASK_DEMO_ITERATIONS=3, REMOTASK_DEMO_INTERVAL_SECONDS=0.5` (test-mode), confirm: (a) topic created, (b) `Session starting` + `Status: running` messages, (c) three `Status: iteration i/3 @ <ts>` lines, (d) one `Status: final iteration 3 (natural)` line, (e) session row reaches `status=completed`.

### Implementation for User Story 1

- [X] T007 [US1] Implement the placeholder worker in `src/remotask/agent/demo_worker.py`: read `REMOTASK_DEMO_ITERATIONS` (default 5) and `REMOTASK_DEMO_INTERVAL_SECONDS` (default 30.0) from `os.environ`; install a `SIGUSR1` handler that sets a module-level "stop_requested" flag (no I/O in handler — signal-safety); main loop emits `PROGRESS i/N <iso8601_utc>` to stdout at the start of each iteration, sleeps in ≤0.5s slices to stay responsive to the flag, emits `FINAL <iteration> operator_stop` and exits 0 if the flag is observed, else emits `FINAL <N> natural` after the loop completes and exits 0. Single-file module, importable AND runnable as `python -m remotask.agent.demo_worker`.
- [X] T008 [US1] Replace `_default_worker_argv()` in `src/remotask/daemon/worker.py` to return `[sys.executable, "-m", "remotask.agent.demo_worker"]` instead of raising `NotImplementedError`. Production code path now reaches a real, deterministic subprocess.
- [X] T009 [US1] Extend `_stream_subprocess_output` in `src/remotask/daemon/worker.py` to recognise `PROGRESS` and `FINAL` lines (using the regexes from T006) and post the templated topic messages (from T005) immediately as each line arrives. Lines that match neither `PR_URL=`, `PROGRESS`, nor `FINAL` continue to log-only.
- [X] T010 [US1] When the worker exits with code 0, use the most recent `FINAL` line (if any) to choose the terminal transition: `FINAL <N> natural` (or no FINAL) → `running → completed`; `FINAL <i> operator_stop` → handled by US2's path (skip here, the in-flight flag will be present). Update `run_worker` in `src/remotask/daemon/worker.py` to thread this decision.

### Tests for User Story 1

- [X] T011 [P] [US1] Unit tests for the demo worker in `tests/unit/test_demo_worker.py`: env-var overrides honoured, default values applied when env unset, `iso8601_utc()` helper produces the right shape, `SIGUSR1` handler sets the flag (use `os.kill(os.getpid(), signal.SIGUSR1)` with the handler installed; verify the flag flips). Run the worker as a fast subprocess with `iterations=2, interval=0.05` and verify stdout shape.
- [X] T012 [P] [US1] Integration test in `tests/integration/test_demo_natural_completion.py`: exercise the full pipeline (dispatcher → worker → topic post) with `fake_telegram` and the **real** demo_worker subprocess; env vars `REMOTASK_DEMO_ITERATIONS=3, REMOTASK_DEMO_INTERVAL_SECONDS=0.05`. Assert: topic created, ≥3 `Status: iteration` posts visible, `Status: final iteration 3 (natural)` post visible, session row reaches `status=completed`.

**Checkpoint**: Demo worker actually runs end-to-end. Operator can trigger from Telegram and watch progress. Stop is **not yet** implemented — US2 next.

---

## Phase 4: User Story 2 — Operator can stop a running session from Telegram (Priority: P1) 🎯 MVP slice 2

**Goal**: Whitelisted operator posts `done` (or `stop` / `finish`) inside a session-bound topic; daemon resolves the topic to its session, sends `SIGUSR1` to the worker, the worker's pre-installed handler (from T007) flushes a final-status line and exits, daemon transitions the session to `canceled` with `error_message='operator_stop'`. Audit captures both the accepted command and any rejected attempts.

**Independent Test**: Trigger a session with shortened iterations (`REMOTASK_DEMO_INTERVAL_SECONDS=2`), wait until `Status: iteration 2/5` has been posted, then post `done` in the bound topic. Confirm within 10s: `Status: final iteration 2 (operator_stop)` appears, `Session stopped by operator.` appears, session row is `status=canceled, error_message=operator_stop`. Confirm `done` from a non-whitelisted account is silently ignored (audit-logged with `reason=unauthorized`). Confirm `done` in the main chat is silently ignored. Confirm `done` in a stale topic (no active session) is silently ignored (audit-logged with `reason=no_active_session`).

### Implementation for User Story 2

- [X] T013 [P] [US2] Add `match_termination_command(text: str) -> str | None` to `src/remotask/telegram/parser.py`. Pure regex `^(done|stop|finish)$` (case-insensitive, applied to `text.strip()`); returns the lowercase canonical token or `None`. Module-level compiled regex.
- [X] T014 [US2] Add the **termination branch** to `src/remotask/daemon/dispatcher.py`. Place it AFTER the whitelist gate and AFTER checking that `message.message_thread_id` is non-null, but BEFORE the issue-key extraction. Branch logic per `contracts/termination-protocol.md` §"Decision tree": match grammar → resolve session via `core.db.get_active_session_by_topic` → on accept: insert `EV_TELEGRAM_TERMINATION_RECEIVED` event row, set runtime's `operator_stop_in_flight` flag for this session, send `SIGUSR1` to the worker pid, post nothing yet (the worker's `FINAL` line drives the topic post). On reject: emit `EV_TELEGRAM_TERMINATION_REJECTED` audit entry with `reason ∈ {unauthorized, wrong_topic, no_active_session}` and the payload from the contract.
- [X] T015 [US2] Track operator-stop in flight on the runtime side. Add a small `set[str]` of session ids on `Runtime` that is mutated under the listener thread; the worker post-exit logic checks this set to choose between `operator_stop` (in-set) vs `timeout` (002 path) for the `error_message`. `src/remotask/daemon/runtime.py`. Expose a thread-safe-enough API (`mark_operator_stop_in_flight(session_id)`, `pop_operator_stop_in_flight(session_id) -> bool`) since both the dispatcher and the worker exit-handler run on the same listener loop.
- [X] T016 [US2] In `src/remotask/daemon/worker.py:run_worker`, when the worker exits 0 AND `operator_stop_in_flight` is set for this session, transition `running → canceled` with `extra_columns={"error_message": "operator_stop"}` and post `Session stopped by operator.` to the topic. The already-emitted `Status: final iteration <i> (operator_stop)` line (from US1's T009) accompanies this.

### Tests for User Story 2

- [X] T017 [P] [US2] Unit tests for the termination grammar in `tests/unit/test_telegram_parser.py` (extend the existing file): accepts `done`, `Done`, `STOP`, `finish ` (trailing space), rejects `done please`, `cancel`, empty string, `Stop?`.
- [X] T018 [P] [US2] Unit tests for the dispatcher termination branch in `tests/unit/test_dispatcher.py` (extend the existing file). Four cases: (a) whitelisted + topic + valid grammar + active session → `EV_TELEGRAM_TERMINATION_RECEIVED` row inserted, SIGUSR1 sent (mocked), in-flight flag set; (b) non-whitelisted → audit-only `unauthorized`, no signal; (c) whitelisted + topic + grammar + no active session → audit-only `no_active_session`; (d) whitelisted + main chat + grammar → falls through, treated as casual chat (no audit, no signal).
- [X] T019 [P] [US2] Integration test in `tests/integration/test_operator_stop.py`: trigger a session with the real demo_worker (interval 0.5s), inject a `done` message via `fake_telegram` after the first progress line is posted, assert the worker exits, the topic shows `Status: final iteration <i> (operator_stop)` and `Session stopped by operator.`, and the session row is `status=canceled, error_message=operator_stop`. Bound by a 10-second outer timeout.
- [X] T020 [P] [US2] Integration test in `tests/integration/test_termination_rejection.py`: cover the three rejection paths (unauthorized sender, no active session, main-chat termination). For each, assert no Telegram reply, no signal sent (worker continues if running), and an `audit.log` entry with the right `reason`.

**Checkpoint**: P1 stories complete — operator can trigger, observe, and stop sessions using only Telegram. This is the **first releasable cut** of the e2e demo feature.

---

## Phase 5: User Story 3 — Worker flushes a final status before exiting on stop signal (Priority: P2)

**Goal**: Polish on US2's stop. The `FINAL <i> operator_stop` line is already emitted by the worker thanks to T007's signal handler, and the daemon already posts it as a topic message thanks to T009. This phase **adds the forced-kill escalation path** and verifies it: if the worker ignores SIGUSR1 (by misconfiguration or bug), the 002 SIGTERM/SIGKILL ladder fires after the configured grace window and the session lands on `canceled` with `error_message='operator_stop_forced'`.

**Independent Test**: Spawn a worker that *ignores* SIGUSR1 (test-only worker variant or a monkey-patched demo_worker), trigger and let it run, post `done`, observe: after `agent.operator_stop_grace_seconds` (set to 1s in test) elapses, daemon escalates to SIGTERM (then SIGKILL after 002's 10s grace), topic receives `Session force-stopped by operator (grace window exceeded).`, session row is `status=canceled, error_message=operator_stop_forced`.

### Implementation for User Story 3

- [X] T021 [US3] Add the operator-stop grace watchdog to the dispatcher's termination accept path in `src/remotask/daemon/dispatcher.py`: after sending `SIGUSR1`, schedule an asyncio task that waits `cfg.agent.operator_stop_grace_seconds`; if the worker is still alive when the timer fires, invoke the existing 002 `_kill_worker_group` ladder (SIGTERM → 10s grace → SIGKILL). On forced kill, set `error_message='operator_stop_forced'` and post `TPL_OPERATOR_STOPPED_FORCED` to the topic.
- [X] T022 [US3] In `src/remotask/daemon/worker.py:run_worker`, refine the exit-handling so that when the worker is killed by SIGTERM/SIGKILL **AND** `operator_stop_in_flight` is set, the transition uses `error_message='operator_stop_forced'` (instead of the 002 `timeout` path). 002's `timeout` branch retains its own `_kill_worker_group` for the timeout case; we are adding a parallel branch for operator-stop escalation.

### Tests for User Story 3

- [X] T023 [P] [US3] Integration test in `tests/integration/test_operator_stop_forced.py`: spawn a worker variant that explicitly ignores SIGUSR1 (e.g. a test-only flag in `demo_worker.py` like `REMOTASK_DEMO_IGNORE_SIGUSR1=1`, or a small `tests/fakes/stuck_worker.py` script that masks SIGUSR1 via `signal.signal(signal.SIGUSR1, signal.SIG_IGN)` then loops). With `agent.operator_stop_grace_seconds=1`, post `done`, assert: `Session force-stopped by operator (grace window exceeded).` topic message, `status=canceled, error_message=operator_stop_forced`, worker actually exited (no PID).

**Checkpoint**: All three user stories complete. The escalation path is exercised under test, even though the stock demo_worker honors SIGUSR1 cleanly.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T024 [P] Verify backward compatibility with 002's existing tests: run `uv run pytest tests/integration/test_worker_lifecycle.py tests/integration/test_runtime_end_to_end.py` and confirm they still pass — the `PR_URL=` line shape and 002's `fake_agent` fixtures must be unaffected.
- [X] T025 [P] Lint + mypy + full test sweep: `uv run ruff check src/remotask tests`, `uv run mypy src/remotask/core`, `uv run pytest -q`. Fix issues if any.
- [X] T026 [P] Update `specs/003-e2e-demo/checklists/requirements.md` with a final pass-mark across all checklist items if any spec adjustments were needed during implementation.
- [X] T027 Run `quickstart.md` end-to-end on a real Telegram group: Steps 1–7. Capture the resulting session rows + audit log entries as evidence. Update quickstart with any troubleshooting addenda discovered.
- [X] T028 [P] Verify `CLAUDE.md` active feature pointer remains correct (`specs/003-e2e-demo/plan.md`).
- [X] T029 [P] Check coverage on new modules (`agent/demo_worker.py` and the modified dispatcher / worker branches) is ≥ 85% via `uv run pytest --cov=src/remotask`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no deps — start immediately.
- **Foundational (Phase 2)**: depends on Setup. **BLOCKS all user stories.**
- **US1 (Phase 3)**: depends on Foundational. P1, MVP slice 1.
- **US2 (Phase 4)**: depends on Foundational + US1's worker (`demo_worker.py` must exist with its SIGUSR1 handler so the dispatcher can rely on the cooperative path). Without US1's worker, the SIGUSR1 has no recipient that knows what to do.
- **US3 (Phase 5)**: depends on US2 (the forced path is an escalation of the graceful path).
- **Polish (Phase 6)**: after all desired user stories.

### Within Each User Story

- Implementation tasks can interleave in any order that respects same-file ordering (sequential same-file edits, parallel different-file edits).
- Tests can be written alongside or just after the implementation they cover.

### Parallel Opportunities

- All Phase 1 tasks (T001, T002) — different files, no interdependencies.
- All Phase 2 tasks (T003–T006) — different files, no interdependencies.
- Within US1: T011 + T012 are independent test files and can be drafted in parallel after T007–T010 land.
- Within US2: T013 (parser) and the four implementation tasks T014–T016 touch different files — T013 is parallelizable. Tests T017–T020 are all in different files → all parallelizable.
- Within US3: T023 is an independent integration test file → parallelizable with the implementation tasks.
- Polish: T024–T029 are mostly independent operations — most can run in parallel.

---

## Parallel Example: Phase 2 (Foundational)

```bash
# All Phase 2 [P] tasks operate on different files:
Task T003: src/remotask/core/db.py (new helper)
Task T004: src/remotask/daemon/audit.py (new constants)
Task T005: src/remotask/daemon/topic.py (new templates)
Task T006: src/remotask/daemon/worker.py (new regex patterns; same file as T009 in US1, but T006 is just patterns; T009 extends the streamer below them)
```

> Note: T006 and T009 both edit `src/remotask/daemon/worker.py`; T006 lands first (Phase 2), T009 lands later in US1. Since T006 is a small additive change at the top of the module, the conflict surface is tiny.

## Parallel Example: User Story 2

```bash
# Tests can be written in parallel:
Task T017: tests/unit/test_telegram_parser.py (new cases)
Task T018: tests/unit/test_dispatcher.py (new cases)
Task T019: tests/integration/test_operator_stop.py
Task T020: tests/integration/test_termination_rejection.py

# Within implementation:
Task T013: src/remotask/telegram/parser.py (new function)  # parallel with the rest
Task T014: src/remotask/daemon/dispatcher.py (new branch)
Task T015: src/remotask/daemon/runtime.py (operator_stop_in_flight set)
Task T016: src/remotask/daemon/worker.py (terminal transition for operator stop)
```

---

## Implementation Strategy

### MVP Slice 1 (US1 only)

1. Phase 1 (Setup) → Phase 2 (Foundational) → Phase 3 (US1).
2. **STOP and VALIDATE**: run `quickstart.md` Step 2 (happy path only) on a real Telegram group.
3. The trigger now actually does something visible. This alone is a meaningful incremental delivery over 002 (which left workers as `NotImplementedError`).

### MVP Slice 2 (US1 + US2)

1. Continue with Phase 4 (US2).
2. **STOP and VALIDATE**: run `quickstart.md` Steps 3, 5, 6, 7 (operator stop + rejection cases) on the real group.
3. This is the **first releasable cut of 003** — operator can now control sessions end-to-end from Telegram.

### Full delivery

1. Continue with Phase 5 (US3 forced kill).
2. Run Phase 6 polish.
3. Demo loop is now production-grade.

### Solo-Developer Strategy

This project is single-operator, so "parallel teams" is not meaningful. Use [P] markers to interleave file edits within a single working session (e.g., draft `parser.py` and `topic.py` in the same hour, since they are independent files). Sequence same-file edits.

---

## Notes

- `[P]` = different file, no logical dependency on incomplete work. Same-file [P] tasks must still be sequenced.
- Each user story is independently testable: US1 via `test_demo_natural_completion.py`, US2 via `test_operator_stop.py` + `test_termination_rejection.py`, US3 via `test_operator_stop_forced.py`.
- Every task names exact file paths.
- No new database migration; V0001 already covers every column needed (per `data-model.md`).
- All outbound Telegram message templates come verbatim from `contracts/termination-protocol.md` and `contracts/worker-stdout-protocol.md`.
- Worker stdout protocol is line-oriented; the daemon's parser is whitelist-only (only `PR_URL=`, `PROGRESS`, `FINAL` lines reach Telegram; everything else goes to log file only).

---

## Format Validation

Every task above:

- Begins with `- [ ] T###`
- Includes either no story label (Setup / Foundational / Polish) or exactly one of `[US1]`–`[US3]`
- Names a concrete file path
- Has `[P]` only when the task does not share a file with another incomplete task in the same phase
