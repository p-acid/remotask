# Phase 0 Research — Agent SDK Integration

10개 기술 결정. clarify 단계에서 plan-level로 deferred된 3건(daemon-restart 회복, FINAL 검출, PROGRESS rate-limit)은 R7/R8/R9에서 해결.

---

## R1 — Worker driver 위치: in-daemon vs subprocess

**Decision**: **별도 subprocess** (`python -m remotask.agent.sdk_worker`). daemon이 spawn하는 자식 프로세스이며, 003 demo_worker가 차지하던 위치를 그대로 대체.

**Rationale**:
- daemon-side worker.py의 process-group 종료 ladder, stdout 스트리밍, 상태 전이 wiring을 그대로 재사용 — 회귀 위험 최소화.
- 헌법 §II "daemon-centric" 정합 (daemon이 spawn·관리·종료의 SoT).
- 단일 daemon 프로세스 안에 SDK를 import하면 한 세션의 SDK 오류·OOM이 daemon 전체를 죽일 수 있다. subprocess 격리가 안전.
- `claude-agent-sdk`의 `ClaudeSDKClient`는 자체적으로 `claude` CLI를 spawn하므로 어차피 별도 프로세스 트리가 발생 — 한 단계 더 격리한들 비용은 무시 가능.

**Alternatives considered**:
- daemon 내부 asyncio task로 SDK 호출 — daemon-fault 격리 약화, 종료 ladder 재설계 필요. 거부.

---

## R2 — Permission policy

**Decision**: `permission_mode="bypassPermissions"` + driver-level `PreToolUse` 훅으로 **헌법 §VI deny-list 강제**.

**Rationale**:
- spec Q2 결정: 헤드리스 운영을 위해 모든 도구 자동 승인 필요.
- `bypassPermissions`는 SDK가 노출하는 캐노니컬 모드 (`PermissionMode = Literal["default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"]`).
- 헌법 §VI deny-list(`git push --force` / `git reset --hard` / `git clean -fd` / `rm -rf <abs>` / `sudo *`)는 SDK의 `bypassPermissions`로 비활성화되지만, **SDK의 `PreToolUse` 훅은 permission_mode와 독립적으로 호출**되며 `{"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": "..."}}`로 차단 가능.
- 결과: spec FR-004 만족 + 헌법 §VI invariant 유지 → Constitution Check waiver 불필요.

**Alternatives considered**:
- `acceptEdits`만 사용 — bash 도구가 매번 prompt → 헤드리스 흐름 자체 불가. 거부.
- daemon-side bash sandbox(seccomp 등) — 1인용 도구에 과한 인프라. 거부.

---

## R3 — Cooperative interrupt mechanism

**Decision**: SIGUSR1 핸들러를 driver 프로세스에 등록한다. 신호 수신 시 핸들러는 단순히 asyncio Event를 set하고, main task가 그 Event를 보면 `await client.interrupt()`를 호출 → 이후 driver는 `FINAL <i> operator_stop` 라인을 emit하고 정상 exit(0)한다.

**Rationale**:
- 003 cooperative ladder(SIGUSR1 → grace → SIGTERM → SIGKILL)를 그대로 재사용. daemon-side worker.py 변경 없음.
- `ClaudeSDKClient.interrupt()`는 streaming 모드 전용이며 in-flight tool 호출을 graceful하게 중단한다.
- Python signal-safety: 핸들러 안에서는 I/O를 하지 않고 Event만 set; interrupt() 호출은 main async loop에서 수행. 표준 패턴.
- worker.py의 기존 in-flight 플래그 + FINAL 라인 우선 정책(`final_reason == "operator_stop" → canceled`)이 그대로 적용된다.

**Alternatives considered**:
- 신호 없이 SDK control 채널만 — daemon-side runtime이 ladder를 신호로 강제하므로 적합하지 않음. 거부.
- SIGTERM에서도 graceful interrupt — 003 ladder의 의미를 흐림(grace expired = forced kill). 거부.

---

## R4 — Stdout protocol 확장

**Decision**: 003 contract을 **super-set**으로 확장. 기존 `PR_URL=` / `PROGRESS i/N ts` / `FINAL i reason`은 그대로 두고, 두 라인 셰이프를 추가:
- `STEP <body>`  (body: 200자 이내, 줄바꿈 없음). PostToolUse 등에서 사람이 읽을 progress 라인.
- `EVENT <type> <json>` (type: bareword, json: 단일 라인 JSON). per-turn audit 이벤트.

