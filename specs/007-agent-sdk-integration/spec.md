# Feature Specification: Agent SDK Integration (placeholder worker → real claude-agent-sdk)

**Feature Branch**: `007-agent-sdk-integration`
**Created**: 2026-05-03
**Status**: Draft
**Input**: User description: "003에서 도입한 placeholder demo_worker를 실제 claude-agent-sdk 호출로 완전히 교체. `/run <Jira-key>` 한 번으로 실제 코드가 작성되고 Draft PR 링크가 토픽에 도착하는 흐름을 처음으로 end-to-end 검증한다. 005 [<issue_key>] prefix·`/cancel` 캐노니컬·forum-topic 격리는 보존. 003 cooperative termination ladder 보존. Jira fetch / Pro·Max backoff / 새 슬래시 / 스키마·헌법 변경은 모두 out-of-scope."

## Clarifications

### Session 2026-05-03

- Q: GitHub Draft PR을 만드는 책임은 daemon-side와 agent-side 중 어디인가? → A: Agent-side. 에이전트의 슬래시 스킬 안에서 PR을 생성하고 그 URL을 daemon에게 이벤트/stdout으로 전달한다. daemon은 GitHub API 자격증명을 보유하지 않고 `[KEY]` chokepoint로 URL을 토픽에 회신만 한다. 어떤 슬래시 스킬이 PR 생성을 담당할지는 운영자의 스킬 설계 자유에 맡긴다 — `/work-start` 안에 묶을 수도, 별도 PR 전용 스킬을 도입할 수도, 기존 `/work-start`를 개선해 책임을 흡수할 수도 있다.
- Q: 에이전트의 도구 권한 정책의 실제 범위는 (`acceptEdits`만 vs 전 도구 자동 승인 vs 명시적 allowlist)? → A: 전 도구 자동 승인 (bypassPermissions 동치). 파일 편집·bash·SDK가 노출하는 모든 도구가 per-tool prompt 없이 실행된다. 안전 책임은 worktree 격리와 운영자 본인의 슬래시 스킬 설계로 이동한다 (헤드리스 운영의 필수 조건이며 spec FR-004에 명시).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — `/run`이 진짜 Draft PR을 만들어 토픽에 회신 (Priority: P1)

운영자는 휴대폰 Telegram에서 `/run ZXTL-1234`를 보낸다. daemon은 worktree를 만들고 그 안에서 실제 Claude Code 작업을 수행하는 에이전트를 spawn한다. 에이전트가 작업을 완료하고 첫 commit을 푸시하면, 같은 forum topic에 `[ZXTL-1234] Draft PR opened: <url>` 메시지로 PR 링크가 회신된다. 운영자는 그 링크를 GitHub 모바일 앱에서 열어 머지 여부를 결정한다.

**Why this priority**: PRD §5의 MVP 핵심 가치 ("원격 트리거 → PR")를 처음으로 실증하는 마지막 퍼즐 조각. 003~006은 격리·제어 평면을 갖췄으나 워커가 placeholder였기 때문에 사용자에게 실 가치가 전달되지 않았다. 이 스토리가 들어와야 remotask의 존재 이유가 검증된다.

**Independent Test**: 운영자 머신에서 daemon을 띄우고, fake가 아닌 실제 claude-agent-sdk(stub harness 또는 secret이 주입된 실 SDK)로 `/run <Jira-key>`를 보낸다. 같은 토픽에 `[<key>] Draft PR opened: <url>` 메시지가 도착하는지 확인하고, 그 URL을 열어 변경된 파일이 실제 commit으로 보존되어 있는지 확인한다.

**Acceptance Scenarios**:

