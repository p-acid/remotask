# Implementation Plan: CLI Bootstrap

**Branch**: `001-cli-bootstrap` | **Date**: 2026-05-01 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-cli-bootstrap/spec.md`

## Summary

remotask의 골격을 세우는 첫 feature. typer 기반 단일 진입점 CLI, XDG 표준 디렉토리 레이아웃, SQLite 스키마와 간이 마이그레이션, 그리고 라이프사이클(PID·signal·lock)만 동작하는 stub daemon을 제공한다. 비즈니스 로직(텔레그램 봇·Agent SDK 실행)은 후속 feature에서 추가된다. macOS launchd 등록·해제까지 한 명령으로 가능하게 만들어 "노트북이 깨어 있는 한 항상 듣고 있다"의 인프라를 완성한다.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**:
  - `typer[all]` — CLI 프레임워크 (Rich 출력 포함)
  - `platformdirs` — XDG 경로 결정 (macOS·Linux 호환)
  - `tomli-w` — TOML 쓰기 (읽기는 stdlib `tomllib`)
  - `structlog` — JSON 구조화 로깅
  - `pydantic` — config 스키마 검증 (이미 SDK 의존성에 포함될 가능성 높음)
**Storage**: SQLite (stdlib `sqlite3`) + 자체 간이 마이그레이션 러너 (`migrations/V0001__init.sql` 형식)
**Testing**:
  - `pytest` + `pytest-cov`
  - CLI E2E는 `subprocess.run`으로 실제 바이너리 호출
  - daemon 라이프사이클은 `pytest` fixture로 백그라운드 spawn 후 검증
  - 임시 환경은 `tmp_path` + `monkeypatch.setenv("XDG_*")`로 격리
**Target Platform**: macOS 14+ (Apple Silicon/Intel). Linux는 후속 단계
**Project Type**: CLI / 단일 프로젝트
**Performance Goals**:
  - `--help` 응답 < 1초 (SC-002)
  - `init` 완료 < 3초 (SC-003)
  - `daemon stop` 정상 종료 < 5초 (SC-004)
  - launchd 부팅 후 헬스 응답 < 30초 (SC-005)
**Constraints**:
  - 외부 API key 사용 금지 (헌법: claude OAuth credential 위임)
  - 웹 GUI 코드 미포함 (MVP 스코프)
  - 단일 사용자 (1인 셀프호스트)
  - launchd plist는 사용자 환경(`PATH`, `HOME`, 인터프리터 경로) 동적 감지
**Scale/Scope**:
  - 사용자 1명
  - 서브커맨드 8개 (init, install, uninstall, daemon, config, login, sessions, projects)
  - SQLite 테이블 5개 (schema_version + 4 비즈니스 테이블; 비즈니스 데이터는 후속 feature에서 채움)
  - 모듈 라인 수 < 2000줄 추정

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

For each gate, mark `[x] PASS`, `[!] WAIVED` (with justification in Complexity Tracking),
or `[ ] PENDING`. All gates must be PASS or WAIVED before implementation.

### Initial Gate (pre-research)

- [x] **I. Jira as Single Source of Truth**
  - No new task/issue/workspace domain is introduced. SQLite 스키마는 `sessions`·`projects` 등 실행 메타데이터만 정의하며, Jira 이슈 자체를 복제하지 않는다.
  - Jira context is fetched, not duplicated to local persistent storage. (이 feature는 Jira 호출을 포함하지 않으나, 스키마는 Jira issue key를 참조 키로만 보관.)
- [x] **II. Daemon-Centric Architecture**
  - Business logic and privileged operations live in the daemon. CLI는 stub daemon의 라이프사이클·설정 조작 진입점만 담당.
  - All clients (CLI, Telegram bot, web) talk to the daemon via the HTTP API. ⚠ MVP에서는 CLI가 직접 PID·DB 파일을 읽는다(데몬 HTTP는 Phase 2). Complexity Tracking 참조.
- [x] **III. Strict Session Isolation** — N/A
  - 본 feature는 세션 실행 코드를 포함하지 않는다. 격리 모델을 깨뜨릴 여지 없음.
- [x] **IV. MVP-First, Incremental Hardening**
  - 웹 GUI·다중 세션·외부 노출은 본 feature에 포함되지 않는다.
  - Phase 0 entry criteria(spec 통과, 헌법 게이트) 충족.
- [x] **V. Spec-Driven Development**
  - spec.md / 본 plan / 후속 tasks·implement는 모두 speckit 흐름을 따른다.
- [x] **VI. Security by Default**
  - `config.toml` 권한 `0600`, 토큰 자동 생성 후 마스킹 표시, denylist 정책의 자리(설정 키)는 본 feature에서 정의되어 후속 feature에서 강제됨.
  - HTTP 노출 없음 → 노출 면적 자체가 0.
- [x] **VII. Observability & Auditability**
  - structlog 기반 JSON 라인 로깅을 처음부터 적용.
  - 모든 CLI·daemon 명령은 audit 로그를 남긴다(install/uninstall/config set/token rotate).

### Justified Variance: Gate II (CLI ↔ daemon HTTP)

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Phase 1 MVP에서 CLI가 daemon에 HTTP로 질의하지 않고 PID·DB를 직접 읽음 | HTTP 서버는 Phase 2(웹 GUI)에서 도입 예정. MVP는 daemon이 단지 stub이고 노출할 API가 없음 | HTTP 서버를 미리 도입하면 인증·포트 충돌·라이프사이클 복잡도가 MVP 단계에 누적됨. 헌법 IV(MVP-First)에 부합하기 위해 의도적 지연 |

이 위반은 헌법 II의 정신("daemon이 단일 진실 원천")을 깨뜨리지 않는다. CLI는 여전히 daemon의 산출물(PID, DB)을 읽기만 하고 비즈니스 로직을 복제하지 않는다. Phase 2에서 HTTP API가 추가되면 자연스럽게 II 완전 준수로 전환된다.

## Project Structure

### Documentation (this feature)

```text
specs/001-cli-bootstrap/
├── plan.md              # 이 문서
├── research.md          # Phase 0 산출물
├── data-model.md        # Phase 1 산출물
├── quickstart.md        # Phase 1 산출물
├── contracts/           # Phase 1 산출물
│   ├── cli-commands.md
│   ├── config.schema.md
│   └── launchd-plist.md
├── checklists/
│   └── requirements.md  # spec 검증 체크리스트
└── tasks.md             # /speckit-tasks 산출물 (이 명령은 생성 안 함)
```

### Source Code (repository root)

본 feature가 만들 코드 트리:

```text
remotask/
├── pyproject.toml
├── README.md
├── .gitignore                       (이미 존재)
├── PRD.md                           (이미 존재)
├── CLAUDE.md                        (이미 존재)
│
├── src/remotask/
│   ├── __init__.py
│   ├── _version.py                  ← 단일 버전 출처
│   ├── cli.py                       ← typer.Typer() 단일 진입점
│   │
│   ├── commands/                    ← 서브커맨드(이 feature에서 채우는 것은 init/install/uninstall/daemon/config; 다른 명령은 stub만)
│   │   ├── __init__.py
│   │   ├── init.py                  ← 환경 부트스트랩
│   │   ├── install.py               ← launchd plist 생성/load
│   │   ├── uninstall.py             ← launchd unload + plist 제거
│   │   ├── daemon.py                ← run-foreground/start/stop/status/logs
│   │   ├── config_cmd.py            ← config get/set
│   │   ├── login.py                 ← (stub, 후속 feature)
│   │   ├── sessions.py              ← (stub, 후속 feature)
│   │   └── projects.py              ← list / add / remove 완전 구현 (US6)
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── paths.py                 ← XDG 경로 결정 (platformdirs 래핑)
│   │   ├── config.py                ← TOML 로드/검증/저장
│   │   ├── secrets.py               ← 토큰 생성·회전·마스킹
│   │   ├── db.py                    ← SQLite 연결·마이그레이션 러너
│   │   ├── logging.py               ← structlog 설정 + 파일 로테이션 + audit 로거
│   │   ├── lifecycle.py             ← PID 파일·flock·signal 핸들러
│   │   └── projects.py              ← jira_key·repo_path 검증 + DB CRUD (US6)
│   │
│   ├── daemon/
│   │   ├── __init__.py
│   │   └── stub_runtime.py          ← 비즈니스 로직 없는 idle loop (signal 대기)
│   │
│   ├── platform/
│   │   ├── __init__.py
│   │   └── macos_launchd.py         ← plist 생성·load·unload·status
│   │
│   └── migrations/
│       └── V0001__init.sql          ← 4개 테이블 + schema_version
│
├── templates/
│   └── launchd.plist.j2             ← Jinja2 템플릿 (install 명령이 렌더)
│
└── tests/
    ├── __init__.py
    ├── conftest.py                  ← XDG 경로 격리 fixture
    ├── unit/
    │   ├── test_paths.py
    │   ├── test_config.py
    │   ├── test_secrets.py
    │   ├── test_db_migrations.py
    │   ├── test_lifecycle.py
    │   └── test_macos_launchd.py
    └── integration/
        ├── test_cli_help.py
        ├── test_init_command.py
        ├── test_config_command.py
        ├── test_daemon_lifecycle.py
        └── test_install_uninstall.py