daemon-side worker.py는 두 정규식(`_STEP_RE`, `_EVENT_RE`)을 추가하고, STEP은 `format_progress(issue_key, body)`를 통해 토픽 전송, EVENT는 `audit.record_event(type=..., payload=...)`로 `session_events`에 적재한다. 매치되지 않는 라인은 기존대로 log-only.

**Rationale**:
- 003 contract을 깨지 않으므로 fake_agent + 003-006 회귀 테스트 100% 보존.
- 사람이 읽는 PROGRESS와 기계가 읽는 EVENT를 분리해서 토픽이 audit 이벤트 spam으로 채워지지 않게 한다.
- iteration 번호가 의미 없는 실 에이전트 워크로드에 003 PROGRESS의 `i/N` 셰이프를 강제하지 않아도 됨.

**Alternatives considered**:
- 기존 PROGRESS 그대로 사용하고 N=∞ 센티넬 — 가독성 나쁨, 003 grammar 위반. 거부.
- 라인 셰이프 대신 stderr JSON 채널 — daemon-side worker.py가 stdout/stderr 둘 다 파싱해야 함, 복잡도 증가. 거부.

---

## R5 — Initial prompt format

**Decision**: 첫 사용자 메시지로 **literal text** `/work-start <issue_key>`를 보낸다. driver는 `REMOTASK_ISSUE_KEY` 환경변수를 받아 그 값을 그대로 삽입한다. system prompt는 `{"type": "preset", "preset": "claude_code"}` (claude-agent-sdk 기본값) 그대로 — 운영자의 슬래시 스킬은 personal `~/.claude` 환경에서 자동 로드된다.

**Rationale**:
- 운영자가 이미 보유한 `/work-start` 스킬을 그대로 사용 (spec Assumptions, Q1 결정과 정합).
- 스킬을 personal `~/.claude/skills/`에 두면 SDK가 알아서 로드하므로 driver는 텍스트만 전달하면 됨.
- 단순성 — driver는 message routing만 하고 skill orchestration은 사용자 책임으로 격리.

**Alternatives considered**:
- 시스템 프롬프트에 issue_key를 박는다 — `/work-start` 스킬 디자인을 driver가 알아야 함. 거부.
- 구조화된 input(JSON) — `query()`는 string 또는 AsyncIterable[dict] 둘 다 받지만 슬래시 스킬은 string user message가 가장 자연스러움. 거부.

---

## R6 — PR URL 추출 방식

**Decision**: assistant 메시지 텍스트에서 정규식 `PR_URL=(\S+)`로 추출한다. driver가 매치를 보면 stdout에 `PR_URL=<url>` 라인을 그대로 emit (003 protocol). 운영자의 슬래시 스킬은 `gh pr create --draft --json url --jq '"PR_URL=" + .url'` 같은 형태로 PR URL을 한 번 찍어주기만 하면 된다.

**Rationale**:
- 003 stdout protocol 그대로 통과 → daemon-side worker.py가 기존 `_PR_URL_RE` 그대로 사용.
- daemon은 GitHub API 자격증명을 보유하지 않음 (Q1).
- 운영자 측 스킬에 책임을 위임하고 driver는 dumb-relay.

**Alternatives considered**:
- SDK Stop hook의 result 메시지에서 추출 — Stop hook 시점에 PR URL이 메시지에 포함되리란 보장이 없음. 거부.
- 파일 기반 (`<worktree>/.remotask/pr_url`)으로 약속 — 운영자가 추가 규약을 알아야 함. 거부.

---

## R7 — FINAL 검출 메커니즘 (clarify deferred → 해결)

**Decision**: SDK `Stop` 훅 콜백 안에서 driver가 직접 `FINAL <i> natural`을 stdout으로 emit (i = 누적 PostToolUse 카운터). cooperative cancel 경로는 R3에서 `FINAL <i> operator_stop`. 003 protocol의 `_FINAL_RE`로 worker.py가 그대로 파싱.

**Rationale**:
- SDK exit code만으로는 `pr_created` vs `completed` 구분이 어렵고, 003가 정한 FINAL+PR_URL 조합이 가장 robust함.
- 003 worker.py 분기(`final_reason == "operator_stop" → canceled`, `final_reason == "natural" + pr_url → pr_created` 등)를 그대로 활용.