1. **Given** 화이트리스트 운영자가 forum group에 있고, daemon이 running 상태이고, 매핑된 프로젝트 repo가 있고, `agent.max_concurrent ≥ 1`이며, `claude` CLI OAuth credential이 사용자 머신에 유효하게 설치되어 있을 때, **When** 운영자가 `/run ZXTL-1234`를 보내면, **Then** daemon은 새 forum topic을 생성하고 그 안에 `[ZXTL-1234] Status: starting` → `[ZXTL-1234] Status: running` PROGRESS를 차례로 게시한 뒤, 에이전트가 첫 commit을 푸시하면 `[ZXTL-1234] Draft PR opened: https://github.com/<owner>/<repo>/pull/<n>` 형식의 URL 회신을 게시한다.
2. **Given** 위 흐름이 시작된 상태에서, **When** 에이전트가 `/work-done` 슬래시 스킬로 작업 종료를 선언하면, **Then** session 상태는 `pr_created → completed`로 전이되고 `[ZXTL-1234] Status: completed` 종료 라인이 토픽에 게시된다.
3. **Given** 에이전트가 commit 없이 종료한 경우(scope 무효, 작업 불필요 판단 등), **When** `/work-done`이 호출되면, **Then** session 상태는 `running → completed`로 전이되고 토픽에는 PR URL 없이 종료 라인만 게시된다.

---

### User Story 2 — 진행 상황을 토픽에서 실시간 관찰 (Priority: P2)

운영자는 트리거 후 휴대폰을 보고 있을 때 에이전트가 어떤 단계에 있는지 — 어떤 도구를 썼는지, 어느 파일을 편집했는지 — 사람이 읽을 수 있는 한 줄로 토픽에서 본다. daemon은 같은 진행 이벤트를 구조화 형태로 audit 데이터(`session_events`)에 기록하여 사후 추적이 가능하도록 한다.

**Why this priority**: 운영자가 "지금 뭐 하고 있나"를 보지 못하면 신뢰가 형성되지 않고 `/cancel`을 너무 일찍 누르거나 너무 늦게 누른다. 헌법 §VII("관측 가능성") 정합. P1보다 한 단계 낮은 이유는 P1만으로도 가치 입증은 가능하되 (PR이 도착하기만 하면 됨), 신뢰성·실용성을 위해 곧바로 필요한 보완이라서다.

**Independent Test**: 에이전트가 파일 1~2개를 편집하고 1~2회 bash를 실행하는 작은 작업을 수행할 때, 토픽에 그 단계별 PROGRESS 라인이 sub-30초 latency로 도착하는지 확인하고, 동일 정보가 `session_events`에 turn-by-turn 행으로 적재되는지를 SQL로 확인한다.

**Acceptance Scenarios**:

1. **Given** running 상태의 세션에서 에이전트가 파일 편집 도구를 호출했을 때, **When** 도구 실행이 완료되면, **Then** 30초 이내에 `[<key>] <human-readable progress line>` 형식의 메시지가 토픽에 게시되고, 동일 의미의 이벤트가 `session_events` 테이블에 한 행 추가된다.
2. **Given** 에이전트가 같은 turn 안에서 여러 도구를 연속 호출할 때, **When** 각 도구가 끝날 때마다, **Then** PROGRESS 라인은 도구별로 1줄씩 게시되되 동일 종류 라인이 1초 미만 간격으로 폭주할 때는 합리적으로 묶이거나 정해진 양식대로만 회신된다 (토픽이 1줄짜리 spam으로 채워지지 않는다).
3. **Given** 에이전트가 turn 사이에 멈출 때(LLM 응답 대기 등), **When** 그 대기 구간이 길어져도, **Then** 토픽은 마지막 PROGRESS 라인 그대로 유지되며 false-positive "stuck" 메시지를 자동으로 만들지 않는다.

---

### User Story 3 — `/cancel`이 진짜 에이전트를 cooperative하게 중단 (Priority: P3)

운영자는 작업이 잘못된 방향으로 가고 있다고 판단하면 같은 토픽에서 `/cancel`을 보낸다. daemon은 003에서 정의된 종료 ladder(SIGUSR1 → grace → SIGTERM → SIGKILL)를 그대로 적용하되, 이번 feature에서는 그 대상이 placeholder가 아니라 실제 claude-agent-sdk 기반 subprocess가 된다. 가능하면 에이전트가 부분 진행분(이미 만든 commit 등)을 잃지 않은 채 graceful하게 종료된다.

**Why this priority**: 005에서 운영자에게 단일 종료 명령(`/cancel`) 세만틱을 약속했으므로 실제 에이전트로 바뀐 후에도 그 약속이 깨지지 않아야 한다. P1·P2 흐름이 동작한 뒤에 검증해도 충분히 늦지 않다는 점에서 P3.

