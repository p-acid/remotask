# Implementation Plan: Remove Deprecated Termination Aliases

**Branch**: `006-remove-termination-aliases` | **Date**: 2026-05-02 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/006-remove-termination-aliases/spec.md`

## Summary

005가 한 릴리스 동안 deprecated alias로 유지한 4개 종료 별칭(`/done` 슬래시 + 토픽 안 평문 `done`/`stop`/`finish`)을
완전히 제거한다. 운영자가 사용할 종료 명령은 **`/cancel` 단 하나**로 고정되며, 옛 별칭은 음성 케이스로 떨어진다:
`/done`은 `slash_command_rejected reason=unknown_command`로 거부되고, 평문 `done`/`stop`/`finish`는 일반 채팅으로
무시된다. 005에서 도입한 `[<issue_key>]` prefix·`REASON_MAIN_CHAT_CANCEL` 사유·`/cancel` 캐노니컬 동작은 모두 그대로
유지한다. 코드 측면에서는 dispatcher의 별칭 분기, runtime의 `_alias_deprecation_warned` 셋과 메서드 3개,
parser의 `match_termination_command`, audit의 `EV_ALIAS_DEPRECATION_USED`/`REASON_MAIN_CHAT_DONE` 상수,
worker의 `on_terminal` 콜백을 함께 제거하고, 관련 테스트(전용 파일 3개 + 별칭 전용 클래스 2개)를 삭제하며 003 평문
종료 통합 테스트를 `/cancel` 슬래시로 마이그레이션한다.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: 변경 없음 (httpx, claude-agent-sdk, structlog, pydantic, typer, pytest-asyncio — 모두 기존)
**Storage**: SQLite V0001 그대로 (스키마 변경 없음)
**Testing**: pytest + pytest-asyncio (기존 인프라)
**Target Platform**: macOS launchd daemon (`~/.local/share/remotask/`)
**Project Type**: cli/daemon (단일 패키지 `remotask`)
**Performance Goals**: `/done` → `unknown_command` 거부 응답이 1초 이내 (SC-002, 004 reject latency baseline 유지)
**Constraints**:
- `src/`에 `match_termination_command`/`_alias_deprecation_warned`/`EV_ALIAS_DEPRECATION_USED`/
  `REASON_MAIN_CHAT_DONE`/`_emit_alias_warning`/`on_terminal=` 잔재 0건 (SC-001)
- 005에서 보호되는 모든 동작(`/cancel` 캐노니컬, `[KEY]` prefix, `REASON_MAIN_CHAT_CANCEL`) 회귀 0건 (SC-004)
**Scale/Scope**:
- 수정 파일: `src/remotask/daemon/{dispatcher,runtime,worker,audit}.py` + `src/remotask/telegram/parser.py`
- 삭제 파일: `tests/integration/test_alias_deprecation.py`, `tests/integration/test_slash_done.py`,
  `tests/unit/test_runtime_alias_warned.py`
- 마이그레이션 파일: `tests/integration/test_operator_stop.py`, `tests/integration/test_operator_stop_forced.py`,
  `tests/unit/test_telegram_parser.py`(클래스 삭제), `tests/unit/test_dispatcher.py`(클래스 삭제),
  `tests/unit/test_audit.py`(상수 어설션 삭제)
- 신규 회귀 테스트: 2건 (FR-019 `/done` unknown_command, FR-020 평문 비-제어)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **I. Jira as Single Source of Truth — PASS**
  - Jira 도메인이나 스토리지에 손대지 않는다. 별칭 제거는 dispatcher/parser 내부 변경.
- [x] **II. Daemon-Centric Architecture — PASS**
  - 모든 변경이 daemon 내부(dispatcher/runtime/worker/audit)와 그 클라이언트 라이브러리(telegram/parser)에 국한됨.
    HTTP API 계약 변경 없음.
- [x] **III. Strict Session Isolation — PASS**
  - 1 issue = 1 worktree = 1 branch 매핑 그대로. 005에서 채택한 forum-topic presentation 매핑도 그대로.
    `[<issue_key>]` prefix는 다중 세션 가독성 보장을 위해 보존된다.
- [x] **IV. MVP-First, Incremental Hardening — PASS**
  - 기능 추가가 아닌 deprecation 사이클의 종결. 005가 약속한 시간 박스 충족.
- [x] **V. Spec-Driven Development — PASS**
  - 본 spec/plan/tasks 흐름을 따른다. < 30분 1 파일 예외 적용 안 함.
- [x] **VI. Security by Default — PASS**
  - 외부 노출/권한 토글 없음. 오히려 입력 처리 표면(평문 termination grammar) 축소로 잠재적 attack surface 감소.
- [x] **VII. Observability & Auditability — PASS**
  - `slash_command_rejected reason=unknown_command` 감사 경로는 005에서 이미 정의됨, 그대로 사용.
  - `alias_deprecation_used` 이벤트와 `main_chat_done` 사유는 더 이상 발행되지 않음. 과거 로그 라인은 immutable이라
    그대로 보존됨 (FR-007 + Edge Case 마지막 항목).
  - `session_events` 테이블 형상 변경 없음.

## Project Structure

### Documentation (this feature)

```text
specs/006-remove-termination-aliases/
├── plan.md              # 이 파일
├── spec.md              # 이미 작성됨
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/           # Phase 1 (계약 변경분만 명시)
└── checklists/
    └── requirements.md  # 이미 작성됨