**Alternatives considered**:
- 종료 코드만 사용 — natural vs operator_stop 구분 불가, in-flight 플래그 race가 다시 신뢰의 1차 근거가 됨. 거부.
- SDK가 제공하는 result message 구조에만 의존 — driver 종료 직전 stdout flush 보장이 약하면 데이터 유실 가능. 거부.

---

## R8 — Daemon-restart 회복 (clarify deferred → 해결)

**Decision**: **본 feature 범위 밖**. 현재(003+) 동작 그대로 유지: launchd가 daemon에 SIGTERM을 보내면 process group 전체가 죽으므로 worker도 함께 종료된다. 재기동 시 `running` 상태로 남은 세션은 별도 reconcile 로직 없이 그대로 두며, 운영자가 같은 issue로 재트리거할 때 "active session" 거부에 걸려 정리는 수동(`remotask sessions cancel <key>` 또는 DB 직접 수정)으로 한다.

**Rationale**:
- 헌법 §IV "MVP-First" 정합 — 가치 검증 전에 운영 안정화 인프라를 미리 만들지 않는다.
- 1인 셀프호스트 환경에서 daemon 재기동은 빈도가 낮고 사용자가 즉시 인지함 — 자동 reconcile 부재가 즉각적 위험을 만들지 않는다.
- Phase 4 운영 안정화에서 같은 결정 위에 reconcile + retry 정책을 일괄 설계하는 것이 비용-효율적.

**Alternatives considered**:
- 시작 시 모든 `running` 세션을 `failed`로 표시 — 사용자에게 사라진 진행 상태가 갑자기 실패로 보고됨. 거부.
- worker를 daemon에서 detach해 process group 분리 — daemon은 죽었는데 worker는 살아 PR을 만들면 audit이 비게 됨. 거부.

---

## R9 — PROGRESS / STEP 라인 rate-limit 전략 (clarify deferred → 해결)

**Decision**: driver는 PostToolUse 훅마다 1 STEP 라인을 emit하되, **per-tool 카테고리 단위로 1초 인터벌 throttle**을 둔다. 같은 카테고리(예: `Read`)가 1초 내 연속 발생하면 첫 라인만 emit하고 나머지는 EVENT로만 audit에 적재(토픽 회신 안 함). 카테고리는 SDK tool name으로 분류한다.

**Rationale**:
- spec US2.2 "1줄짜리 spam으로 채워지지 않도록" 만족.
- 1초 throttle은 사람이 토픽을 읽을 수 있는 최소 간격에 가깝고, 짧은 구현으로 충분.
- audit(EVENT)은 그대로 유지 → 사후 추적 가능 (헌법 §VII).

**Alternatives considered**:
- N개씩 묶어 `Read 3개` 형식으로 합치기 — 의미 있는 결합 규칙을 정의하기 어렵고 latency를 늘림. 거부.
- 비동기 deduplication queue — 1인용 도구에 과한 인프라. 거부.

---

## R10 — Test mocking 전략

**Decision**: 두 레이어로 분리.

1. **Daemon-level integration tests** (003-006 회귀): `tests/fakes/fake_agent.py` 그대로 사용. STEP/EVENT 모드를 추가해 신규 라인 셰이프 회귀도 fake로 검증.
2. **Driver-level integration tests** (FR-017 신규): `claude_agent_sdk.Transport`를 stub으로 주입하여 SDK 호출 없이 driver의 라인-셰이프 변환·initial prompt·interrupt 흐름을 검증. 실 OAuth credential·실 LLM 호출 없음.

**Rationale**:
- daemon ↔ worker 인터페이스는 stdout protocol에 닫혀 있으므로 fake_agent로 검증 표면이 충분.
- driver ↔ SDK 인터페이스는 SDK가 제공하는 `Transport` 추상으로 mock 가능.
- 양 레이어를 분리하면 변경 시 하나가 깨져도 어느 쪽인지 즉시 보임 (헌법 §VII 정합).

**Alternatives considered**:
- 실 SDK + 실 OAuth 사용한 e2e 테스트 — CI에서 토큰·과금 문제. 거부 (단, quickstart.md에서 운영자가 수동으로 한 번 수행).
- 모든 테스트를 mock — 003-006 회귀를 깨질 가능성 낮춤이 fake_agent 충분. 거부.

---

## Open items rolled into Phase 1

R1~R10 모두 결정됨. Phase 1 design은 R4(stdout protocol)와 R3(SIGUSR1 → interrupt)에 의존한다. tasks 단계에서 R10의 두 레이어 테스트 매트릭스를 그대로 풀어 task 분해.
