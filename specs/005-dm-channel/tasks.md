---

description: "Task list — 005 `/cancel` rename + `[KEY]` prefix + alias deprecation"
---

# Tasks: `/cancel` Rename + `[KEY]` Prefix + Alias Deprecation

**Input**: Design documents from `/specs/005-dm-channel/`
**Prerequisites**: plan.md, spec.md (rev 2 narrowed scope), research.md, data-model.md, contracts/cancel-command-protocol.md, quickstart.md

**Tests**: Tests are INCLUDED. SC-003 mandates that "every existing 002/003/004 integration test that does not specifically assert on `/done` or the un-prefixed message body continues to pass unchanged" — regression coverage is core, not optional.

**Organization**: Tasks are grouped by user story (rev 2 spec):

- US1 (P1): `/cancel` canonical
- US2 (P1): Backwards-compat aliases (`/done` slash + plain-text `done`/`stop`/`finish`)
- US3 (P2): `[KEY]` prefix on session-bound messages
- US4 (P3): Unchanged-surface regression

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- File paths are absolute / repo-relative as appropriate

## Path Conventions

- Source: `src/remotask/...`
- Tests: `tests/unit/...`, `tests/integration/...`, `tests/fakes/...`
- Specs: `specs/005-dm-channel/...`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify branch state and that 002/003/004 baseline is green before adding 005 deltas.

- [X] T001 Confirm current branch is `005-dm-channel` and working tree is clean except for `specs/005-dm-channel/` artifacts (run `git status` from repo root)
- [X] T002 Run the existing test suite to establish baseline pass count: `uv run pytest tests/ -x` from repo root; record the count for SC-003 verification later

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Constants, helpers, and runtime fields that every user story imports. Must complete before US1/US2/US3 can start.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 Add audit event constant `EV_ALIAS_DEPRECATION_USED` and rejection-reason constant `REASON_MAIN_CHAT_CANCEL` to `src/remotask/daemon/audit.py` (preserve existing `REASON_MAIN_CHAT_DONE` — both will appear in audit logs going forward; see research R5)
- [X] T004 [P] Add `alias_deprecation_warned: set[tuple[str, str]]` field to `Runtime` in `src/remotask/daemon/runtime.py`, initialised in `__init__` to `set()`; add docstring referencing data-model.md "Lifecycle of alias_deprecation_warned"
- [X] T005 [P] Add `format_progress(issue_key: str, body: str) -> str` helper to `src/remotask/daemon/topic.py` that returns `f"[{issue_key}] {body}"`; one-line docstring referencing data-model.md "Outbound message catalogue"
- [X] T006 Add terminal-transition cleanup hook in `src/remotask/daemon/sessions.py` (or wherever the existing 003 transition helper lives): when a session moves to a terminal state, drop every `(_, session_id)` tuple from `runtime.alias_deprecation_warned` (depends on T004)
- [X] T007 [P] Add unit test `tests/unit/test_audit_constants.py` (or extend existing audit tests) asserting both `EV_ALIAS_DEPRECATION_USED` and `REASON_MAIN_CHAT_CANCEL` are exported strings, distinct from existing constants

**Checkpoint**: Foundation ready — US1/US2/US3 implementation can begin in parallel.

---

## Phase 3: User Story 1 — `/cancel` canonical (Priority: P1) 🎯 MVP

**Goal**: Operators can post `/cancel` inside a session topic to terminate the running worker, with the same SIGUSR1 → grace → SIGTERM ladder as 003/004's `/done`. The `setMyCommands` payload advertises `/cancel` (not `/done`).

**Independent Test**: Trigger `/run ZXTL-1234 …`, wait for first progress, post `/cancel` inside the topic. Within 10s the session reaches `canceled / operator_stop`, the topic shows the operator-stop final + canceled-by-operator messages, and `setMyCommands` payload contains `cancel` not `done`.

### Tests for User Story 1

