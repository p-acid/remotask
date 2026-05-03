# Tasks: Agent SDK Integration

**Input**: Design documents from `/specs/007-agent-sdk-integration/`
**Prerequisites**: plan.md, spec.md (US1/US2/US3), research.md (R1~R10), data-model.md, contracts/sdk-worker-protocol.md, quickstart.md

**Tests**: Spec FR-016, FR-017, FR-018에 의해 명시적으로 요구됨. test 작업 포함.

**Organization**: User story 단위 (US1 P1 → US2 P2 → US3 P3) + 헌법 §VI 회귀 / FR-018 / Polish.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 동일 파일을 건드리지 않고 의존성이 없을 때 병렬 가능.
- **[Story]**: US1/US2/US3 — Setup/Foundational/Polish 단계는 라벨 없음.
- 모든 task에 절대 또는 repo-relative 파일 경로를 명시한다.

## Path Conventions (per plan.md)

- 코드: `src/remotask/agent/`, `src/remotask/daemon/`
- 테스트: `tests/integration/`, `tests/unit/`, `tests/fakes/`

---

## Phase 1: Setup

신규 레포 초기화는 없음. 기존 레포에 코드 추가만 수행.

- [X] T001 Verify `claude-agent-sdk>=0.1` is already declared in `/Users/samuel/Developments/remotask/pyproject.toml` and `uv sync` succeeds locally.

---

## Phase 2: Foundational (blocks all stories)

stdout protocol 확장과 audit 상수 추가가 모든 스토리의 전제다. 여기 끝나기 전에는 US1/US2/US3 어떤 것도 시작하지 않는다.

- [X] T002 Add `EV_AGENT_TURN: Final = "agent.turn"` constant to `src/remotask/daemon/audit.py` near existing `EV_WORKER_*` constants.
- [X] T003 Extend `src/remotask/daemon/worker.py`: add module-level regexes `_STEP_RE = re.compile(r"^STEP (.{1,500})$")` and `_EVENT_RE = re.compile(r"^EVENT ([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*) (.+)$")` next to the existing `_PR_URL_RE` / `_PROGRESS_RE` / `_FINAL_RE` block. Keep existing regexes unchanged.
- [X] T004 In `src/remotask/daemon/worker.py::_stream_subprocess_output`, after the existing `FINAL` branch, add a `STEP` branch that calls `topic.format_progress(spec.issue_key, body)` and posts via the same `topic.post_to_topic` chokepoint used by `_on_progress`. Reuse the `progress_handler` injection pattern (introduce a sibling `step_handler` parameter) to keep the streaming function pure.
- [X] T005 In `src/remotask/daemon/worker.py::_stream_subprocess_output`, after the new `STEP` branch, add an `EVENT` branch that decodes the JSON payload and calls a new `event_handler(type, payload_dict)`. Unknown types and JSON parse errors land in log-only path with a `worker.event.malformed` warning.
- [X] T006 In `src/remotask/daemon/worker.py::run_worker`, register two new handlers: `_on_step(body) -> post_to_topic(format_progress(issue_key, body))` and `_on_event(type, payload) -> audit.record_event(conn, session_id=spec.session_id, type=type, payload=payload)` for known agent.* types only.
- [X] T007 [P] Extend `tests/fakes/fake_agent.py`: add a `step_then_pr` mode that emits one `STEP did_a_thing` line and one `EVENT agent.tool_use {"tool":"Bash","iter":1}` line followed by the existing `PR_URL=` + `FINAL 1 natural`. This gives us a deterministic fixture for the new line shapes without needing the real SDK.
- [X] T008 [P] Add `tests/unit/test_step_event_parsers.py`: assert `_STEP_RE` and `_EVENT_RE` from `worker.py` accept canonical shapes, reject malformed shapes (length > 500 for STEP, malformed type for EVENT, non-JSON payload), and that the priority ordering (`PR_URL` > `PROGRESS` > `FINAL` > `STEP` > `EVENT` > log-only) is preserved by inspecting the matcher dispatch table.
- [X] T009 Add `tests/integration/test_step_event_pipeline.py`: spawn `fake_agent` in `step_then_pr` mode through the existing daemon-side `run_worker` harness; assert the topic receives the STEP body line (with `[<key>]` prefix) AND the `agent.tool_use` row lands in `session_events`. This is the single foundational integration test — DO NOT proceed to Phase 3 until it passes.

