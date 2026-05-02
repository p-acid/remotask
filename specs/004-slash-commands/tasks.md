---
description: "Task list for 004-slash-commands"
---

# Tasks: Telegram Slash-Command Surface

**Feature**: 004-slash-commands
**Branch**: `004-slash-commands`
**Input**: `specs/004-slash-commands/{plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md}`

**Tests**: Included. Plan enumerates new test files (`tests/unit/test_commands_registry.py`, plus 5 new integration tests under `tests/integration/`). Existing 002/003 tests must keep passing unchanged (SC-005 backwards-compat).

**Organization**: Tasks are grouped by user story (US1 P1, US2 P1, US3 P2, US4 P2). MVP cut = US1 + US2 (autocomplete + /run + /done graceful stop). US3 + US4 round out the full surface.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Different file, no dependency on incomplete task → may run in parallel
- **[Story]**: `US1`–`US4`, applied to user-story-phase tasks only

## Path Conventions

Single-project layout, paths relative to repo root:

- Source: `src/remotask/`
- Tests: `tests/{unit,integration,fakes}/`
- Specs: `specs/004-slash-commands/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Curated command registry as single source of truth + new config field.

- [X] T001 Create new module `src/remotask/telegram/commands.py` exporting `CuratedCommand` (frozen dataclass with `name`, `description`, `requires_topic`, `requires_args`) and a frozen `CURATED_COMMANDS` tuple containing exactly `run`, `done`, `status` per `contracts/set-my-commands.md`.
- [X] T002 [P] Add `default_project_jira_key: str = ""` to `AgentConfig` in `src/remotask/core/config.py` with a regex validator (`^[A-Z]{2,10}$` when non-empty); place next to the other agent fields from 003.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Parsing primitives, Bot API extensions, audit/listener-state plumbing, and topic templates that every user-story phase consumes.

⚠️ **CRITICAL**: Phase 3+ depends on Phase 2.

- [X] T003 [P] Add `match_slash_command(message: dict, *, bot_username: str | None) -> SlashCommandInvocation | None` to `src/remotask/telegram/parser.py`. Detects `entities[0].type == "bot_command"` at offset 0, strips trailing `@<botname>`, splits args once on `\s+`. Return type is a new module-level dataclass.
- [X] T004 [P] Add `set_my_commands(commands)` and `get_me()` async methods to `src/remotask/telegram/client.py`. `set_my_commands` posts to `/setMyCommands` with default scope (no `scope` field); `get_me` fetches the bot's username for the `@<botname>` stripping logic. Both use the existing `_call()` plumbing.
- [X] T005 [P] Add four new audit event constants to `src/remotask/daemon/audit.py`: `EV_SLASH_COMMAND_RECEIVED` (session-bound), `EV_SLASH_COMMAND_REJECTED`, `EV_COMMANDS_REGISTERED`, `EV_COMMANDS_REGISTRATION_FAILED` (all unbound). Place next to 003's constants block.
- [X] T006 [P] Extend `ListenerState` in `src/remotask/daemon/listener_state.py` with `commands_registered: bool = False` and `commands_registered_at: float = 0.0`. Update `from_json` field-filter so old state files load cleanly with the new defaults.
- [X] T007 [P] Add new outbound templates to `src/remotask/daemon/topic.py`: `TPL_RUN_USAGE_HINT`, `TPL_RUN_NO_DEFAULT_PROJECT`, `TPL_STATUS_LIST_HEADER`, `TPL_STATUS_LIST_LINE`, `TPL_STATUS_DETAIL`, `TPL_STATUS_NO_ACTIVE`, `TPL_STATUS_NO_TOPIC_SESSION`, `TPL_STATUS_TRUNCATED`, with literal text from `contracts/slash-command-protocol.md`.
- [X] T008 [P] Extend `tests/fakes/fake_telegram.py` to record `setMyCommands` calls (`self.set_my_commands_calls: list[list[dict]]`) and `getMe` (return a fixed bot identity), plus a helper `push_slash_command(text, sender_id, *, chat_id=None, message_thread_id=None)` that injects a properly-shaped `bot_command` entity at offset 0.
- [X] T009 [P] Unit test the curated registry shape in `tests/unit/test_commands_registry.py`: `CURATED_COMMANDS` has exactly 3 entries with names `run`, `done`, `status`; descriptions ≤ 256 chars; `requires_topic` only true for `done`; `requires_args` only true for `run`.

**Checkpoint**: Foundation ready — user-story implementation can begin.

---

## Phase 3: User Story 1 — Autocomplete menu + `/run` with Jira-key (Priority: P1) 🎯 MVP slice 1

**Goal**: Operator sees three commands when typing `/`. `/run ZXTL-1234 ...` produces a session via the existing 002 routing (no behaviour change vs 003 plain-text trigger; what's new is the command came from the menu).

**Independent Test**: With one whitelisted operator, one registered project (`ZXTL`), and a daemon that has been restarted after this phase lands. (a) `setMyCommands` was called once at listener start with the curated set. (b) Posting `/run ZXTL-1234 also add a test` in the configured group's main chat creates a session for `ZXTL-1234`, the topic gets the standard 003 startup messages, and `sessions.trigger_text` for that row contains `also add a test`. (c) The 003 plain-text trigger (`ZXTL-1235`) also still works — backwards-compat smoke.

### Implementation for User Story 1

- [X] T010 [US1] Wire `setMyCommands` invocation into `Runtime._async_main()` in `src/remotask/daemon/runtime.py`. After the listener reports first poll OK, call `client.set_my_commands(...)` with the curated set serialised via `commands.py`; on success update `listener.state` (`commands_registered=True`, `commands_registered_at=now`) and emit `EV_COMMANDS_REGISTERED`; on failure log a warning + emit `EV_COMMANDS_REGISTRATION_FAILED` and continue.
- [X] T011 [US1] Cache the bot's username on the runtime: call `client.get_me()` once at listener startup, store the username on `Runtime`, and pass it through `DispatchContext` (new optional field `bot_username: str | None`).
- [X] T012 [US1] Add the slash-command branch to `src/remotask/daemon/dispatcher.py`: after the whitelist gate and `chat_id` check (and before the 003 termination / 002 issue-key branches), call `match_slash_command(message, bot_username=ctx.bot_username)`. If non-`None`, route to a new `_handle_slash_command(...)` function that dispatches by name; unknown names emit `EV_SLASH_COMMAND_REJECTED` with `reason=unknown_command` and return.
- [X] T013 [US1] Implement `_handle_slash_run(...)` in `src/remotask/daemon/dispatcher.py` for the **Jira-key path only** (free-text path is US4): parse args, if first token matches the issue-key regex use 002's accept-trigger flow with `trigger_text=<rest>`, store `EV_SLASH_COMMAND_RECEIVED` audit row on the new session. If args are empty → reply `TPL_RUN_USAGE_HINT` and emit `EV_SLASH_COMMAND_REJECTED` (`reason=empty_args`). Free-text fallback is a NotImplemented stub for US4 to fill in.

### Tests for User Story 1

- [X] T014 [P] [US1] Unit tests for `match_slash_command` in `tests/unit/test_telegram_parser.py` (extend the existing file): `/run` at offset 0, `/run@curious_claude_notification_bot` (suffix stripped), `/done` mid-sentence (no entity at 0 → returns `None`), bot_command at non-zero offset (returns `None`), entity present but text empty after `/run` (returns invocation with empty `args_text`), tab/multi-space args.
- [X] T015 [P] [US1] Unit tests for the dispatcher slash-command branch in `tests/unit/test_dispatcher.py`: (a) accept `/run ZXTL-1234 trailing text` → session inserted with `trigger_text="trailing text"` and `EV_SLASH_COMMAND_RECEIVED` row; (b) reject `/run` with empty args → `TPL_RUN_USAGE_HINT` posted, `EV_SLASH_COMMAND_REJECTED` audit row, no session; (c) reject unknown command `/foo` → audit-only `unknown_command`; (d) verify the slash branch never falls through to the 003 / 002 plain-text branches when a `bot_command` entity is present.
- [X] T016 [P] [US1] Integration test in `tests/integration/test_set_my_commands.py`: bring up the runtime with `fake_telegram`, observe that `set_my_commands_calls` contains exactly one entry whose `commands` field matches `CURATED_COMMANDS`. Then simulate a one-shot 503 from the fake on `setMyCommands` (next listener start) and confirm the listener still dispatches inbound messages — proves SC-006.
- [X] T017 [P] [US1] Integration test in `tests/integration/test_slash_run.py` (Jira-key only — free-text in US4): trigger `/run ZXTL-1234 also add tests` via `fake_telegram.push_slash_command`, confirm session row inserted with the right `issue_key`/`trigger_text`, topic created, worker spawned, terminal state reached.

**Checkpoint**: Operator gets the autocomplete menu and can `/run ZXTL-…`. MVP slice 1 done.

---

## Phase 4: User Story 2 — `/done` slash equivalent (Priority: P1) 🎯 MVP slice 2

**Goal**: `/done` posted inside a session-bound topic does exactly what 003's plain-text `done` does. Main-chat `/done` is silently rejected with audit. Plain-text `done` continues to work (backwards-compat).

**Independent Test**: Trigger any session, wait for first progress line, post `/done` inside the bound topic from a whitelisted account. Within 10s the session reaches `canceled` / `error_message=operator_stop`, identical to 003's plain-text `done`. Main-chat `/done` produces no Telegram reply, only an `audit.log` rejection with `reason=main_chat_done`.

### Implementation for User Story 2

- [X] T018 [US2] Implement `_handle_slash_done(...)` in `src/remotask/daemon/dispatcher.py`: enforce `requires_topic` from the registry — if `message_thread_id is None` → emit `EV_SLASH_COMMAND_REJECTED` (`reason=main_chat_done`) and return. Otherwise reuse the existing 003 `_handle_termination` flow, recording an `EV_SLASH_COMMAND_RECEIVED` row in addition to the existing 003 termination event (the operator can see both forms in the audit trail).

### Tests for User Story 2

- [X] T019 [P] [US2] Unit test cases added to `tests/unit/test_dispatcher.py`: (a) `/done` in topic with active session → SIGUSR1 sent, runtime in-flight set updated; (b) `/done` in main chat → `EV_SLASH_COMMAND_REJECTED` reason=`main_chat_done`, no signal; (c) `/done` in topic with no active session → `EV_SLASH_COMMAND_REJECTED` reason=`no_active_session`; (d) unauthorised `/done` → `EV_SLASH_COMMAND_REJECTED` reason=`unauthorized`.
- [X] T020 [P] [US2] Integration test in `tests/integration/test_slash_done.py`: trigger via `/run ZXTL-7777 ...`, after first PROGRESS post `/done` in the bound topic, assert worker exit + `Status: final iteration <i> (operator_stop)` topic message + session row `canceled` / `operator_stop`.

**Checkpoint**: `/run` + `/done` work as a complete slash-command driven loop. **First releasable cut.**

---

## Phase 5: User Story 3 — `/status` reply (Priority: P2)

**Goal**: `/status` in the main chat lists active sessions (≤ 10 lines, most-recent-first); inside a topic returns that session's detail; `/status` with no active sessions returns the friendly "no active sessions" message.

**Independent Test**: With 0 sessions → main-chat `/status` returns `No active sessions.`. With N>0 sessions (mix of `running`, `starting`) → main-chat reply has one line per session, capped at 10. Inside a session-bound topic → returns that single session's detailed state. Inside a stale topic → `No active session in this topic.`

### Implementation for User Story 3

- [X] T021 [US3] Implement `_handle_slash_status(...)` in `src/remotask/daemon/dispatcher.py`: branch by `message_thread_id` null-ness. Main-chat path runs `SELECT … LIMIT 11` over `sessions WHERE status IN NON_TERMINAL_STATES ORDER BY enqueued_at DESC`, formats per `contracts/slash-command-protocol.md` using the templates from T007. Topic-detail path resolves the topic to a session via `core.db.get_active_session_by_topic` and formats `TPL_STATUS_DETAIL`; on miss, post `TPL_STATUS_NO_TOPIC_SESSION`.
- [X] T022 [P] [US3] Add a small helper `_latest_progress(session_id)` to `src/remotask/daemon/dispatcher.py` (or a new private module function) that reads the most recent `PROGRESS i/N` line from the per-session log file; it returns `(i, n) | None`. The `/status` formatter uses this for the iteration column. If the file is missing or has no PROGRESS line, returns `None` and the formatter renders `—`.

### Tests for User Story 3

- [X] T023 [P] [US3] Integration test in `tests/integration/test_slash_status.py`: (a) `/status` in main chat with zero active sessions → `No active sessions.`; (b) seed three running sessions and one terminal session in DB; `/status` in main chat → list of exactly three lines, in most-recent-first order, no terminal session; (c) `/status` inside one of those running topics → detail shape with the session's data; (d) `/status` in a stale topic → `No active session in this topic.`. Use direct DB inserts rather than going through the trigger path so the test stays fast.

**Checkpoint**: Operator can introspect daemon state without leaving Telegram.

---

## Phase 6: User Story 4 — `/run` free-text → default project (Priority: P2)

**Goal**: `/run` without a Jira-key in args falls back to `agent.default_project_jira_key`; if unset, replies with a hint and creates no session. The synthetic `issue_key` is `run-<YYYY-MM-DD-HH-MM>-<slug>-<6-hex>`.

**Independent Test**: With `agent.default_project_jira_key=ZXTL` set and registered, `/run fix the cache layer` creates a session whose `issue_key` matches the synthetic shape and whose `trigger_text` is `"fix the cache layer"`. With the field unset, the same command replies with `TPL_RUN_NO_DEFAULT_PROJECT` and creates no session.

### Implementation for User Story 4

- [X] T024 [US4] Add `synthesize_run_topic_id(args_text: str, *, now: datetime | None = None) -> str` helper to `src/remotask/daemon/dispatcher.py` (or a new tiny `daemon/slash_helpers.py` module): produces `run-<YYYY-MM-DD-HH-MM>-<slug>-<6-hex>` per `data-model.md` rules. The 6-hex is `secrets.token_hex(3)`. Slug uses `re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:20].rstrip("-") or "untitled"`.
- [X] T025 [US4] Replace the NotImplemented free-text fallback in `_handle_slash_run` (T013) with the actual implementation: when args do not lead with a Jira-key, look up `cfg.agent.default_project_jira_key`; if empty/unset → reply `TPL_RUN_NO_DEFAULT_PROJECT` + emit `EV_SLASH_COMMAND_REJECTED` reason=`no_default_project`; else resolve via `projects.by_prefix`, synthesise `issue_key` via T024, route through 002's accept-trigger flow with `issue_key=<synthetic>` and `trigger_text=<full args_text>`.

### Tests for User Story 4

- [X] T026 [P] [US4] Unit tests in `tests/unit/test_dispatcher.py`: (a) synthetic id slug shape via `synthesize_run_topic_id` (mock `now` so the date prefix is deterministic; assert regex match); (b) free-text `/run` with default project unset → `EV_SLASH_COMMAND_REJECTED` `reason=no_default_project`, hint posted, no session; (c) free-text `/run` with default project set but unregistered → also `no_default_project` (treats unregistered same as unset for clarity).
- [X] T027 [P] [US4] Integration test in `tests/integration/test_slash_run.py` (extend the existing US1 file or split as needed): with `agent.default_project_jira_key=ZXTL` and ZXTL registered, send `/run fix the cache layer` → session row's `issue_key` matches `^run-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-fix-the-cache-[0-9a-f]{6}$`, `trigger_text="fix the cache layer"`, topic name equals the synthetic id, worker runs to completion.

**Checkpoint**: Operator can drive sessions without ever knowing a Jira-key prefix.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T028 [P] Backwards-compat regression test in `tests/integration/test_backwards_compat.py`: in the same test invocation, mix (a) plain-text `ZXTL-1234` trigger, (b) `/run ZXTL-1235`, (c) plain-text `done` inside topic, (d) `/done` inside topic. All four pathways must reach a session terminal state correctly. Confirms SC-005.
- [X] T029 [P] Update `remotask telegram status` formatter in `src/remotask/commands/telegram.py` to show the new `commands` line (`registered (last: <iso>)` vs `not registered (will retry on next restart)`).
- [X] T030 [P] `uv run ruff check src/remotask tests`, `uv run mypy src/remotask/core`, `uv run pytest -q` — all clean. Fix any issues that surface.
- [X] T031 [P] Confirm `CLAUDE.md` active feature pointer is `specs/004-slash-commands/plan.md` (already updated in plan phase).
- [X] T032 Run `quickstart.md` end-to-end on a real Telegram group. Capture session rows + audit log lines as evidence. Update quickstart with troubleshooting addenda found.
- [X] T033 [P] Coverage check: ensure `telegram/parser.py:match_slash_command`, `telegram/commands.py`, and the new dispatcher branches are ≥ 85% covered.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no deps — start immediately.
- **Foundational (Phase 2)**: depends on Setup. **BLOCKS all user stories.**
- **US1 (Phase 3)**: depends on Foundational. P1, MVP slice 1.
- **US2 (Phase 4)**: depends on US1's dispatcher branch (T012); T018 calls into the same `_handle_slash_command` switch.
- **US3 (Phase 5)**: depends on Foundational + US1's dispatcher branch.
- **US4 (Phase 6)**: depends on US1's `_handle_slash_run` (T013); T025 fills in the stub.
- **Polish (Phase 7)**: after all desired user stories.

### Within Each User Story

- Tests can be drafted alongside or just after the implementation they cover. The plan does not mandate strict TDD; the [P] markers identify safe parallelism.

### Parallel Opportunities

- All Phase 1 tasks (T001, T002): different files → fully parallel.
- All Phase 2 tasks (T003–T009): different files → fully parallel.
- Within US1: T014 + T015 + T016 + T017 are different test files → all parallelizable. T010 + T011 + T012 + T013 share `dispatcher.py` / `runtime.py` and must be sequenced.
- Within US2: T019 + T020 different test files → parallel.
- Within US3: T021 + T022 share `dispatcher.py` (sequence); T023 standalone.
- Within US4: T024 standalone; T025 modifies `dispatcher.py` (sequence after T024); T026 + T027 parallel.
- Polish: T028, T029, T030, T031, T033 mostly independent.

---

## Parallel Example: Phase 2 (Foundational)

```bash
# All [P] tasks operate on different files:
T003: src/remotask/telegram/parser.py
T004: src/remotask/telegram/client.py
T005: src/remotask/daemon/audit.py
T006: src/remotask/daemon/listener_state.py
T007: src/remotask/daemon/topic.py
T008: tests/fakes/fake_telegram.py
T009: tests/unit/test_commands_registry.py
```

---

## Implementation Strategy

### MVP Slice 1 (US1 only)

1. Phase 1 (Setup) → Phase 2 (Foundational) → Phase 3 (US1).
2. **STOP and VALIDATE**: run quickstart Steps 1–3 (registration + `/run` Jira-key) on a real Telegram group.
3. Operator can now drive sessions via the autocomplete menu.

### MVP Slice 2 (US1 + US2)

1. Continue with Phase 4 (US2 `/done`).
2. **STOP and VALIDATE**: run quickstart Steps 5 + 11 (graceful stop + main-chat reject).
3. **First releasable cut of 004.**

### Full delivery

1. Continue with Phase 5 (`/status`) and Phase 6 (free-text `/run`).
2. Run Phase 7 polish.
3. Run quickstart end-to-end (Steps 1–12).

### Solo-Developer Strategy

This is a single-operator project. Use [P] markers to interleave file edits within a session. Sequence same-file edits.

---

## Notes

- `[P]` = different file, no logical dependency on incomplete work. Same-file [P] tasks must still be sequenced.
- Each user story is independently testable: US1 via `test_slash_run.py` + `test_set_my_commands.py`; US2 via `test_slash_done.py`; US3 via `test_slash_status.py`; US4 via the free-text portion of `test_slash_run.py`.
- Every task names exact file paths.
- No new database migration; V0001 schema (002 / 003) covers everything.
- Backwards-compat with 003's plain-text triggers is a hard requirement (SC-005). The slash-command branch must run *before* the 003 / 002 plain-text branches in the dispatcher, but only when a `bot_command` entity is present at offset 0 — plain text always falls through to 003 / 002.

---

## Format Validation

Every task above:

- Begins with `- [ ] T###`
- Includes either no story label (Setup / Foundational / Polish) or exactly one of `[US1]`–`[US4]`
- Names a concrete file path
- Has `[P]` only when the task does not share a file with another incomplete task in the same phase