- [X] T008 [P] [US1] Update `tests/unit/test_telegram_parser.py` with `/cancel` slash-command parsing cases: `/cancel`, `/cancel@<botname>`, case-insensitive, no-args (FR-002 → no `args_text`); confirm an unrelated `/cancel something` still parses but is rejected at dispatcher level (out-of-scope grammar)
- [X] T009 [P] [US1] Update `tests/unit/test_commands_registry.py` to pin `CURATED_COMMANDS` to exactly `(run, cancel, status)` in that order; assert `done` is NOT in the tuple; assert `cancel.requires_topic == True` and `cancel.requires_args == False`
- [X] T010 [P] [US1] Update `tests/unit/test_dispatcher.py` with three cases: (a) `/cancel` inside topic with active session → 003 SIGUSR1 ladder triggered, `slash_command_received command=cancel` audit row; (b) `/cancel` in main chat (`message_thread_id=None`) → `slash_command_rejected reason=main_chat_cancel`, no signal; (c) `/cancel` inside topic with no active session → `slash_command_rejected reason=no_active_session`, no signal
- [X] T011 [P] [US1] Add `tests/integration/test_cancel_canonical.py`: end-to-end `/run` → wait for first progress → `/cancel` → assert session DB row reaches `canceled / operator_stop` within 10s, topic receives `Session canceled by operator.` post

### Implementation for User Story 1

- [X] T012 [P] [US1] Update `src/remotask/telegram/commands.py`: change `CURATED_COMMANDS` to `(run, cancel, status)`; description for `cancel` = `"Cancel an active session"`; `requires_topic=True`, `requires_args=False`; remove the `done` entry
- [X] T013 [P] [US1] Update `src/remotask/telegram/parser.py`: add `cancel` to the recognised-name set used by `match_slash_command`; the existing offset-0 + length normalisation from 004 covers parsing
- [X] T014 [US1] Update `src/remotask/daemon/dispatcher.py`: add `name == "cancel"` branch to `_handle_slash_command`. Behaviour: if `message_thread_id is None` → `slash_command_rejected reason=main_chat_cancel` (audit-only); else resolve `session_id` via `core.db.get_active_session_by_topic` — if missing → `slash_command_rejected reason=no_active_session`; else record `slash_command_received command=cancel` and invoke the existing 003 termination ladder (SIGUSR1 + grace watchdog) — depends on T003, T013

**Checkpoint**: At this point `/cancel` works end-to-end; setMyCommands shows the new payload; integration test green.

---

## Phase 4: User Story 2 — Backwards-compat aliases (Priority: P1)

**Goal**: `/done` (slash) and plain-text `done` / `stop` / `finish` (003) continue to cancel sessions for the duration of the deprecation window (one release; removed in 006). Each first use per `(alias_token, session_id)` pair emits a structured-log `WARNING` and an `alias_deprecation_used` audit row. Repeated alias use on the same session is silent.

**Independent Test**: Trigger a session, post `/done` → cancellation works + WARNING + audit. Trigger another, post plain-text `stop` → same. Trigger a third, post `/done` twice in quick succession → cancellation on first, no second WARNING for that (alias, session) pair.

### Tests for User Story 2

- [X] T015 [P] [US2] Add `tests/unit/test_runtime_alias_warned.py`: assert that `runtime.alias_deprecation_warned` is empty on init; that adding `("/done", "S1")` then re-checking returns `True` (idempotency); that the terminal-transition cleanup hook (T006) removes only `(_, "S1")` entries, leaving `(_, "S2")` intact
- [X] T016 [P] [US2] Update `tests/unit/test_dispatcher.py` with alias cases: (a) `/done` slash form inside topic with active session → cancellation + WARNING emitted + `alias_deprecation_used` audit row + `slash_command_received command=done`; (b) plain-text `stop` inside topic → same behaviour with `alias_token=stop`; (c) `/done` posted twice on same session → second call adds no second WARNING; (d) `/done` posted in main chat → `slash_command_rejected reason=main_chat_done` (NOT `main_chat_cancel` — preserves 004 reason for the alias path, R5)
- [X] T017 [US2] Add `tests/integration/test_alias_deprecation.py`: end-to-end run with `/done`, `done` (plain-text), `stop`, `finish` — each cancels a fresh session, each emits exactly one WARNING + audit row per (alias, session); verify cross-session WARNING repetition by triggering session A → `/done` → session B → `/done` (expect 2 WARNINGs total in daemon.log for `alias_token=/done`)