---

## Phase 3: User Story 1 — `/run` makes a real Draft PR (Priority: P1) 🎯 MVP

**Goal**: 운영자가 `/run <Jira-key>`를 보내면 daemon이 진짜 `claude-agent-sdk` driver를 spawn하고, driver가 작업 후 첫 commit + push를 만들면 토픽에 `[<key>] Draft PR opened: <url>` 라인이 도착한다.

**Independent Test**: 운영자 머신에서 작은 작업(파일 1개 수정 + 1 commit)을 트리거. 30초 이내 PR URL 라인 도착 확인 + `sessions.pr_url` DB 컬럼 채워짐 확인.

### Implementation for US1

- [X] T010 [US1] Create `src/remotask/agent/sdk_worker.py` skeleton: module docstring, `__main__` entrypoint, env var read (`REMOTASK_ISSUE_KEY`, `REMOTASK_SESSION_ID`), `ClaudeAgentOptions(permission_mode="bypassPermissions", system_prompt={"type":"preset","preset":"claude_code"})`, async `main()` that opens `ClaudeSDKClient`, sends initial prompt `f"/work-start {issue_key}"`, drains the message stream until Stop, then exits 0.
- [X] T011 [US1] In `src/remotask/agent/sdk_worker.py`, add an assistant-message scanner: as messages flow through `client.receive_messages()`, run `re.search(r"PR_URL=(\S+)", text)` over each assistant text block; the FIRST match is captured and emitted to stdout as exactly `PR_URL=<url>\n` followed by `sys.stdout.flush()`. Do not emit a second time even if more matches appear.
- [X] T012 [US1] In `src/remotask/agent/sdk_worker.py`, add a `Stop` HookMatcher whose callback emits `EVENT agent.stop {"iter":<i>,"reason":"natural"}` and then `FINAL <iter> natural\n` (in that order, both flushed) before returning a no-op `HookJSONOutput`. The driver's main task awaits the SDK to finish then exits with code 0.
- [X] T013 [US1] In `src/remotask/daemon/worker.py::_default_worker_argv`, change the default argv from `remotask.agent.demo_worker` to `remotask.agent.sdk_worker`. Keep `demo_worker` importable so existing 003-style direct-invocation tests can still target it explicitly via `WorkerSpec.argv`.

### Tests for US1

- [X] T014 [US1] Add `tests/integration/test_sdk_worker_initial_prompt.py`: instantiate `sdk_worker` with a stubbed `claude_agent_sdk.Transport` (custom `Transport` injected via `ClaudeSDKClient(options, transport=stub)`); assert the FIRST `query()` payload is exactly `{"type":"user","message":{"role":"user","content":"/work-start ZXTL-1234"},...}`. Use `REMOTASK_ISSUE_KEY=ZXTL-1234` env injection.
- [X] T015 [US1] Add `tests/integration/test_sdk_worker_pr_url.py`: with the stubbed Transport, push an assistant message containing `Created PR_URL=https://github.com/x/y/pull/42 successfully` followed by a Stop event; assert the driver's stdout contains exactly one `PR_URL=https://github.com/x/y/pull/42` line, exactly one `FINAL 1 natural` line, exit code 0.
- [X] T016 [US1] Extend `tests/integration/test_step_event_pipeline.py` with a second case driving the **real** `sdk_worker` module via the stubbed Transport through the daemon `run_worker` orchestrator (not the fake_agent). Assert `sessions.status == 'pr_created'` and `pr_url == 'https://github.com/x/y/pull/42'` after the worker exits, and that the topic received the `Draft PR opened:` line with `[<key>]` prefix.

