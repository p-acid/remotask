# Implementation Plan: Agent SDK Integration

**Branch**: `007-agent-sdk-integration` | **Date**: 2026-05-03 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/007-agent-sdk-integration/spec.md`

## Summary

`/run <Jira-key>` 흐름의 **워커**를 003 placeholder(`demo_worker`)에서 진짜 `claude-agent-sdk` 기반 driver로 교체한다. daemon-side worker.py의 stdout 프로토콜·종료 ladder·상태 전이는 **그대로 유지**하고, 새 driver(`remotask.agent.sdk_worker`)가 SDK 이벤트(`PostToolUse` / `Stop`)와 메시지 스트림을 003 protocol(`STEP`/`PROGRESS`/`FINAL`/`PR_URL`/`EVENT`)로 변환한다. 003 contract을 작은 추가(`STEP`, `EVENT` 두 라인 셰이프)로 확장하되 기존 `PROGRESS`·`FINAL`·`PR_URL`은 그대로 둬서 `fake_agent`가 깨지지 않게 한다. 권한 정책은 `permission_mode="bypassPermissions"`이며, 헌법 §VI deny-list는 driver-level `PreToolUse` 훅으로 enforce한다(constitution waiver 없이 불변량 유지).

## Technical Context

**Language/Version**: Python 3.11+ (uv-managed venv).
**Primary Dependencies**:
- `claude-agent-sdk >= 0.1` (이미 pyproject에 등재됨; `ClaudeSDKClient` + `ClaudeAgentOptions` + `HookMatcher` 사용).
- `structlog`, `pydantic`, `typer`, `httpx` (변경 없음).
- 신규 의존성 없음.

**Storage**: SQLite V0001 (`sessions / session_events / projects / locks`), 변경 없음. `session_events`는 기존 컬럼만 사용.
**Testing**: pytest + pytest-asyncio. 기존 `tests/fakes/fake_agent.py`는 daemon-level 회귀 테스트용으로 보존. 신규 driver-level 테스트는 `claude_agent_sdk.Transport`를 stub한 mock harness로 작성.
**Target Platform**: macOS (launchd-managed daemon). 변경 없음.
**Project Type**: single (CLI + daemon).
**Performance Goals**:
- SC-001: 첫 push 후 30초 이내 PR URL 게시.
- SC-002: 도구 호출 후 30초 이내 PROGRESS/STEP 라인 게시.
- SC-003: ≥ 80% cooperative cancel within grace window (default 30s).
**Constraints**:
- 헌법 v1.1.0 변경 없음, DB schema V0001 변경 없음, `setMyCommands` `{run, cancel, status}` 변경 없음.
- 동시 실행은 max_concurrent=1(D16)대로 유지.
- daemon은 GitHub API 자격증명을 보유하지 않음(spec FR-005, Q1 결정).
**Scale/Scope**: 1 운영자, 1 daemon, 동시 1 세션.

## Constitution Check

- [x] **PASS — I. Jira as Single Source of Truth**
  - 본 feature는 자체 task/issue/workspace 도메인을 추가하지 않는다. Jira 컨텍스트 fetch는 008 후보로 유보(spec Assumptions). `session_events`에 turn-by-turn 이벤트가 추가되지만 이는 *실행 메타데이터*이므로 헌법 §I 정합.
- [x] **PASS — II. Daemon-Centric Architecture**
  - daemon이 여전히 모든 트리거 진입·세션 라이프사이클·토픽 회신·DB 쓰기를 소유한다. SDK driver는 daemon이 spawn하는 자식 worker subprocess일 뿐(003 placeholder와 동일 위치). HTTP API 표면 변경 없음.
- [x] **PASS — III. Strict Session Isolation (NON-NEGOTIABLE)**
  - 1 issue = 1 worktree = 1 branch 그대로(D8/D19 정합). Telegram presentation은 forum-topic 모델 유지(spec FR-013).
- [x] **PASS — IV. MVP-First, Incremental Hardening**
  - 본 feature가 곧 Phase 1 MVP 가치(원격 트리거 → 진짜 PR)의 마지막 퍼즐. multi-session·web GUI·외부 노출은 도입 안 함. 헌법 §IV 정합.
- [x] **PASS — V. Spec-Driven Development**
  - spec → clarify(2 questions) → plan → tasks → implement 정상 흐름.
- [x] **PASS — VI. Security by Default**
  - `permission_mode="bypassPermissions"`는 per-tool prompt를 끄지만, **deny-list는 driver-level PreToolUse 훅으로 강제**한다. 즉 `git push --force`, `git reset --hard`, `git clean -fd`, `rm -rf <abs>`, `sudo *`는 SDK 권한 우회와 무관하게 driver가 차단한다. 결과적으로 헌법 §VI deny-list invariant는 유지되고, "1회 휴대폰 confirm으로 override"는 spec 범위 밖(필요시 별도 feature). 토큰 0600·whitelist 등은 변경 없음. **WAIVER 불필요**.
- [x] **PASS — VII. Observability & Auditability**
  - `session_events`에 per-turn 이벤트 row 추가(같은 컬럼, 새 type 문자열만 추가 — 스키마 변경 없음). 구조화 로깅·헬스 엔드포인트·로그 로테이션 모두 변경 없음. 외부 네트워크 호출(GitHub API)은 daemon이 직접 발생시키지 않으므로 audit log 추가 불필요.

> **Gate result**: 모든 7개 원칙 PASS. Complexity Tracking 작성 불필요.

## Project Structure

### Documentation (this feature)

```text
specs/007-agent-sdk-integration/
├── plan.md              # this file
├── research.md          # Phase 0 — R1~R10 결정 기록
├── data-model.md        # Phase 1 — 기존 엔티티 + 새 event-type 문자열
├── quickstart.md        # Phase 1 — 운영자 머신에서 end-to-end 검증 절차
├── contracts/
│   └── sdk-worker-protocol.md   # 003 protocol 확장(STEP, EVENT)
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
src/remotask/
├── agent/
│   ├── __init__.py
│   ├── demo_worker.py       # (003) — 유지. fake_agent 대체용 placeholder.
│   └── sdk_worker.py        # NEW (007) — claude-agent-sdk driver.
│                            #   - ClaudeSDKClient + bypassPermissions
│                            #   - PreToolUse 훅(deny-list)
│                            #   - PostToolUse 훅(STEP/EVENT 라인 emit)
│                            #   - Stop 훅(FINAL 라인 emit)
│                            #   - SIGUSR1 → client.interrupt()
│                            #   - assistant 메시지에서 PR_URL=<url> scrape
└── daemon/
    └── worker.py            # MOD — _STEP_RE, _EVENT_RE 추가 (parser 확장만)
                             # 종료 ladder·상태 전이 wiring 그대로