### Implementation for User Story 2

- [X] T018 [US2] Add `_emit_alias_warning(invocation, alias_token: str, session_id: str)` helper in `src/remotask/daemon/dispatcher.py`: check `runtime.alias_deprecation_warned`, return early if pair present; else add to set, log structlog `WARNING(event="alias_deprecation", alias_token=…, canonical="cancel", session_id=…)`, write audit row with type `EV_ALIAS_DEPRECATION_USED` carrying full payload (alias_token, canonical, session_id, sender_id, message_id, chat_id, message_thread_id) — depends on T003, T004
- [X] T019 [US2] Update `src/remotask/daemon/dispatcher.py` `_handle_slash_command`: add `name == "done"` branch routing through `_emit_alias_warning(alias_token="/done", …)` then the same cancel handler as `/cancel`, with the topic/main-chat gate using `reason=main_chat_done` (preserves 004 audit value, R5) — depends on T014, T018
- [X] T020 [US2] Update `src/remotask/daemon/dispatcher.py` plain-text alias path (the existing 003 `match_termination_command` branch): wrap with `_emit_alias_warning(alias_token=<resolved>, …)` before invoking the cancel handler; alias_token resolution = `text.strip().lstrip("/").lower()` (one of `done` / `stop` / `finish`) — depends on T018
- [X] T021 [US2] Verify `src/remotask/telegram/parser.py` still routes `/done` through the bot_command path (the parser does not need to know `done` is deprecated; it just parses; the dispatcher decides the deprecation behaviour) — confirm with a quick read; no code change expected

**Checkpoint**: At this point both `/cancel` and the four alias forms cancel sessions; deprecation WARNING + audit row land exactly once per (alias, session) pair; main-chat-done audit reason is distinguishable from main-chat-cancel.

---

## Phase 5: User Story 3 — `[KEY]` prefix on session-bound messages (Priority: P2)

**Goal**: Every progress / status / final / canceled message the worker posts to a session's topic begins with `[<issue_key>]` followed by a single space. Templates that already name the issue_key in their body (`Session starting for ZXTL-1234. Worktree: …`, `Draft PR opened: <url>`) skip the prefix to avoid stutter.

**Independent Test**: Trigger one session and read its topic. Every line in `data-model.md` "Outbound message catalogue" marked Prefixed=Yes begins with `[ZXTL-1234]` and a space. Every line marked Prefixed=No does NOT begin with the prefix.

### Tests for User Story 3

- [X] T022 [P] [US3] Add `tests/unit/test_topic_format.py`: assert `topic.format_progress("ZXTL-1234", "Status: iter 1/5") == "[ZXTL-1234] Status: iter 1/5"`; assert with various keys (synthetic ids `run-2026-…-a3f9b1`) and bodies; one negative case ensures the helper does not strip leading whitespace from `body`
- [X] T023 [P] [US3] Add `tests/integration/test_key_prefix.py`: trigger a session, capture every outbound message via `tests/fakes/fake_telegram.py`; assert `Session starting for …` and `Draft PR opened: …` (if emitted) do NOT carry the prefix; assert every other progress / `Status:` / final / canceled message begins with `[<issue_key>]` followed by a space

### Implementation for User Story 3