**Checkpoint**: T009 passes (Phase 2) AND T014/T015/T016 pass. MVP slice deliverable to operator.

---

## Phase 4: User Story 2 — Per-tool PROGRESS visibility (Priority: P2)

**Goal**: PostToolUse 훅마다 사람이 읽을 STEP 라인이 토픽에 게시되고, 동일 의미 EVENT 행이 `session_events`에 적재된다. 동일 카테고리 1초 throttle (R9).

**Independent Test**: 작은 작업이 도구 N개를 호출할 때, 토픽에 ≥1개의 STEP 라인 도착 + `session_events`에 N개의 `agent.tool_use` 행 + 동일 카테고리 1초 내 연속 발생 시 토픽 게시 1번으로 합쳐짐.

### Implementation for US2

- [X] T017 [US2] In `src/remotask/agent/sdk_worker.py`, add an integer counter `_iter` (module-local) that increments on each PostToolUse hook invocation.
- [X] T018 [US2] In `src/remotask/agent/sdk_worker.py`, add a `PostToolUse` HookMatcher that ALWAYS emits `EVENT agent.tool_use {"tool":<name>,"iter":<iter>}` to stdout (no throttle on EVENT — full audit trail).
- [X] T019 [US2] In the same `PostToolUse` matcher, add a per-tool throttle map `_last_step_emit: dict[str, float]` so a STEP line is emitted at most once per second per tool name. The STEP body format is `<tool_name>: <succinct one-line summary>` truncated to 500 chars; the summary is derived from `tool_input` (Bash → first 80 chars of command; Edit → file_path; Read → file_path; default → tool_name only).
- [X] T020 [US2] In `src/remotask/agent/sdk_worker.py`, add a sibling `PostToolUse` (failure) handler that emits `EVENT agent.tool_result {"tool":<name>,"iter":<iter>,"is_error":true}` so the daemon-side `agent.tool_result` row in `session_events` reflects failures (per data-model.md).

### Tests for US2

- [X] T021 [US2] Add `tests/unit/test_sdk_worker_throttle.py`: drive the throttle map directly (no SDK), feed it 5 PostToolUse events for tool=`Read` within 200ms; assert exactly 1 STEP emit and 5 EVENT emits.
- [X] T022 [US2] Extend `tests/integration/test_step_event_pipeline.py` with a third case where the stubbed Transport synthesizes 3 PostToolUse events (different tools) followed by Stop; assert daemon-side topic receives 3 STEP lines AND `session_events` table holds 3 `agent.tool_use` rows.
- [X] T023 [US2] [P] Extend `tests/integration/test_step_event_pipeline.py` with a fourth case where the stubbed Transport synthesizes a tool_input that produces an error result; assert `agent.tool_result` row has `is_error: true` payload.

**Checkpoint**: US1 + US2 deliver the full happy-path observability story.

---

## Phase 5: User Story 3 — `/cancel` cooperative interrupt (Priority: P3)

**Goal**: 같은 토픽에서 `/cancel` 한 번이면 daemon이 SIGUSR1을 driver process group에 보내고, driver는 `client.interrupt()`를 호출해 graceful 종료. 003 ladder 그대로 (SIGUSR1 → grace → SIGTERM → SIGKILL). 부분 진행 commit은 worktree에 보존.

**Independent Test**: 길게 도는 작업 트리거 직후 `/cancel`. session 상태 `canceled`, error_message `operator_stop`, 도중 발생한 commit 보존 확인.

### Implementation for US3