**Independent Test**: 에이전트가 길게 도는 작업을 시작한 직후 `/cancel`을 보낸다. 토픽에 cancellation 안내가 게시되고 grace window 내에 session 상태가 `canceled`로 전이되는지 확인한다. worktree에 이미 만들어진 commit은 보존되어 있어야 한다.

**Acceptance Scenarios**:

1. **Given** running 상태의 실제 에이전트 세션에서, **When** 운영자가 같은 토픽에서 `/cancel`을 보내면, **Then** daemon은 005 캐노니컬 흐름대로 `REASON_MAIN_CHAT_CANCEL`로 종료를 시도하고 grace window 내에 에이전트가 cooperative interrupt에 응답해 graceful하게 종료한다.
2. **Given** grace window가 만료되었음에도 에이전트가 종료하지 않은 경우, **When** SIGTERM이 그 다음 단계로 전달되어도 종료되지 않으면, **Then** 003 ladder대로 SIGKILL이 마지막 단계에서 전달되고 session은 `canceled`로 전이된다 (외부 강제 종료라도 finalization은 보장).
3. **Given** 에이전트가 cooperative interrupt에 응답해 graceful하게 종료하고 그 시점까지 1개 이상의 commit이 worktree에 만들어져 있던 경우, **When** session이 `canceled`로 전이되더라도, **Then** 그 commit은 worktree에 보존되며 운영자가 사후에 worktree에서 수동 검토할 수 있다 (canceled 세션은 Draft PR을 자동 생성하지 않는다).

---

### Edge Cases