- [X] T024 [US3] Update `src/remotask/daemon/worker.py`: route progress, `Status:`, `final`, `completed`, `canceled`, `failed`, `Session canceled by operator.`, `Session stopped (forced) by operator.`, `Session timed out`, `Session failed: …` posts through `topic.format_progress(spec.issue_key, body)`; route `Session starting for …`, `Draft PR opened: …` posts directly without the helper. Concretely: introduce two local helpers `post_progress(body)` (prefixed) and `post_template(body)` (not prefixed); refactor existing call sites to pick the right one — depends on T005

**Checkpoint**: Topic messages from all session-bound paths now carry `[KEY]`; the `Session starting` template still reads as before.

---

## Phase 6: User Story 4 — Unchanged-surface regression (Priority: P3)

**Goal**: 002 plain-text Jira-key trigger, 003 plain-text alias termination (now wrapped with WARNING but otherwise identical), 004 `/run` (Jira-key + free-text + synthetic id) and `/status` (main-chat list + topic-detail) all continue to work bit-for-bit. SC-003: "every existing 002/003/004 integration test that does not specifically assert on `/done` or the un-prefixed message body continues to pass unchanged."

**Independent Test**: Run the full pre-005 test suite (002 + 003 + 004 integration tests), updating only the assertions that pin the un-prefixed body of session-bound messages or the absence of the prefix; confirm pass count matches T002's baseline modulo the documented updates.

### Tests for User Story 4

- [X] T025 [P] [US4] Audit existing 002/003/004 integration tests for assertions that will break under 005's `[KEY]` prefix: search for `assertEqual.*Status:` or `in body` patterns asserting un-prefixed status lines; document the list in a comment block at the top of `tests/integration/test_backwards_compat.py` (T026)
- [ ] T026 [US4] Add `tests/integration/test_backwards_compat.py`: a single suite that exercises (a) 002 plain-text Jira-key trigger in main chat (Privacy Mode OFF assumed), (b) 003 plain-text alias `done` inside topic still cancels (now with WARNING — assert via the alias_deprecation_used audit row), (c) 004 `/run ZXTL-1234 free text` happy path, (d) 004 `/run free text only` synthetic-id happy path, (e) 004 `/status` in main chat returns the active list, (f) 004 `/status` inside topic returns the detail summary; this suite is the regression backstop for SC-003
- [X] T027 [P] [US4] Update existing 002/003/004 integration tests identified in T025 to assert on the prefixed body where it now applies; do NOT change tests that don't touch session-bound progress/final lines

**Checkpoint**: Full test suite green; T002's baseline pass count is preserved or increased.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Real-bot validation, documentation hygiene, and lint/type pass.

- [X] T028 Update `src/remotask/commands/telegram.py` if any 005-introduced state is worth surfacing in `remotask telegram status` — expected: NO change (no new persistent fields). Verify by reading the existing status formatter; document in commit message that 005 adds no status surface
- [ ] T029 [P] Run `quickstart.md` Steps 1–11 end-to-end against a real Telegram bot in the configured forum group; record any deviations and fix the corresponding code path
- [X] T030 [P] Run `uv run ruff check src/ tests/` and `uv run mypy src/` (or equivalent lint/type commands defined in 002+) and resolve any 005-introduced findings
- [X] T031 Run the full test suite one final time (`uv run pytest tests/ -x`) and confirm pass count ≥ T002's baseline (allowing for new 005 tests added)
- [ ] T032 Verify `audit.log` after a quickstart run contains: at least one `slash_command_received command=cancel`, at least one `alias_deprecation_used`, and at least one each of `slash_command_rejected reason=main_chat_cancel` and `slash_command_rejected reason=main_chat_done` from Steps 8–9 (proves R5 distinguishability landed)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup. Blocks all user stories.
- **US1 (Phase 3)**: Depends on Foundational. Independently testable once `/cancel` happy path lands.
- **US2 (Phase 4)**: Depends on Foundational + US1's `_handle_cancel` reuse (T014). Can be staged after T014 lands; tests T015–T017 run in parallel with US1's later tasks.
- **US3 (Phase 5)**: Depends on Foundational (specifically T005 for `format_progress`). Independent of US1/US2.
- **US4 (Phase 6)**: Depends on US1 + US2 + US3 landing (regression cannot be validated until the canonical command + aliases + prefix are all in place).
- **Polish (Phase 7)**: Depends on US1–US4.