- [X] T024 [US3] In `src/remotask/agent/sdk_worker.py`, install a SIGUSR1 handler at startup that sets an `asyncio.Event` (call it `_interrupt_requested`). The handler does NO I/O — it only sets the event (Python signal-safety).
- [X] T025 [US3] In `src/remotask/agent/sdk_worker.py::main()`, add a watchdog task that awaits `_interrupt_requested.wait()`. Once fired: emit `EVENT agent.interrupt {"iter_at_interrupt":<iter>}` to stdout, call `await client.interrupt()`, then emit `FINAL <iter> operator_stop` and call `sys.exit(0)`. The main message loop must yield control regularly so the watchdog gets scheduled.
- [X] T026 [US3] Verify that `src/remotask/daemon/worker.py` already sends SIGUSR1 to the worker's process group as the FIRST step of the operator-stop ladder (003 behaviour). If the existing `_kill_worker_group` only sends SIGTERM/SIGKILL, add SIGUSR1 as the first signal in the cancel path (NOT in the timeout path — those remain SIGTERM/SIGKILL per 003).

### Tests for US3

- [X] T027 [US3] Add `tests/integration/test_sdk_worker_cooperative_cancel.py`: spawn `sdk_worker` (with Transport stub configured to stay in a long-running loop) as a real subprocess; daemon-side issue `os.kill(pid, signal.SIGUSR1)`; assert subprocess emits `EVENT agent.interrupt` then `FINAL <i> operator_stop` to stdout and exits 0 within 5 seconds. Assert `client.interrupt()` was called exactly once on the stub.
- [X] T028 [US3] Add a second case to `tests/integration/test_sdk_worker_cooperative_cancel.py` driving the full daemon-side `run_worker` flow: enqueue a session bound to a fake topic, set the `is_operator_stop_in_flight` callback to True after the worker emits its first STEP line, send SIGUSR1; assert `sessions.status == 'canceled'`, `sessions.error_message == 'operator_stop'`.
- [X] T029 [US3] Add a third case asserting that when the driver does NOT respond to SIGUSR1 within the grace window (simulate by patching the watchdog to ignore the event), the 003 SIGTERM → SIGKILL fallback still drives the session to `canceled` with `error_message == 'operator_stop_forced'`. This validates 003 ladder preservation.

**Checkpoint**: All three stories complete. spec FR-009 / FR-010 satisfied.

---

## Phase 6: Constitution & FR-018 regression

전체 스토리와 무관하게 항상 검증되어야 하는 invariant 회귀 테스트.

- [X] T030 [P] Add `tests/integration/test_sdk_worker_denylist.py`: instantiate `sdk_worker` with a stubbed Transport whose first PreToolUse-eligible message is a Bash tool_use with `command="git push --force"`. Assert the driver's PreToolUse hook returns a deny `HookJSONOutput` (`{"hookSpecificOutput": {"permissionDecision": "deny", ...}}`). Repeat for `git reset --hard`, `git clean -fd`, `rm -rf /tmp/abs`, `sudo whoami`. Each case must produce a deny.
- [X] T031 [P] Implement the deny-list PreToolUse hook in `src/remotask/agent/sdk_worker.py`: a callback registered via `HookMatcher(matcher="Bash", hooks=[deny_list_guard])` that inspects `input["tool_input"]["command"]` for the patterns enumerated in T030. Patterns are kept as a module-level constant `_DENY_PATTERNS: list[re.Pattern]` so future additions are localized.
- [X] T032 [P] Add `tests/integration/test_setmycommands_curated.py` (FR-018): assert that `src/remotask/telegram/commands.py` exports a curated set whose names are exactly `{"run", "cancel", "status"}` — no `work-start`, no `work-done`. Snapshot test against the actual list passed to `setMyCommands`.

---

## Phase 7: Polish

문서·아키텍처 갱신·MVP 회귀 검증.