- 트리거된 worktree에 GitHub remote가 설정되어 있지 않거나 push 권한이 없으면? → 에이전트가 push 실패를 감지하고 PROGRESS로 회신한 뒤 `failed` 전이. PR URL은 게시되지 않는다.
- 에이전트가 첫 commit을 만들기 전에 `/work-done`을 호출했을 때 → no-PR completion (US1.3 시나리오와 동치).
- 에이전트가 `/work-start` 응답에서 곧바로 "이 작업은 이미 완료됨" 판단을 내려 작업 자체를 수행하지 않을 때 → 즉시 `/work-done` 호출, no-PR completion.
- 동일 issue_key로 이미 활성 세션이 있는 상태에서 `/run`이 다시 들어왔을 때 → 003/006의 거부 정책 그대로(거부 + 안내 + audit). 변경 없음.
- 에이전트가 cooperative interrupt에 즉시 응답하지 않고 partial state를 남긴 채 SIGKILL로 죽었을 때 → worktree와 commit은 디스크에 남고 session은 `canceled`. 다음 트리거에서 같은 worktree 경로 충돌이 없도록 정리 정책은 003 그대로.
- Pro/Max 사용량 한도가 작업 중 초과되어 SDK가 응답을 거부할 때 → 이번 feature에서는 그대로 `failed` 전이로 처리. backoff·재시도는 Phase 4로 연기 (Assumptions 참조).
- GitHub Draft PR 생성 API가 일시적 5xx를 반환할 때 → 에이전트가 자체 재시도 정책을 적용하고 최종 실패 시 `failed` 전이 + 사람이 읽을 수 있는 사유 PROGRESS 라인. (daemon은 PR 생성을 직접 시도하지 않으므로 daemon-side retry는 존재하지 않는다.)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST replace the placeholder demo worker introduced in 003 with a real claude-agent-sdk-based worker for all non-test trigger paths. Tests continue to use the existing fake_agent fixture (FR-016).
- **FR-002**: When `/run <issue-key>` is accepted, daemon MUST create the per-session git worktree (existing 003 behavior) and spawn the real agent subprocess with that worktree as its working directory.
- **FR-003**: The agent MUST be invoked with an initial prompt that begins the operator's existing `/work-start <issue_key>` slash skill — the issue key is passed verbatim from the trigger so the skill receives the correct Jira context.
- **FR-004**: The agent's tool-permission policy MUST auto-accept ALL tool invocations for the duration of the session — file edits, bash, and any other tool the SDK exposes — with no per-tool human prompt. This is a precondition for headless operation; safety relies on worktree isolation and the operator's own slash-skill design rather than per-tool confirmation gates.
- **FR-005**: Draft PR creation MUST be performed agent-side — i.e., from inside one of the agent's own slash skills (whether `/work-start`, an enhanced version of it, or a dedicated PR-creation skill is the operator's design choice). Daemon MUST NOT call the GitHub API directly and MUST NOT hold GitHub credentials for this feature; daemon's only role in the PR flow is receiving the URL the agent emits and posting it.
- **FR-006**: Once the agent emits the Draft PR URL through its event channel (SDK event or stdout), daemon MUST post the URL to the same forum topic via the existing `[<issue_key>] Draft PR opened: <url>` template, going through the `format_progress` chokepoint introduced in 005. No new direct topic-send paths are added for this case.
- **FR-007**: Per-turn agent activity (tool invocations, tool results, agent stop events) MUST be observable to daemon as structured events. Daemon MUST translate each such event into both (a) a human-readable PROGRESS line on the topic with `[<issue_key>]` prefix, and (b) one row in `session_events`.
- **FR-008**: The agent MUST conclude work with the operator's existing `/work-done` slash skill, which causes daemon to observe a final completion signal and transition the session to `completed` (or `pr_created → completed` if a PR was created).
- **FR-009**: The 003 cooperative termination ladder MUST remain unchanged from the operator's perspective: `/cancel` → SIGUSR1 → operator_stop_grace_seconds → SIGTERM → 5s → SIGKILL. Daemon MUST first attempt cooperative interrupt; only escalate when the agent fails to terminate inside the grace window.
- **FR-010**: System MUST ensure the agent receives the cooperative interrupt in a way that allows it to flush in-flight tool calls or pending commits before exiting. If the SDK's process-signal handling does not provide this guarantee, system MUST additionally use the SDK's in-process cancel mechanism alongside the signal.
- **FR-011**: The 005 `[<issue_key>]` prefix chokepoint MUST be preserved: every session-bound outbound message — including PROGRESS, status, PR-opened, and termination notifications — passes through `topic.format_progress(issue_key, body)`. No new direct topic-send paths are added.
- **FR-012**: The 005 `/cancel` canonical, `REASON_MAIN_CHAT_CANCEL`, and the curated `setMyCommands` set `{run, cancel, status}` MUST remain unchanged. No new Telegram slash commands are introduced.
- **FR-013**: The forum-topic isolation model (1 session = 1 topic, presentation-layer per ARD D19) MUST remain unchanged.
- **FR-014**: The `sessions.status` state machine MUST remain unchanged from 003: `enqueued → starting → running → {pr_created → completed | completed | canceled | failed}`. No new states are added.
- **FR-015**: The `sessions / session_events / projects / locks` SQLite schema (V0001) MUST remain unchanged. No new tables, columns, or indexes are introduced. Per-turn agent events are stored using existing `session_events` columns.
- **FR-016**: `tests/fakes/fake_agent.py` MUST be retained as the integration-test stand-in. All integration tests for 003/004/005/006 — including `test_cancel_canonical`, `test_key_prefix`, `test_operator_stop`, `test_operator_stop_forced`, `test_done_command_removed`, `test_plain_termination_dead`, and the existing worker-lifecycle tests — MUST continue to pass against `fake_agent` without modification of their assertions, with at most the worker-spawn shim updated.
- **FR-017**: System MUST add new tests that, against a stubbed/mocked SDK harness (no real claude API call), verify: (a) the agent is started with an initial prompt of the form `/work-start <issue-key>`; (b) when the SDK signals first-commit / PR-open through its event stream, daemon posts the URL to the topic with the `[<issue_key>]` prefix; (c) `/cancel` causes the SDK to receive cooperative interrupt and the session transitions to `canceled` within the grace window without losing already-made commits.
- **FR-018**: System MUST add a regression test asserting the curated `setMyCommands` set is still `{run, cancel, status}` (no new entry for this feature) and that `/work-start` and `/work-done` are NOT registered with Telegram (they are agent-side skills, not Telegram operator commands).
- **FR-019**: When the agent terminates with a non-zero exit code or the SDK reports an unrecoverable error, session MUST transition to `failed` (not `completed`) and a human-readable failure reason MUST be posted to the topic with the `[<issue_key>]` prefix.
- **FR-020**: When the agent terminates after producing one or more commits but before invoking `/work-done` (e.g., crash, OOM), session MUST transition to `failed`, NOT `pr_created` — Draft PR creation is gated on the `/work-done` completion signal, not on commit-presence alone, to avoid publishing PRs the agent itself considered incomplete.