```

**Structure Decision**: 단일 Python 프로젝트(Option 1) 채택. PRD §8의 디렉토리와 일치하며, 이 feature는 `src/remotask/` 안의 골격(commands·core·daemon·platform·migrations)과 `templates/`, `tests/`만 다룬다. 후속 feature(`002-telegram-trigger`, `003-agent-execution`)는 같은 트리 안에서 `core/bot.py`, `core/dispatcher.py`, `core/worker.py` 등을 추가하게 된다.

## Phase 0 — Research (개요)

Phase 0은 [research.md](./research.md)에서 다룬다. 다룬 주제 요약:

- typer 서브커맨드 구조와 lazy 로딩
- SQLite 마이그레이션 패턴 선택 (자체 SQL runner vs alembic)
- macOS launchd plist 스펙 (KeepAlive, RunAtLoad, EnvironmentVariables)
- PID 파일 + `fcntl.flock`으로 단일 인스턴스 보장
- structlog의 JSON 라인 + 파일 로테이션 구성
- 토큰 생성 (secrets.token_urlsafe) + Keychain 옵션의 표면화 시점
- `--reveal` 패턴(시크릿 마스킹 UX)
- `pytest`로 daemon 라이프사이클 통합 테스트
- TOML 키 dotted-path get/set 처리

**모든 NEEDS CLARIFICATION 해결됨**. 자세한 결정·근거·기각된 대안은 research.md 참조.

## Phase 1 — Design & Contracts

Phase 1 산출물은 다음 세 문서로 분리된다:

- [data-model.md](./data-model.md) — SQLite 스키마 (테이블·인덱스·마이그레이션 정책)
- [contracts/cli-commands.md](./contracts/cli-commands.md) — 모든 서브커맨드의 인자·옵션·종료 코드 계약
- [contracts/config.schema.md](./contracts/config.schema.md) — `config.toml` 키·타입·기본값·시크릿 분류
- [contracts/launchd-plist.md](./contracts/launchd-plist.md) — plist 필수 필드와 환경변수 처리 규칙
- [quickstart.md](./quickstart.md) — 신규 사용자가 5분 안에 install까지 도달하는 매뉴얼 (SC-001 검증)

### Constitution Re-check (post-design)

설계가 끝난 뒤 게이트를 다시 확인하면 모두 PASS:

- I, III, V, VI, VII — 변동 없음, 모두 PASS
- II — Justified Variance 유지(Phase 2에서 HTTP API 추가 예정)
- IV — Phase 0 entry criteria 충족, Phase 1 산출물도 MVP 스코프 내

post-design 결과: **PASS** (variance 1건은 그대로 추적).

### Agent Context Update

`CLAUDE.md` 안의 `<!-- SPECKIT START -->` ~ `<!-- SPECKIT END -->` 블록을 본 plan(`specs/001-cli-bootstrap/plan.md`)을 가리키도록 갱신한다. 갱신은 plan 작성 마지막에 별도 단계로 처리한다.

## 테스트 전략 — 작은 실행 단위 (사용자 요구 반영)

각 user story 별로 **독립적으로 실행 가능한 작은 테스트 단위**를 정의한다. spec의 acceptance scenario를 통합 테스트(integration test)와 1:1로 매핑한다.

| Story | 단위 종류 | 파일 | 검증 방법 |
|---|---|---|---|
| US1: CLI 진입점·도움말 | E2E (subprocess) | `tests/integration/test_cli_help.py` | `remotask --version` 출력·각 서브커맨드 `--help` 가용 |
| US1: 도움말 응답 시간 | 성능 | `tests/integration/test_cli_help.py::test_help_under_1s` | `time.perf_counter()`로 1초 미만 검증 |
| US2: init 부트스트랩 | E2E | `tests/integration/test_init_command.py` | tmp XDG 환경에서 init → 디렉토리·파일·DB 스키마 존재·권한 검증 |
| US2: init 멱등성 | E2E | `tests/integration/test_init_command.py::test_init_idempotent` | init 두 번 호출 후 변경 없음 |
| US2: init --force | E2E | 동일 파일 | 사용자 데이터 보존 + 설정 덮어쓰기 검증 |
| US3: config get/set | E2E | `tests/integration/test_config_command.py` | get/set 왕복, 유효성·마스킹·`--reveal` |
| US4: daemon 라이프사이클 | 통합 | `tests/integration/test_daemon_lifecycle.py` | run-foreground subprocess + status·stop 검증 |
| US4: 단일 인스턴스 락 | 통합 | 동일 파일 | 두 번째 run-foreground 거부 |
| US4: stale PID 정리 | 통합 | 동일 파일 | 죽은 PID로 PID 파일 만들고 status 호출 |
| US5: install/uninstall | 통합 | `tests/integration/test_install_uninstall.py` | plist 존재 + `launchctl list` 노출 + uninstall 후 정리 |
| US5: 사용자 데이터 보존 | 통합 | 동일 파일 | uninstall 후 config·db·logs 존재 |
| US5: 재install plist 갱신 | 통합 | 동일 파일 | 기존 plist 갱신 + 데몬 재시작 (FR-042) |
| US6: projects CRUD | 통합 | `tests/integration/test_projects_command.py` | add → list → remove 왕복 + 검증·중복·미존재 거부 |
| US6: jira_key/repo_path validators | unit | `tests/unit/test_projects.py` | 정규식·경로 존재·git repo 검증 함수 |
| 횡단: SC-008 동시성 stress | 통합 | `tests/integration/test_concurrency_stress.py` | 100회 init·daemon 동시 실행 무결성 |
| 횡단: SC-010 컬러 비활성 | 통합 | `tests/integration/test_cli_help.py::test_no_color_in_pipe` | 파이프 출력에 ANSI escape 부재 |
| 횡단: 헌법 VII audit 로그 | 통합 | 각 US 파일 | regenerate_token / install / uninstall이 audit 로그 항목 추가 |

추가로 unit 레벨에선 모듈별 작은 단위를 둔다:

- `paths`: XDG 환경변수 우선순위, 폴백
- `config`: dotted-path get/set, 정의되지 않은 키 거부
- `secrets`: 토큰 길이·엔트로피·마스킹
- `db`: V0001 마이그레이션 적용 후 PRAGMA로 테이블 존재 확인
- `lifecycle`: PID 파일 생성/락/SIGTERM 핸들러
- `macos_launchd`: plist 렌더링 결과의 키·값 검증 (실제 launchctl은 mocking)

### 테스트 실행 단계 (사용자가 매 스토리 후 직접 실행)

각 user story 구현 후 다음을 차례로 실행해 산출물을 즉시 확인할 수 있도록 한다:

```bash
# 스토리별 단위
uv run pytest tests/integration/test_cli_help.py        # US1
uv run pytest tests/integration/test_init_command.py    # US2
uv run pytest tests/integration/test_config_command.py  # US3
uv run pytest tests/integration/test_daemon_lifecycle.py # US4
uv run pytest tests/integration/test_install_uninstall.py # US5

# 사용자 손으로 직접 검증 (quickstart.md의 절차)
uv run remotask --help
uv run remotask init
uv run remotask config set agent.max_concurrent 1
uv run remotask daemon run-foreground &
uv run remotask daemon status
uv run remotask daemon stop
uv run remotask install      # 실제 launchd 등록(원할 때만)
```

이 흐름이 spec의 "Independent Test" 항목을 그대로 자동/수동 양쪽에서 재현한다.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Gate II 부분 위반 (CLI가 daemon HTTP 대신 PID·DB 직접 접근) | MVP에서 daemon은 stub이며 노출할 API가 없다. HTTP 서버를 미리 도입하면 인증·포트·헬스체크 라이프사이클이 MVP 단계에 누적됨 | Phase 2 도입 전까지는 CLI ↔ daemon 통신 표면을 만들지 않는 것이 IV(MVP-First) 정신에 부합. Phase 2에서 자연 해소됨 |