tests/
├── fakes/
│   └── fake_agent.py        # MOD — STEP / EVENT 모드 추가 (회귀 테스트용 stand-in 유지)
├── integration/
│   ├── test_sdk_worker_initial_prompt.py    # NEW — FR-017 (a)
│   ├── test_sdk_worker_pr_url.py            # NEW — FR-017 (b)
│   ├── test_sdk_worker_cooperative_cancel.py # NEW — FR-017 (c)
│   ├── test_setmycommands_curated.py        # NEW — FR-018
│   └── test_sdk_worker_denylist.py          # NEW — 헌법 §VI invariant 회귀
└── unit/
    └── test_sdk_worker_step_event_parsers.py # NEW — STEP/EVENT 라인 파서
```

`pyproject.toml`의 `console_scripts`나 외부 진입점은 변경되지 않는다. daemon이 production에서 부르는 `_default_worker_argv()`만 `remotask.agent.demo_worker` → `remotask.agent.sdk_worker`로 바뀐다 (테스트는 별도 argv를 주입).

**Structure Decision**: Single project layout(=003 그대로). 신규 소스는 `src/remotask/agent/sdk_worker.py` 단일 모듈에 집중. daemon-side는 worker.py에 라인 셰이프 두 개만 추가하여 변경 surface 최소화.

## Phase 0: research → see [research.md](./research.md)

10개 결정 항목(R1~R10) 정리. clarify 단계의 deferred 3건(daemon-restart 회복, FINAL 검출 메커니즘, PROGRESS rate-limit)은 모두 R8/R7/R9에서 답함.

## Phase 1: data-model → see [data-model.md](./data-model.md), contracts → see [contracts/](./contracts), quickstart → see [quickstart.md](./quickstart.md)

- **data-model.md**: `sessions.status` 유지, `session_events.type` 신규 문자열 4종(`agent.tool_use`, `agent.tool_result`, `agent.stop`, `agent.interrupt`), worker.py 신규 audit 이벤트 상수 추가(`EV_AGENT_TURN`).
- **contracts/sdk-worker-protocol.md**: 003 contract을 super-set으로 확장. `STEP <body>`, `EVENT <type> <json>` 두 라인 셰이프 신설. 기존 `PROGRESS`/`FINAL`/`PR_URL`은 unchanged.
- **quickstart.md**: 운영자 머신에서 운영자가 직접 한 번에 검증할 수 있는 절차(brand-new repo + 슬래시 스킬 sanity check + 작은 작업 트리거 + cancel 흐름).

## CLAUDE.md plan pointer

CLAUDE.md의 Active feature plan 포인터를 이 plan.md로 갱신 (Phase 1 단계에서 직접 수행).

## Re-evaluated Constitution Check (post-design)

위 7개 원칙 모두 PASS. design 산출물(driver 단일 모듈 + worker.py 라인 파서 추가)이 §II daemon-thin과 §VI deny-list 모두 충족. 변경 없음.