- [X] T033 Append ARD entry D22 to `/Users/samuel/Developments/remotask/ARD.md`: `## D22 — claude-agent-sdk 실 통합 채택 (007)`. **결정**: SDK driver를 별도 subprocess로 spawn (R1), permission_mode=bypassPermissions + driver-level PreToolUse deny-list (R2), SIGUSR1 → client.interrupt() (R3), 003 stdout protocol을 STEP/EVENT 두 라인 셰이프로 super-set 확장 (R4), Draft PR 생성은 agent-side (Q1). **사유**: daemon-thin 유지 + 헌법 §VI invariant 보존 + 003 회귀 surface 최소화. **근거 spec**: `specs/007-agent-sdk-integration/`.
- [X] T034 Update `/Users/samuel/Developments/remotask/ARCHITECTURE.md` §8 feature stack table: add a row `007-agent-sdk-integration | placeholder demo_worker → real claude-agent-sdk driver, STEP/EVENT protocol, deny-list hook`. Update §2 component table to add `agent/sdk_worker.py` row alongside `agent/demo_worker.py`. Update §7 tech stack note: claude-agent-sdk is now in active production path (not placeholder).
- [X] T035 [P] Run `uv run pytest -q` from repo root; assert 003-006 regression suites pass with zero modifications and zero skips. Document the final pass/fail count in this task before marking complete.
- [X] T036 [P] Run `uv run ruff check src/ tests/` and `uv run mypy src/remotask/core/` (per CLAUDE.md dev rules). Fix any new findings introduced by 007.
- [ ] T037 Manual quickstart smoke run on the operator's machine following `specs/007-agent-sdk-integration/quickstart.md` §1 (US1 trigger) end-to-end with the operator's real `/work-start` slash skill. Document the resulting PR URL and session_id in this task before marking complete (operator-only; CI cannot reproduce).

---

## Dependency graph

```
Phase 1 (T001)
    │
    ▼
Phase 2 (T002 → T003 → T004 → T005 → T006 → T007/T008 [P] → T009)
    │
    ├──── Phase 3 US1 (T010 → T011/T012/T013 → T014/T015/T016) ──┐
    │                                                             │
    ├──── Phase 4 US2 (T017 → T018 → T019 → T020 → T021/T022/T023)┤  These three
    │                                                             │  story phases
    └──── Phase 5 US3 (T024 → T025 → T026 → T027 → T028 → T029) ──┤  may overlap
                                                                  │  in time after
    Phase 6 (T030/T031/T032 [P]) ─────────────────────────────────┤  Phase 2.
                                                                  │
    Phase 7 (T033 → T034 → T035/T036 [P] → T037) ─────────────────┘
```

After Phase 2, US1 / US2 / US3 / Phase 6 are independently parallelizable along separate file boundaries. T035/T036 must run after all code phases.

---

## Parallel opportunities

| Cluster | Tasks | Why parallel |
|---------|-------|--------------|
| Foundational tail | T007 (fake_agent), T008 (parser unit) | different files, no shared state |
| US2 tail | T022 vs T023 | both extend the same file but tests can be written in parallel and merged |
| Constitution gates | T030 / T031 / T032 | three different files; each independently verifiable |
| Polish lint | T035 / T036 | both run from CLI on completed code |

---

## MVP scope suggestion

**Phase 1 + Phase 2 + Phase 3 (US1) + Phase 7 (T035/T036/T037)**.

이 9개 테스크를 머지하면 spec SC-001(첫 PR URL 30초 내 도착) + SC-004(003-006 회귀 통과)가 만족되고 operator는 처음으로 진짜 PR을 받을 수 있다. US2/US3는 필요시 별도 PR로 분리 가능.

---

## Independent test criteria summary

- **US1**: T014 + T015 + T016 (driver + daemon 통합) — 30초 이내 PR URL 토픽 회신.
- **US2**: T021 + T022 + T023 — STEP throttle + session_events 적재.
- **US3**: T027 + T028 + T029 — SIGUSR1 cooperative + 003 ladder fallback.
- **Constitution gate**: T030 — deny-list invariant.
- **FR-018**: T032 — setMyCommands curated set unchanged.
- **003-006 회귀**: T035 — 전체 회귀 zero diff.

---

## Format validation

모든 task가 `- [ ] T### [P?] [Story?] <description with absolute or repo-relative file path>` 형식 준수 — 37/37 ✅.