### Within Each User Story

- Tests (T008–T011 for US1, T015–T017 for US2, T022–T023 for US3, T025–T027 for US4) MUST be written and FAIL before their implementation tasks land (TDD discipline inherited from 002+).
- Implementation tasks within a story follow the per-story checkpoint sequence.

### Parallel Opportunities

- **Within Foundational**: T004 ‖ T005 ‖ T007 (different files); T003 first then T006.
- **Within US1**: T008 ‖ T009 ‖ T010 ‖ T011 (test files), T012 ‖ T013 (different source files), T014 sequential after T013.
- **Within US2**: T015 ‖ T016 (test files); T018 first, then T019 ‖ T020.
- **Within US3**: T022 ‖ T023 (test files); T024 sequential.
- **Within US4**: T025 ‖ T027; T026 sequential.
- **Across stories**: After Foundational, US1 + US3 can proceed in parallel by different developers (different file sets); US2 should follow US1's T014 to reuse the cancel handler.

---

## Parallel Example: User Story 1

```bash
# Launch all US1 unit tests in parallel:
Task: "Update tests/unit/test_telegram_parser.py with /cancel parsing cases"
Task: "Update tests/unit/test_commands_registry.py with (run, cancel, status) pin"
Task: "Update tests/unit/test_dispatcher.py with /cancel happy path + main_chat_cancel + no_active_session"
Task: "Add tests/integration/test_cancel_canonical.py"

# Then launch US1 implementation in parallel where files don't conflict:
Task: "Update src/remotask/telegram/commands.py CURATED_COMMANDS"
Task: "Update src/remotask/telegram/parser.py /cancel recognition"

# Then sequentially:
Task: "Update src/remotask/daemon/dispatcher.py /cancel branch (depends on parser change)"
```

---

## Implementation Strategy

### MVP scope (US1 + US2)

005's spec puts US1 and US2 both at P1 — they form one MVP. Without US2 the day-of-upgrade UX regresses (operators with `/done` muscle memory get a silent failure). Without US1 there is no canonical command to migrate to.

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: US1 (`/cancel` canonical) — tests + implementation + checkpoint
4. Complete Phase 4: US2 (aliases) — tests + implementation + checkpoint
5. **STOP and VALIDATE**: Real-bot test of `/cancel` + `/done` aliases (quickstart Steps 1–11 partial)
6. Ship MVP if standalone US1+US2 is what 005 is taken to be

### Incremental Delivery

1. Setup + Foundational → infrastructure ready.
2. US1 → `/cancel` canonical; ship if we want only the rename.
3. US2 → aliases keep working; **MVP boundary** for 005.
4. US3 → `[KEY]` prefix lands; quality-of-life win.
5. US4 → regression validated; full SC-003 satisfied.
6. Polish → real-bot quickstart + lint + final test run.

### Notes for the implementer

- 005 has zero schema migrations and zero new config fields. If a task suggests adding either, re-read `data-model.md` — it's the wrong path.
- The deprecation aliases removal lives in feature 006, not 005. 005 ships them with a WARNING; do NOT delete the alias dispatch branches.
- The `topic.py` module is intentionally NOT renamed in 005 (research R7). Leave the name alone.
- Audit reason `main_chat_done` is intentionally retained for the `/done` alias path; do NOT collapse it into `main_chat_cancel` (research R5).

---

## Notes

- [P] tasks = different files, no dependencies on each other.
- [Story] label maps each task to a user story for traceability against spec.md.
- Each user story is independently completable and testable.
- Tests are written first within each story (TDD discipline from 002+).
- Commit after each task or logical group (auto-commit hooks in `.specify/extensions.yml` will prompt).
- Stop at the US2 checkpoint to ship MVP if scope demands.
