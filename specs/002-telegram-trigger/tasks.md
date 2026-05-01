---
description: "Task list for 002-telegram-trigger"
---

# Tasks: Telegram Trigger

**Feature**: 002-telegram-trigger
**Branch**: `002-telegram-trigger`
**Input**: `specs/002-telegram-trigger/{plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md}`

**Tests**: Included. The plan explicitly enumerates new test artifacts (`tests/unit/test_telegram_parser.py`, `test_dispatcher.py`, `test_audit.py`; `tests/integration/test_listener_loop.py`, `test_worker_lifecycle.py`, `test_runtime_end_to_end.py`; `tests/fakes/fake_telegram.py`, `fake_agent.py`). New `pytest-asyncio` dependency is added explicitly to support these tests.

**Organization**: Tasks are grouped by user story (US1–US6, priorities P1/P1/P1/P2/P2/P3) so each story can be implemented and validated as an independent increment. The MVP is User Story 1 only.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Different file, no dependency on an incomplete task → may run in parallel
- **[Story]**: `US1`–`US6`, applied to user-story-phase tasks only

## Path Conventions

Single-project layout, paths relative to repo root:

- Source: `src/remotask/`
- Tests: `tests/{unit,integration,fakes}/`
- Specs: `specs/002-telegram-trigger/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: New runtime dependencies and package skeletons.

- [X] T001 Add new runtime deps `httpx>=0.27` and `claude-agent-sdk>=0.1` to `[project.dependencies]` in `pyproject.toml`; add `pytest-asyncio>=0.24` to `[dependency-groups].dev`. Run `uv sync` (or `pip install -e .[dev]`) and verify imports succeed.
- [X] T002 Add `asyncio_mode = "auto"` under `[tool.pytest.ini_options]` in `pyproject.toml` so async tests don't need per-test markers.
- [X] T003 [P] Create new package skeleton `src/remotask/telegram/__init__.py` (empty module-level docstring only).
- [X] T004 [P] Create new test fakes package skeleton `tests/fakes/__init__.py` (empty file).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Pure helpers and contracts that every user-story phase consumes. No story can begin until this phase is complete.

⚠️ **CRITICAL**: Phase 3+ depends on Phase 2.

- [X] T005 [P] Extend `TelegramConfig` in `src/remotask/core/config.py`: add optional `poll_timeout_seconds: int = 25` (≥1, ≤60) and `backoff_max_seconds: int = 60` (≥1, ≤600), plus a regex validator on `bot_token` (`^\d+:[A-Za-z0-9_-]{30,}$` when non-empty), per `contracts/config.schema.md`.
- [X] T006 [P] Extend `AgentConfig` in `src/remotask/core/config.py`: add `session_timeout_seconds: int = 1800` (≥60, ≤86400).
- [X] T007 [P] Add `Project.by_prefix(prefix: str) -> Project | None` to `src/remotask/core/projects.py` (lookup by `jira_key`, treats `enabled=0` as not registered) and a `list_registered_prefixes() -> list[str]` helper.
- [X] T008 [P] Add session-helpers to `src/remotask/core/db.py`: `get_active_session_for_issue(conn, issue_key) -> Row | None` (status IN `enqueued|starting|running`); `count_active_sessions(conn) -> int`; `iter_non_terminal_sessions(conn) -> Iterable[Row]` (used by daemon-restart recovery).
- [X] T009 [P] Implement issue-key parser in `src/remotask/telegram/parser.py`: `extract_first_issue_key(text: str) -> str | None` using `\b[A-Z][A-Z0-9_]{1,9}-\d{1,6}\b` (regex compiled at module level); pure function, no I/O.
- [X] T010 [P] Implement Telegram Bot API client in `src/remotask/telegram/client.py`: thin async wrapper around `httpx.AsyncClient` exposing `get_updates(offset, timeout, allowed_updates=["message"])`, `create_forum_topic(chat_id, name)`, `send_message(chat_id, text, message_thread_id=None)`. Honour HTTP 429 `retry_after`; respect 50ms outbound spacing.
- [X] T011 [P] Implement listener state-file IO at `src/remotask/daemon/listener_state.py`: dataclass `ListenerState(running, started_at, last_poll_ok_at, consecutive_failures, active_sessions, whitelist_size, degraded, last_update_id)`; `read()` from `~/.local/share/remotask/listener.state` (returns sentinel "missing/stale" markers); `write_atomic(state)` (write `.tmp` + rename, mode 0600); throttle helper "write at most once per second unless changed".
- [X] T012 [P] Implement listener command-file IO at `src/remotask/daemon/listener_cmd.py`: dataclass `ListenerCmd(seq, command)`; `write(seq, command)` to `~/.local/share/remotask/listener.cmd` (atomic, 0600); `read_and_clear()` for the daemon side; sequence-monotonicity helper.
- [X] T013 [P] Implement audit-event writer in `src/remotask/daemon/audit.py`: `record_event(conn, session_id, type, payload_dict)` inserts into `session_events` (when `session_id` is non-NULL); `log_unbound_event(type, payload_dict)` writes a structured `WARNING` line to the existing logger (because `session_events.session_id` is `NOT NULL` in V0001). Constants for the new event types from `data-model.md`.
- [X] T014 [P] Implement fake Telegram server in `tests/fakes/fake_telegram.py`: in-process `httpx.MockTransport`-based stand-in supporting `getUpdates` (queue of inbound updates the test pushes), `createForumTopic` (returns synthetic `message_thread_id`), `sendMessage` (records calls); fixture `fake_telegram` for use across integration tests.
- [X] T015 [P] Implement fake Claude Agent stand-in in `tests/fakes/fake_agent.py`: a tiny entry-point script (or `monkeypatch`-installed fake `claude_agent_sdk` module) that simulates configurable scenarios (success-with-PR, success-no-PR, exit-nonzero, hang-until-killed) controlled via env vars; importable helper to create the worker subprocess command pointing at this fake.
- [X] T016 [P] Unit tests for the parser in `tests/unit/test_telegram_parser.py`: matches valid keys, ignores casual text, picks first match when multiple, rejects malformed (`ZXTL-` no number, `ZXTL-abc`), respects word boundaries.
- [X] T017 [P] Unit tests for the audit writer in `tests/unit/test_audit.py`: session-bound events insert rows into `session_events`; unbound events emit structured `WARNING` log; payload JSON is serialised correctly; bot token never appears in payloads.

**Checkpoint**: Foundation ready — user-story implementation can begin.

---

## Phase 3: User Story 1 — Trigger a session from a Jira issue key (Priority: P1) 🎯 MVP

**Goal**: An authorized operator posts a Jira issue key in the configured group; a forum topic is created within ~5s, status updates stream into the topic, and a draft PR URL appears at the end.

**Independent Test**: Given one whitelisted user and one registered project for prefix `ZXTL`, post `ZXTL-1234` from that user; observe (a) forum topic created, (b) "session starting" message, (c) state-transition messages, (d) PR URL on completion. Database row exists with `status='pr_created'`, `topic_id` non-null, `pr_url` set.

### Tests for User Story 1

- [X] T018 [P] [US1] Unit tests for dispatcher accept path in `tests/unit/test_dispatcher.py`: whitelisted sender + valid prefix → session row inserted, lock acquired, topic create requested, worker spawn requested (collaborators mocked).
- [X] T019 [P] [US1] Integration test for listener loop in `tests/integration/test_listener_loop.py`: pushes a synthetic update through `fake_telegram`; asserts `getUpdates` offset advances, dispatcher is invoked once per message, parsed_key is forwarded.
- [X] T020 [P] [US1] Integration test for worker lifecycle in `tests/integration/test_worker_lifecycle.py`: spawns the `fake_agent` worker in success-with-PR mode; asserts state transitions `enqueued → starting → running → pr_created`, `worktree_path`, `branch`, `pr_url` set.
- [X] T021 [P] [US1] Integration end-to-end test in `tests/integration/test_runtime_end_to_end.py`: brings up the full runtime backed by `fake_telegram` + `fake_agent`; sends a valid trigger; asserts topic was created, status messages were posted to that topic, final PR URL message appeared, and the session row reached `pr_created`.

### Implementation for User Story 1

- [X] T022 [P] [US1] Implement Telegram topic helper in `src/remotask/daemon/topic.py`: `create_topic_for_session(client, chat_id, issue_key)` → `topic_id`; `post_to_topic(client, chat_id, topic_id, text)`; `post_to_main_chat(client, chat_id, text)`; uses outbound templates from `contracts/telegram-protocol.md`.
- [X] T023 [P] [US1] Implement worker subprocess wrapper in `src/remotask/daemon/worker.py` (accept-path only — failure/timeout branches deferred to US5): `spawn_worker(session_id, repo_path, issue_key, branch) -> Worker` using `asyncio.create_subprocess_exec` invoking the `claude-agent-sdk` driver entrypoint; `await worker.wait()` translates exit code 0 (with PR URL emitted by the agent) → `pr_created`, exit 0 (no PR) → `completed`. Worker output captured to `~/.local/share/remotask/logs/sessions/<id>.log`.
- [X] T024 [US1] Implement dispatcher accept path in `src/remotask/daemon/dispatcher.py`: `async def dispatch(message)` flow — whitelist OK + prefix resolved → BEGIN IMMEDIATE txn, insert `sessions` row (`status=enqueued`, `topic_id=NULL`, `trigger_user`, `trigger_text`, `trigger_message_id`), call `topic.create_topic_for_session`, store `topic_id`, transition to `starting`, post "Session starting…" template, transition to `running`, hand off to worker. Other branches (unknown prefix, unauthorised, etc.) raise `NotImplementedError` for now and are filled in by US2/US3/US6.
- [X] T025 [US1] Implement listener long-poll loop in `src/remotask/daemon/listener.py`: asyncio task wrapping `client.get_updates(offset, timeout=poll_timeout_seconds)`; persists `last_update_id` to `listener_state` after each batch; on success resets `consecutive_failures`; on transient failure applies exponential backoff (1s → 60s cap, jitter); dispatches each `message` update to `dispatcher.dispatch`. Plain happy-path version — degraded-marker / 10-fail behaviour is added in US5.
- [X] T026 [US1] Implement runtime orchestrator in `src/remotask/daemon/runtime.py`: `class Runtime` replaces `stub_runtime`. On `start()`: validate config preconditions (deferred completion in US3 task T034), open DB conn, launch dedicated thread with its own asyncio loop hosting the listener + outbound queue, install SIGTERM/SIGINT handlers on main thread to drain workers and stop the loop. Provides `mark_listener_running(bool)` toggled by SIGUSR1 handler (added in US4).
- [X] T027 [US1] Wire the new runtime into `src/remotask/daemon/__init__.py` and the daemon CLI entry (`src/remotask/commands/daemon.py`): import `runtime.Runtime` instead of `stub_runtime.run`. Keep `stub_runtime.py` on disk for rollback during US1; deletion is in the polish phase.
- [X] T028 [US1] Wire `state_transition` event recording into dispatcher + worker (touches `src/remotask/daemon/dispatcher.py` and `src/remotask/daemon/worker.py`): every status change inserts a `session_events` row of type `state_transition` and posts `Status: <new_status>` to the bound topic.

**Checkpoint**: US1 demoable — happy path works end-to-end with `fake_telegram` and `fake_agent` in the integration test.

---

## Phase 4: User Story 2 — Reject unknown project keys with helpful guidance (Priority: P1)

**Goal**: A trigger whose prefix is not in the registered projects table receives an in-channel reply naming the unknown prefix and listing the registered ones; non-trigger messages are ignored silently.

**Independent Test**: Send `BAR-7` from a whitelisted account when only `ZXTL` is registered → bot replies in main chat naming `BAR` and listing `ZXTL`; no topic, no session row. Send a casual message containing no issue-key → no reply, no audit row.

### Tests for User Story 2

- [X] T029 [P] [US2] Add cases to `tests/unit/test_dispatcher.py`: unknown-prefix branch posts the templated reply to main chat and emits `telegram_unknown_prefix` audit log; no `sessions` row inserted; casual non-trigger message is ignored without audit noise.

### Implementation for User Story 2

- [X] T030 [US2] Add unknown-prefix rejection branch to `src/remotask/daemon/dispatcher.py`: when `Project.by_prefix(prefix)` is `None` or disabled, call `topic.post_to_main_chat` with template from `contracts/telegram-protocol.md` ("Unknown project prefix '<P>'. Registered prefixes: <list>") and `audit.log_unbound_event("telegram_unknown_prefix", {...})`.
- [X] T031 [US2] Add silent-ignore branch to `src/remotask/daemon/dispatcher.py`: when `extract_first_issue_key` returns `None`, return early — no reply, no audit row (only the standard structured-log line at DEBUG level).

**Checkpoint**: US1 + US2 working — the operator can distinguish "unknown project" from "bot offline" via reply behaviour.

---

## Phase 5: User Story 3 — Reject unauthorized senders silently (Priority: P1)

**Goal**: Messages from non-whitelisted users produce no reply, no topic, no session — but the daemon's audit log records the rejection. Empty/missing whitelist fails closed.

**Independent Test**: From a Telegram user id not in `allowed_user_ids`, send a valid issue key → no Telegram response, no DB row, but `audit.log` contains a `telegram_unauthorized` entry naming the sender id and message id. Separately, with `allowed_user_ids=[]`, the listener refuses to start.

### Tests for User Story 3

- [X] T032 [P] [US3] Add cases to `tests/unit/test_dispatcher.py`: non-whitelisted sender → no `sendMessage` call, no `sessions` insert, exactly one `telegram_unauthorized` log entry with sender_id, message_id, chat_id.
- [X] T033 [P] [US3] Add `tests/unit/test_runtime_preconditions.py`: empty whitelist → `Runtime.validate_listener_preconditions()` raises with a precise field name; bad bot token regex → raises; missing group_chat_id → raises; config file mode 0644 → raises; never logs the bot token value.

### Implementation for User Story 3

- [X] T034 [US3] Add whitelist gate to `src/remotask/daemon/dispatcher.py`: first action in `dispatch` is an early-return when `sender_id not in cfg.telegram.allowed_user_ids`, calling `audit.log_unbound_event("telegram_unauthorized", ...)`. No reply, no topic, no session insert.
- [X] T035 [US3] Add `Runtime.validate_listener_preconditions()` in `src/remotask/daemon/runtime.py`: enforces non-empty `bot_token` matching the regex, non-zero `group_chat_id`, non-empty `allowed_user_ids`, and config-file mode `0600`. Called before the listener starts polling. CLI exit code 5 surfaces the precise field name.

**Checkpoint**: All three P1 stories complete — happy path, helpful rejection, and silent-with-audit unauthorised flow are working. This is the **first releasable cut**.

---

## Phase 6: User Story 4 — Control the listener via CLI subcommands (Priority: P2)

**Goal**: `remotask telegram start|stop|status` give the operator parity with the existing daemon control surface.

**Independent Test**: With the daemon running and the listener stopped, run each subcommand. `start` flips `listener.state.running` to true within the timeout; `stop` flips it to false without cancelling in-flight workers; `status` reports running/stopped, last poll, active sessions, whitelist size; `--json` emits the raw state file.

### Tests for User Story 4

- [X] T036 [P] [US4] Integration test in `tests/integration/test_cli_telegram.py`: spawns daemon, runs `remotask telegram start/stop/status` via subprocess; asserts exit codes (0/3/4/5 per `contracts/cli-commands.md`), stdout shape, and `listener.state.running` transitions.

### Implementation for User Story 4

- [X] T037 [P] [US4] Implement `src/remotask/commands/telegram.py` with `start`, `stop`, `status` subcommands per `contracts/cli-commands.md`: writes `listener.cmd` (monotonic seq), reads PID from `~/.local/share/remotask/remotask.pid`, sends SIGUSR1, polls `listener.state` with 5s timeout; `status` formats human table or `--json` raw passthrough; exit codes 0/3/4/5 implemented exactly as specified.
- [X] T038 [US4] Register the telegram subcommand group in `src/remotask/cli.py` (`app.add_typer(telegram_app, name="telegram")`).
- [X] T039 [US4] Add SIGUSR1 handler to `src/remotask/daemon/runtime.py`: on signal, read+clear `listener.cmd`, ignore if `seq <= last_applied`, then start/stop the listener task accordingly. Stop is graceful: it sets a "no new triggers" flag but lets in-flight workers run to completion.
- [X] T040 [US4] Implement listener heartbeat writer in `src/remotask/daemon/runtime.py`: a periodic task in the listener loop calls `listener_state.write_atomic` after every poll (rate-limited to once/second) so `status` always sees fresh data; also written on every state change (start/stop/degraded/active-session-count).

**Checkpoint**: Operator can manage the listener via CLI exactly like the daemon itself.

---

## Phase 7: User Story 5 — Surface worker failures in the originating topic (Priority: P2)

**Goal**: Failed workers (crash, exit non-zero, timeout) post a clear failure message to their topic and the session row reflects the failure with a reason. Daemon restarts mid-session leave no "running forever" rows.

**Independent Test**: Force a worker to fail (project pointing at a non-existent path) → topic receives "Session failed: …", session row `status='failed'` with reason. Hang the worker beyond `session_timeout_seconds` → topic receives timeout message; row `status='failed'`, reason `timeout`. Kill the daemon mid-session → on restart, the abandoned session is `failed` with reason `daemon_restart` and the topic receives a notice.

### Tests for User Story 5

- [X] T041 [P] [US5] Add failure-path cases to `tests/integration/test_worker_lifecycle.py`: `fake_agent` exit-nonzero path → session `failed` with captured stderr first line, topic gets templated failure message, `worker_exit` event recorded.
- [X] T042 [P] [US5] Add `tests/integration/test_worker_timeout.py`: `fake_agent` in hang-until-killed mode + `agent.session_timeout_seconds=2` → after ~2s SIGTERM is sent, after grace period SIGKILL; session `failed` with reason `timeout`; topic receives timeout template; `worker_timeout` event recorded.
- [X] T043 [P] [US5] Add `tests/integration/test_restart_recovery.py`: pre-seed DB with sessions in `enqueued`/`starting`/`running` states (with `topic_id` set on some); start `Runtime`; assert all three rows transition to `failed` with reason `daemon_restart`; assert one "Session terminated by daemon restart." sendMessage call per row that had a `topic_id`; assert recovery is non-blocking when the topic post fails.

### Implementation for User Story 5

- [X] T044 [US5] Extend `src/remotask/daemon/worker.py` with failure surfacing: any non-zero exit or unhandled exception → transition session to `failed` with `error_message` set to a one-line reason (last stderr line / exception class+msg); post `Session failed: <reason>` to the topic; record `worker_exit` event.
- [X] T045 [US5] Add per-session timeout watchdog to `src/remotask/daemon/worker.py`: `asyncio.wait_for(worker.wait(), timeout=cfg.agent.session_timeout_seconds)`; on timeout, `os.killpg(pid, SIGTERM)`, await up to 10s, then `os.killpg(pid, SIGKILL)`; mark session `failed` reason `timeout`; post timeout template; record `worker_timeout` event.
- [X] T046 [US5] Add daemon-restart recovery to `Runtime.start()` in `src/remotask/daemon/runtime.py`: at startup, iterate `iter_non_terminal_sessions(conn)`; for each row, set `status='failed'`, `ended_at=now()`, `error_message='daemon_restart'`; insert `daemon_restart` event; if `topic_id` is set, best-effort post the restart-cleanup template (failure to post must not block startup).
- [X] T047 [US5] Add listener-degraded marker to `src/remotask/daemon/listener.py`: ≥10 consecutive `getUpdates` failures sets `listener.state.degraded=true` and emits a `WARNING` log throttled to once/5min; clears on next successful poll.

**Checkpoint**: All P1+P2 stories complete. The system is production-grade for solo use.

---

## Phase 8: User Story 6 — Run multiple sessions concurrently in isolated topics (Priority: P3)

**Goal**: Two issue keys triggered in quick succession run as two independent sessions in two topics on two worktrees. Same-issue retrigger is rejected with a clear pointer to the existing topic.

**Independent Test**: Trigger `ZXTL-1234` and `ZXTL-1235` within seconds (both authorised, both registered) → two topics, two sessions, two worktrees on two branches; both reach a terminal state without one corrupting the other. Then trigger `ZXTL-1234` again while the first is still running → reply in main chat names the existing topic; only one topic for that issue ever exists.

### Tests for User Story 6

- [X] T048 [P] [US6] Add `tests/integration/test_concurrency.py`: two parallel triggers complete independently (assert distinct `topic_id`, distinct `worktree_path`, distinct `branch`, both reach terminal); same-issue retrigger while first is `running` → second is rejected with `telegram_already_in_flight` audit and main-chat reply; `max_concurrent=1` cap → second concurrent issue is rejected with cap reply.

### Implementation for User Story 6

- [X] T049 [US6] Add same-issue rejection branch to `src/remotask/daemon/dispatcher.py`: before insert, query `get_active_session_for_issue(conn, issue_key)`; if a row exists, send the "already in flight" template to main chat, record `telegram_already_in_flight` event, return.
- [X] T050 [US6] Add per-issue advisory lock acquisition to dispatcher accept path: insert into `locks` table with `resource='issue:<KEY>'`, `holder_session=<session_id>` inside the same `BEGIN IMMEDIATE` transaction as the session insert; release in the transition-to-terminal helper.
- [X] T051 [US6] Add `max_concurrent` cap enforcement to dispatcher: `count_active_sessions(conn) >= cfg.agent.max_concurrent` → send cap-reached template to main chat and return without inserting a session.

**Checkpoint**: Concurrency story complete. Spec-level success criteria SC-003 reachable.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [X] T052 [P] Delete `src/remotask/daemon/stub_runtime.py` and remove all imports/references from the codebase. Verify with `grep -rn stub_runtime src tests` — must return nothing.
- [X] T053 [P] Verify `CLAUDE.md` active-feature pointer is `specs/002-telegram-trigger/plan.md` (already set; this task is a re-confirmation after polish).
- [X] T054 [P] Audit secret redaction end-to-end: `remotask config get telegram.bot_token` shows `***redacted***`; `listener.state` contents never include the bot token; structured logs (DEBUG and above) never include the bot token. Add a regression test in `tests/unit/test_secrets.py` if none covers this.
- [X] T055 [P] Help-text quality pass on `remotask telegram --help`, `start --help`, `stop --help`, `status --help` per the `contracts/cli-commands.md` "Help-text quality bar" section (one-line summary, example, mention `telegram.bot_token` / `telegram.allowed_user_ids`).
- [X] T056 [P] Listener-state staleness annotation: when `status` reads a state file older than 30s, append `(stale)` to the displayed `last poll` line per the CLI contract.
- [X] T057 Run quickstart.md end-to-end on a real Telegram group: Steps 1–7. Capture the resulting session row + audit log lines as evidence. Update quickstart with any troubleshooting addenda found.
- [X] T058 [P] Verify `tests/integration/test_concurrency_stress.py` (existing) still passes against the new runtime.
- [X] T059 Coverage sweep: confirm `pytest --cov=src/remotask` covers ≥85% of new modules (`telegram/*`, `daemon/{listener,dispatcher,worker,runtime,topic,audit,listener_state,listener_cmd}.py`).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no deps — start immediately.
- **Foundational (Phase 2)**: depends on Setup. **BLOCKS all user stories.**
- **US1 (Phase 3)**: depends on Foundational. P1, MVP.
- **US2 (Phase 4)**: depends on Foundational; touches `dispatcher.py` so cannot run in parallel with US1's T024 — start after US1's dispatcher accept path lands.
- **US3 (Phase 5)**: depends on Foundational; same `dispatcher.py` constraint as US2.
- **US4 (Phase 6)**: depends on Foundational + US1's runtime (T026); CLI front-end is otherwise independent.
- **US5 (Phase 7)**: depends on US1's worker (T023) and runtime (T026); failure paths build on accept-path scaffolding.
- **US6 (Phase 8)**: depends on US1's dispatcher (T024); concurrency check sits in front of the accept path.
- **Polish (Phase 9)**: after all desired user stories.

### Within Each User Story

- Tests in this plan are written alongside or just after the implementation they cover (the plan does not mandate strict TDD). Where TDD is desired, run the test task first and confirm failure before the matching implementation task.
- Within US1: T022 + T023 in parallel → T024 (dispatcher) → T025 (listener) → T026 (runtime) → T027 (wiring) → T028 (state-transition events).

### Parallel Opportunities

- All Phase 1 [P] tasks (T003, T004) are independent of T001/T002.
- All Phase 2 [P] tasks (T005–T017) hit different files and have no inter-dependencies; they can run in parallel as soon as Phase 1 is done.
- Within US1: T022 (topic helper) and T023 (worker) are in different files — parallel. Tests T018/T019/T020/T021 are in different files from each other — parallel.
- US4's CLI front-end (T037) and US4's daemon-side handlers (T039, T040) touch different files — parallel after T036 lands.
- US5's three integration tests (T041, T042, T043) are in different files — parallel.
- Polish tasks T052–T056, T058 are all in different files — parallel.

---

## Parallel Example: Phase 2 (Foundational)

```bash
# All Phase 2 [P] tasks can be developed concurrently after Phase 1:
Task T005: Extend TelegramConfig in src/remotask/core/config.py
Task T006: Extend AgentConfig in src/remotask/core/config.py    # same file as T005 — actually NOT [P] with T005; sequence them
Task T007: Add Project.by_prefix in src/remotask/core/projects.py
Task T008: Add session helpers in src/remotask/core/db.py
Task T009: Implement parser in src/remotask/telegram/parser.py
Task T010: Implement client in src/remotask/telegram/client.py
Task T011: Implement listener_state.py
Task T012: Implement listener_cmd.py
Task T013: Implement audit.py
Task T014: Implement fake_telegram.py
Task T015: Implement fake_agent.py
Task T016: Unit tests for parser
Task T017: Unit tests for audit
```

> Note: T005 and T006 both edit `src/remotask/core/config.py` — sequence them rather than running in parallel, despite the `[P]` markers. The marker indicates "no logical dependency"; same-file edits should still be serialised to avoid merge conflicts.

## Parallel Example: User Story 1

```bash
# Tests can be drafted in parallel against the contracts:
Task T018: Unit tests for dispatcher accept in tests/unit/test_dispatcher.py
Task T019: Integration test for listener loop in tests/integration/test_listener_loop.py
Task T020: Integration test for worker lifecycle in tests/integration/test_worker_lifecycle.py
Task T021: Integration end-to-end in tests/integration/test_runtime_end_to_end.py

# Implementation files that can be drafted in parallel:
Task T022: daemon/topic.py
Task T023: daemon/worker.py
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 (Setup) → Phase 2 (Foundational) → Phase 3 (US1).
2. **STOP and VALIDATE**: run quickstart.md Step 3 on a real Telegram group with one whitelisted user and one project.
3. Demo the working trigger.

### Incremental Delivery

1. MVP (US1) — happy path demoable.
2. Add US2 + US3 (P1 rejection paths) — first releasable cut. Operator can safely run in a real group.
3. Add US4 (CLI parity) — feature operationally complete.
4. Add US5 (failure surfacing) — production-grade reliability.
5. Add US6 (concurrency) — quality-of-life upgrade.

### Solo-Developer Strategy (this project)

This project is single-operator, so "parallel teams" is not meaningful; prefer sequential progression P1 → P2 → P3 with the [P] markers used to safely interleave file edits within a single working session (e.g., draft `topic.py` and `worker.py` in the same hour, since they are independent files).

---

## Notes

- `[P]` = different file, no logical dependency on incomplete work — but same-file [P] tasks should still be sequenced to avoid conflicts.
- Each user story is independently testable: US1 via the end-to-end integration test, US2/US3 via dispatcher unit tests, US4 via the CLI integration test, US5 via failure-path integration tests, US6 via the concurrency integration test.
- Every task names the exact file path it touches.
- No new database migration is introduced — V0001 already has every column needed (per `data-model.md` and research R6). If the implementer discovers a missing column, add a V0002 migration as a separate, focused task before the affected user-story phase.
- All outbound Telegram message templates are taken verbatim from `contracts/telegram-protocol.md`; do not invent new wording.

---

## Format Validation

Every task above:

- Begins with `- [ ] T###`
- Includes either no story label (Setup / Foundational / Polish) or exactly one of `[US1]`–`[US6]`
- Names a concrete file path
- Has `[P]` only when the task does not share a file with another incomplete task in the same phase