### Key Entities *(include if feature involves data)*

- **Session**: existing entity from 001/002. Status field gains no new values; transitions are now driven by agent-emitted lifecycle events instead of placeholder timers.
- **Session Event** (`session_events` row): existing entity from 002. Each agent tool invocation and stop signal becomes one row; the event-type strings used here are additive (no schema change).
- **Worktree**: existing per-issue git worktree from 003. Now actually mutated by the real agent rather than left as a no-op stage.
- **Agent Subprocess**: a per-session child process running claude-agent-sdk against the operator's installed `claude` OAuth credential. Lifecycle is bound to the session; its structured event channel is daemon's source of truth for PROGRESS and FINAL transitions.
- **Draft Pull Request** (external GitHub resource): created against the session branch when the agent's first commit reaches the remote. URL is the value posted to the topic.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a small representative task (1–2 file edits, 1 commit), at least 90% of `/run` triggers result in a Draft PR URL being posted to the corresponding topic within 30 seconds of the agent's first push to the remote, measured across at least 10 invocations.
- **SC-002**: For the same representative task, at least one human-readable PROGRESS line is posted to the topic within 30 seconds of each agent tool invocation, with no PROGRESS line being a placeholder string (e.g. no `Status: …`-only lines unless they reflect real lifecycle transitions).
- **SC-003**: Cooperative cancel succeeds — i.e., the session reaches `canceled` while the agent's process exited via cooperative interrupt rather than SIGTERM/SIGKILL — for at least 80% of `/cancel` invocations under the configured grace window, measured across at least 10 cancellations on tasks that have run for at least 5 seconds.
- **SC-004**: The full 003/004/005/006 regression test suite continues to pass at 100% against `fake_agent` (no test removed or weakened).
- **SC-005**: For at least 5 distinct end-to-end runs of a representative task on the operator's machine, the resulting Draft PR is mergeable from the GitHub mobile app without further local edits — i.e., the agent produced a self-contained change set, not one that depends on out-of-band local fixup.

## Assumptions

- The operator already has a working `claude` CLI OAuth credential installed on the daemon host (Pro or Max subscription, per ARD D5). No separate API key is provisioned by this feature.
- The operator has the `/work-start` and `/work-done` slash skills already available in their personal Claude environment so the agent can invoke them. Provisioning, evolving, or splitting these skills (e.g., adding a dedicated Draft-PR-creation skill, or absorbing PR creation into an enhanced `/work-start`) is the operator's responsibility and lives in their own user-config — out of scope for this feature.
- Each project repo's GitHub remote MUST be reachable from the agent's tool environment with credentials that can create Draft PRs (e.g., a `gh` CLI session, a `GITHUB_TOKEN` env var, or an equivalent setup the agent's skills assume). daemon does not provision or rotate these credentials for this feature.
- Each project repo registered via `remotask projects add` already has a configured GitHub remote with push permission for the operator's credentials (ARD D7).
- The agent itself (via its skills) is responsible for fetching any Jira ticket context it needs from the issue key passed in. Daemon does not pre-fetch Jira data in this feature — that work is deferred to a future feature 008 candidate (Jira context fetch).
- Pro/Max usage-cap enforcement: when the limit is hit mid-session, this feature treats it as a `failed` terminal state. Backoff, retry, and queue-pause logic are deferred to Phase 4 operational hardening.
- Constitution stays at v1.1.0; no amendment is part of this feature. The new architectural decision (D22 — real claude-agent-sdk integration with `/work-start` + `/work-done` flow and acceptEdits permission) is recorded in ARD as an additive entry, not as a constitutional change.
- Database schema stays at V0001; no migration is part of this feature.