```

### Source Code (repository root)

```text
src/remotask/
├── core/                # 변경 없음 (db, paths, config)
├── daemon/
│   ├── audit.py         # 수정: EV_ALIAS_DEPRECATION_USED, REASON_MAIN_CHAT_DONE 상수 제거
│   ├── dispatcher.py    # 수정: name=="done" 분기, 평문 termination 분기, _emit_alias_warning 헬퍼,
│   │                    #       _on_terminal cleanup, DispatchContext 콜백 3개, REASON_MAIN_CHAT_DONE
│   │                    #       참조, EV_ALIAS_DEPRECATION_USED 참조 모두 제거
│   ├── runtime.py       # 수정: _alias_deprecation_warned 셋과 has_/record_/clear_ 메서드 3개,
│   │                    #       DispatchContext 콜백 wiring 제거
│   ├── worker.py        # 수정: on_terminal 파라미터·호출 제거
│   ├── topic.py         # 변경 없음 (format_progress chokepoint 보존)
│   ├── sessions.py      # 변경 없음
│   ├── listener*.py     # 변경 없음
│   └── __init__.py      # 변경 없음
├── telegram/
│   ├── parser.py        # 수정: match_termination_command 함수 제거
│   ├── client.py        # 변경 없음
│   ├── commands.py      # 변경 없음 ({run,cancel,status} 그대로)
│   └── __init__.py      # 변경 없음
└── (그 외)              # 변경 없음

tests/
├── unit/
│   ├── test_audit.py                    # 수정: 제거되는 두 상수에 대한 어설션 삭제
│   ├── test_telegram_parser.py          # 수정: TestMatchTerminationCommand 클래스 삭제
│   ├── test_dispatcher.py               # 수정: TestAliasDeprecation 등 별칭 전용 클래스 삭제,
│   │                                    #       남는 테스트의 DispatchContext 생성 시 콜백 3개 제거
│   ├── test_runtime_alias_warned.py     # 삭제
│   ├── test_topic_format.py             # 변경 없음 ([KEY] prefix 보존 검증 그대로)
│   ├── test_runtime_signal_state.py     # 변경 없음
│   ├── test_commands_registry.py        # 변경 없음
│   └── test_*.py                        # 그 외 변경 없음
├── integration/
│   ├── test_alias_deprecation.py        # 삭제
│   ├── test_slash_done.py               # 삭제
│   ├── test_operator_stop.py            # 마이그레이션: 평문 종료 → /cancel 슬래시
│   ├── test_operator_stop_forced.py     # 마이그레이션: 평문 종료 → /cancel 슬래시
│   ├── test_cancel_canonical.py         # 변경 없음 (005에서 추가됨)
│   ├── test_key_prefix.py               # 변경 없음
│   ├── test_worker_lifecycle.py         # 변경 없음 (on_terminal 사용 안 함)
│   ├── test_done_command_removed.py     # 신규: FR-019 회귀 (/done → unknown_command)
│   ├── test_plain_termination_dead.py   # 신규: FR-020 회귀 (평문 done/stop/finish 무시)
│   └── test_*.py                        # 그 외 변경 없음
└── fakes/                               # 변경 없음
```

**Structure Decision**: 단일 패키지 구조 (Option 1). 기존 `src/remotask/{core,daemon,telegram,...}` 레이아웃을 그대로
사용하며, 신규 디렉토리·새 패키지·새 의존성 없음. 005에서 추가된 `format_progress` chokepoint, 005 contracts 디렉토리,
신규 신호 ladder는 모두 보존 대상.

## Phases

### Phase 0 — Research

`research.md`에 8개 결정 사항을 정리한다(별칭 제거 패턴, dispatcher 분기 제거 안전성, parser 함수 제거 영향 범위,
runtime 셋 제거 안전성, worker `on_terminal` 제거 안전성, audit 상수 제거 안전성, 회귀 테스트 설계,
003 평문 통합 테스트 마이그레이션 패턴).

### Phase 1 — Design & Contracts

- `data-model.md` — 데이터 모델 측면에서는 *제거*가 핵심. 005가 추가한 in-memory 셋과 두 audit 상수를 명시적으로
  제거 마킹하고, V0001 스키마는 변동 없음을 재확인한다.
- `contracts/alias-removal-protocol.md` — `/done` slash가 어떤 응답·감사 사건을 만들고, 평문 `done`/`stop`/`finish`가
  어떻게 비-제어 텍스트로 처리되는지(이벤트 부재 contract 포함)를 명시한다.
- `quickstart.md` — 운영자 관점 검증 시나리오: `/cancel`은 그대로 동작, `/done`은 unknown_command로 거부, 평문은
  무시. 005 quickstart의 alias 단계는 negative-case 단계로 대체된다.

### Phase 2 — Tasks

`/speckit-tasks`가 다음 흐름으로 분해할 예정:

1. **Setup phase** — 없음 (의존성·디렉토리 변경 없음). Skip.
2. **Foundational phase** — audit/parser/runtime의 비즈니스-블록 제거 작업 (다른 작업의 import가 깨지므로 선결).
3. **User Story 1 (P1)** — `/cancel`이 유일한 종료 명령임을 보증.
4. **User Story 2 (P2)** — 평문 `done`/`stop`/`finish` 비-제어화.
5. **User Story 3 (P3)** — alias-deprecation 경고 부재 검증.
6. **Polish** — `[KEY]` prefix·`REASON_MAIN_CHAT_CANCEL`·005 quickstart 동작 회귀 확인 + 전체 테스트 스위트 통과.

각 user story phase는 다음을 포함한다: 코드 제거 → 영향 받는 기존 테스트 갱신 → 신규 회귀 테스트 추가 →
부분 테스트 실행으로 독립 검증.

## Complexity Tracking

> 위반 없음. Constitution Check의 7개 게이트 모두 PASS. 비워둔다.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (없음)     | (없음)      | (없음)                                 |
