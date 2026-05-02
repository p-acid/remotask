# Tasks: Remove Deprecated Termination Aliases

**Input**: Design documents from `/specs/006-remove-termination-aliases/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Test tasks ARE included — spec FR-018/019/020 explicitly mandate test surface changes (deletions,
migrations, regressions).

**Organization**: Tasks are grouped by user story per spec.md; foundational phase consolidates the dispatcher cleanup
+ orphaned API removal + impacted-test maintenance so the suite stays green between phases.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- File paths in task descriptions are absolute file paths from repo root

## Path Conventions

- Single project. Source under `src/remotask/`, tests under `tests/`.

---

## Phase 1: Setup

**Purpose**: Project initialization. **None for this feature** — no new dependencies, no new directories, no new
configuration. Skip.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Remove the deprecated alias machinery from production code AND update all impacted tests so the suite
stays green when this phase completes. This is required before adding regression tests in user-story phases.

**⚠️ CRITICAL**: After Phase 2 the deprecated alias paths are gone, the orphaned APIs are removed, and the test suite
runs green. User-story phases only ADD regression tests; they do not change production code.

### Phase 2a — Dispatcher cleanup (sequential — all touch `src/remotask/daemon/dispatcher.py`)

- [X] T001 Remove the `name == "done"` slash-command branch (the block that called `_emit_alias_warning(...)` and
      `_handle_slash_cancel(invocation, ctx, alias_token="/done")`) from `src/remotask/daemon/dispatcher.py`.
- [X] T002 Remove the plain-text 003 termination dispatch path (the `if message_thread_id is not None and
      match_termination_command(text) is not None:` block around line 126 and the alias-warning emission around
      line 161) from `src/remotask/daemon/dispatcher.py`.
- [X] T003 Remove the `_emit_alias_warning(...)` helper function (defined around line 948) from
      `src/remotask/daemon/dispatcher.py`.
- [X] T004 Simplify `_handle_slash_cancel` in `src/remotask/daemon/dispatcher.py` by dropping the `alias_token`
      keyword-only parameter and any `if alias_token is not None: _emit_alias_warning(...)` branch inside it. Update
      the `name == "cancel"` call site to invoke `_handle_slash_cancel(invocation, ctx)` (no `alias_token=`).
- [X] T005 Remove the `_on_terminal(sid)` callback definition and the `on_terminal=_on_terminal` keyword argument in
      the `worker.run_worker(...)` call inside `_handle_run_command` of `src/remotask/daemon/dispatcher.py`.
- [X] T006 Remove the `match_termination_command` import line at the top of `src/remotask/daemon/dispatcher.py`.
- [X] T007 Remove the `audit.EV_ALIAS_DEPRECATION_USED` reference (the `audit_event(...)` call inside the now-deleted
      `_emit_alias_warning`) and the `audit.REASON_MAIN_CHAT_DONE` reference (around line 606 in the main-chat
      `/done` handling) from `src/remotask/daemon/dispatcher.py`.
- [X] T008 Remove the three deprecation callback fields (`has_alias_deprecation_warned`,
      `record_alias_deprecation_warned`, `clear_alias_deprecation_for_session`) from the `DispatchContext` dataclass
      in `src/remotask/daemon/dispatcher.py`. Also remove their docstring/comment block.

### Phase 2b — Orphaned API removal (parallelizable, different files)

- [X] T009 [P] Remove the `match_termination_command` function from `src/remotask/telegram/parser.py`. Keep
      `extract_first_issue_key`, `split_prefix`, and `match_slash_command` untouched.
- [X] T010 [P] Remove `EV_ALIAS_DEPRECATION_USED: Final = "alias_deprecation_used"` and
      `REASON_MAIN_CHAT_DONE: Final = "main_chat_done"` (and any associated comments referencing them) from
      `src/remotask/daemon/audit.py`.
- [X] T011 [P] Remove the `_alias_deprecation_warned: set[tuple[str, str]] = set()` initializer, the three accessor
      methods (`has_alias_deprecation_warned`, `record_alias_deprecation_warned`,
      `clear_alias_deprecation_for_session`), and the three keyword arguments
      (`has_alias_deprecation_warned=...`, `record_alias_deprecation_warned=...`,
      `clear_alias_deprecation_for_session=...`) passed to `DispatchContext(...)` from
      `src/remotask/daemon/runtime.py`.
- [X] T012 [P] Remove the `on_terminal: Callable[[str], None] | None = None` parameter from the `run_worker(...)`
      signature and the `if on_terminal is not None: try: on_terminal(spec.session_id) except ...` block at the
      worker exit path in `src/remotask/daemon/worker.py`. Also remove the `Callable` import if it becomes unused.

### Phase 2c — Test surface updates (parallelizable, different files)

- [X] T013 [P] Delete `tests/integration/test_alias_deprecation.py` (entire file).
- [X] T014 [P] Delete `tests/integration/test_slash_done.py` (entire file).
- [X] T015 [P] Delete `tests/unit/test_runtime_alias_warned.py` (entire file).
- [X] T016 [P] Remove `TestMatchTerminationCommand` class from `tests/unit/test_telegram_parser.py`. Leave
      `TestExtractFirstIssueKey`, `TestSplitPrefix`, `TestMatchSlashCommand`, and `TestSlashCancel` intact.
- [X] T017 [P] Remove `TestAliasDeprecation` class (and any other class whose body exclusively exercises the
      removed alias paths) from `tests/unit/test_dispatcher.py`. For all remaining test classes that construct a
      `DispatchContext`, drop the three deprecation callback keyword arguments
      (`has_alias_deprecation_warned=...`, `record_alias_deprecation_warned=...`,
      `clear_alias_deprecation_for_session=...`).
- [X] T018 [P] Remove the assertions referring to `audit.EV_ALIAS_DEPRECATION_USED` and `audit.REASON_MAIN_CHAT_DONE`
      from `tests/unit/test_audit.py`. Specifically the `assert audit.EV_ALIAS_DEPRECATION_USED == "..."` line, the
      `assert audit.REASON_MAIN_CHAT_DONE == "..."` line, the
      `assert audit.REASON_MAIN_CHAT_CANCEL != audit.REASON_MAIN_CHAT_DONE` line, and any membership check that
      references `EV_ALIAS_DEPRECATION_USED` (e.g., the constant set whitelist).

### Phase 2d — 003 plain-text termination test migration (sequential — both files apply the same pattern)

- [X] T019 Migrate `tests/integration/test_operator_stop.py` to trigger termination via the `/cancel` slash command
      instead of plain-text `done`/`stop`/`finish`. Reuse the slash-command message constructor pattern from
      `tests/integration/test_cancel_canonical.py` (or its 005-introduced equivalent). The graceful ladder, status
      transitions, "Session canceled by operator." template, and `[<issue_key>]` prefix expectations MUST remain
      unchanged.
- [X] T020 Migrate `tests/integration/test_operator_stop_forced.py` to trigger termination via the `/cancel` slash
      command instead of plain text. The forced ladder semantics, "Session force-canceled by operator (grace window
      exceeded)." template, and grace-window timing expectations MUST remain unchanged.

### Phase 2e — Validation gate

- [X] T021 Run `uv run pytest -q` and confirm the full suite passes (deletions + migrations leave the suite green).
      Confirm no `ImportError` or `AttributeError` referencing any removed symbol. If failures appear, do not proceed
      to Phase 3 until they are resolved.

**Checkpoint**: After Phase 2 the deprecated alias machinery is gone from `src/`, the impacted tests are deleted or
migrated, and `pytest -q` passes. The user-visible behavior change (US1 + US2) is in effect *now*; user-story phases
only ADD regression tests to lock it in.

---

## Phase 3: User Story 1 — `/cancel` as Sole Termination Command (Priority: P1) 🎯 MVP

**Goal**: Lock in that `/done` slash no longer triggers termination — it returns the standard `unknown_command`
rejection — while `/cancel` continues to work exactly as 005 defined.

**Independent Test**: Trigger a session, send `/done` in its topic, observe the session keeps running and the
dispatcher emits `slash_command_rejected reason=unknown_command`. Then send `/cancel` and observe the session
terminating per 005 semantics.

### Tests for User Story 1

- [X] T022 [P] [US1] Create regression test `tests/integration/test_done_command_removed.py`. Cover three scenarios:
      (a) `/done` sent inside an active session topic → session unchanged + `slash_command_rejected
      reason=unknown_command` audit row;
      (b) `/done` sent in main chat (outside any topic) → same `slash_command_rejected reason=unknown_command`
      (NOT `reason=main_chat_done`);
      (c) `/done@<bot_username>` form sent in topic → same `unknown_command` rejection.
      For all three, additionally assert that no `alias_deprecation_used` audit row is written and no outbound
      Telegram message body contains the substring `"deprecated"`.
      Use the existing `tests.fakes.fake_telegram.FakeTelegram` and DB fixtures from
      `tests/integration/test_cancel_canonical.py` as the model.

### Implementation for User Story 1

> Production code change is already in place from Phase 2. The user-story task is the regression test.

- [X] T023 [US1] Run `uv run pytest tests/integration/test_done_command_removed.py -v` and confirm all three
      scenarios pass.

**Checkpoint**: User Story 1 lock-in complete. `/cancel` canonical (still passing 005's
`tests/integration/test_cancel_canonical.py`) + `/done` rejection guaranteed.

---

## Phase 4: User Story 2 — Plain-Text `done`/`stop`/`finish` Are Non-Control (Priority: P2)

**Goal**: Lock in that bare `done`, `stop`, or `finish` posted in a session topic is treated as ordinary chat — no
termination, no warning, no audit row.

**Independent Test**: Trigger a session, post each of `done`, `stop`, `finish` in its topic, observe the session
unaffected and `audit.log` size unchanged.

### Tests for User Story 2

- [X] T024 [P] [US2] Create regression test `tests/integration/test_plain_termination_dead.py`. Cover:
      (a) plain `done` posted in active topic → no session state change, no outbound message, no new audit row;
      (b) plain `stop` posted in active topic → same;
      (c) plain `finish` posted in active topic → same;
      (d) plain `done` posted in main chat (already non-control in 005, regression guard) → same.
      Assert `len(fake_tg.sent_messages)` is unchanged after each plain-text post (compare snapshot before/after).
      Assert `conn.execute("SELECT COUNT(*) FROM session_events").fetchone()[0]` is unchanged. Assert no audit log
      file line contains `"alias_deprecation_used"` for the test's session_id.

### Implementation for User Story 2

> Production code change is already in place from Phase 2 (parser function gone, dispatcher branch gone).

- [X] T025 [US2] Run `uv run pytest tests/integration/test_plain_termination_dead.py -v` and confirm all four
      scenarios pass.

**Checkpoint**: User Story 2 lock-in complete. Plain-text 003 termination grammar definitively dead.

---

## Phase 5: User Story 3 — No Alias-Deprecation Warnings Reach Operator (Priority: P3)

**Goal**: Verify there is no surface from which a "deprecated" warning can leak — no template, no audit reason, no
code path.

**Independent Test**: Across a session that exercises `/cancel`, `/done`, `done`, `stop`, `finish` in sequence, the
operator's view contains zero message bodies with the word "deprecated".

### Tests for User Story 3

- [X] T026 [P] [US3] Add a single test in `tests/integration/test_done_command_removed.py` (extend the file from US1)
      named `test_no_deprecation_warning_across_input_sequence`: trigger a session, send the sequence
      `[/cancel, /done, done, stop, finish]` over the dispatcher (using main-chat `/cancel` so the session survives
      the first command — main-chat `/cancel` becomes `slash_command_rejected reason=main_chat_cancel`), and assert
      that `all("deprecated" not in m.text for m in fake_tg.sent_messages)`.

### Implementation for User Story 3

- [X] T027 [US3] Run `uv run pytest tests/integration/test_done_command_removed.py::test_no_deprecation_warning_across_input_sequence -v`
      and confirm it passes.

**Checkpoint**: All three user stories independently verified.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T028 Run `grep -rn 'match_termination_command\|_alias_deprecation_warned\|EV_ALIAS_DEPRECATION_USED\|REASON_MAIN_CHAT_DONE\|_emit_alias_warning' src/remotask/`
      and confirm zero hits. (SC-001 verification.)
- [X] T029 Run `grep -rn 'on_terminal' src/remotask/` and confirm zero hits in production source.
- [ ] T030 Run the full quickstart manually per `specs/006-remove-termination-aliases/quickstart.md` against a real
      Telegram supergroup — Steps 1-6. Note any deviation in the quickstart's "실패 시 점검 포인트" section.
      *(Deferred — requires live Telegram supergroup; run before merging.)*
- [X] T031 Run `uv run pytest -q` one final time. Confirm the total test count is in the expected range
      (≈ 308 [005 baseline] − 18 [removed/shrunk] + 2 [new regression files] = ≈ 292; the exact number is acceptable
      as long as it matches what the deletions imply).
- [X] T032 Update `CLAUDE.md` if the active feature plan reference is still pointing somewhere stale (it should
      already point to `specs/006-remove-termination-aliases/plan.md` from Phase 1 of `/speckit-plan`; this is a
      sanity check, not a re-write).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: skipped.
- **Phase 2 (Foundational)**: must complete before Phase 3+. Within Phase 2:
  - Phase 2a (T001–T008) is sequential (all in `dispatcher.py`).
  - Phase 2b (T009–T012) is parallelizable (each task in a different file) and depends on Phase 2a's T006/T007/T008
    so the dispatcher does not import / reference symbols that are about to disappear.
  - Phase 2c (T013–T018) is parallelizable (different test files); has no production-code dependency on Phase 2a/2b
    BUT pytest collection will fail until Phase 2b completes (test files import the soon-to-be-deleted symbols),
    so the safe order is: Phase 2a → Phase 2b → Phase 2c → Phase 2d → Phase 2e.
  - Phase 2d (T019–T020) sequentially migrates two test files. Depends on Phase 2a/2b.
  - Phase 2e (T021) is the validation gate.
- **Phase 3+ (User Stories)**: each depends on Phase 2e passing. Within each story, the test-add task and the
  test-run task are sequential. Stories themselves are independent and can be added in any order.
- **Phase 6 (Polish)**: depends on all user-story phases.

### Within Each User Story

- Tests (one per story, two for US3) are pure additions — they cannot fail before they exist. After each is added,
  run it to confirm green.
- No model/service hierarchy applies here (this is a deletion feature). Each user-story phase is a single
  test-creation + test-run pair.

### Parallel Opportunities

- **Phase 2b (T009, T010, T011, T012)**: four files, no cross-deps after Phase 2a — all four can run in parallel.
- **Phase 2c (T013, T014, T015, T016, T017, T018)**: six different test files — all parallelizable.
- **Phase 3 / Phase 4 / Phase 5**: independent stories — the three regression test files (T022, T024, T026) can be
  authored in parallel by different contributors and merged independently.
- **Phase 6 (T028, T029)**: two independent grep checks — parallelizable.

---

## Parallel Example: Phase 2b

```bash
# After Phase 2a is complete, run these four cleanups in parallel:
Task: "Remove match_termination_command from src/remotask/telegram/parser.py"
Task: "Remove EV_ALIAS_DEPRECATION_USED + REASON_MAIN_CHAT_DONE from src/remotask/daemon/audit.py"
Task: "Remove _alias_deprecation_warned set + 3 methods + DispatchContext wiring from src/remotask/daemon/runtime.py"
Task: "Remove on_terminal parameter + cleanup hook from src/remotask/daemon/worker.py"
```

## Parallel Example: User Story Tests

```bash
# After Phase 2 is fully green, the three regression test files can be added in parallel:
Task: "Create tests/integration/test_done_command_removed.py with three /done scenarios (US1)"
Task: "Create tests/integration/test_plain_termination_dead.py with four plain-text scenarios (US2)"
Task: "Add no-deprecation-warning sequence test to test_done_command_removed.py (US3 extension)"
```

---

## Implementation Strategy

### Single-developer delivery (recommended)

1. Phase 2a — sequentially edit `dispatcher.py` through T001–T008. Run `pytest -q` halfway and at the end; expect
   import errors during the middle (still referencing soon-to-be-removed APIs) and resolve them by completing
   Phase 2a.
2. Phase 2b — four parallel edits across `parser.py`, `audit.py`, `runtime.py`, `worker.py`. Run `pytest -q` after
   each; the suite will fail until Phase 2c completes.
3. Phase 2c — six parallel test edits. Run `pytest -q` afterward; expect green except for `test_operator_stop*`.
4. Phase 2d — migrate the two 003 plain-text tests to `/cancel`. Run `pytest -q`; expect full green.
5. Phase 2e — validation gate.
6. Phase 3 → Phase 4 → Phase 5 — add three regression tests in priority order, run each as it lands.
7. Phase 6 — grep checks, manual quickstart, final pytest, CLAUDE.md sanity.

### MVP scope

Phase 2 + Phase 3 alone constitutes the MVP: deprecated alias machinery gone, `/done` rejection guaranteed by a
locked-in regression test. US2 and US3 are quality lock-ins that can be skipped only if time-pressured (not
recommended — they protect against silent regressions in a path that runs without operator visibility).

---

## Notes

- This feature is **deletion-dominant**. Most tasks remove code/tests; only three tasks add code (regression tests
  T022, T024, T026).
- Keep deletions narrow per task — do not opportunistically refactor unrelated code while editing
  `dispatcher.py`/`runtime.py`/`worker.py`. Focus on the listed symbols only.
- Verify SC-001 (`grep` for any of the six removed symbols returns 0 hits in `src/`) before opening the PR.
- Commit per phase boundary (Phase 2a, 2b+2c+2d together, 2e gate, each story phase, Polish) for clean review.
