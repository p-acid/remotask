---

description: "Tasks for feature 001-cli-bootstrap"
---

# Tasks: CLI Bootstrap

**Input**: Design documents from `/specs/001-cli-bootstrap/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: 사용자 요구("각 피쳐 별로 작은 테스트 단위를 실행해봤으면 해")에 따라 **테스트는 필수**다. TDD 방식으로 각 user story 안에서 테스트를 먼저 작성하고 구현이 통과시키도록 한다.

**Organization**: tasks는 user story 단위로 묶여 있어 한 story만 완료해도 동작 가능한 단위 산출물이 된다.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 다른 파일 + 의존성 없음 → 병렬 실행 가능
- **[Story]**: US1~US5 (spec.md의 user story 매핑)
- 모든 description에 정확한 파일 경로 포함

## Path Conventions

- 코드: `src/remotask/`
- 테스트: `tests/unit/`, `tests/integration/`
- 산출물: `pyproject.toml`, `templates/`, `src/remotask/migrations/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Python 프로젝트 골격 + 린트·포맷 + 테스트 인프라 구성. 모든 후속 단계의 진입 조건.

- [X] T001 Create `pyproject.toml` at repo root with package metadata, `[project.scripts] remotask = "remotask.cli:app"`, runtime deps (typer[all], platformdirs, tomli-w, structlog, pydantic, jinja2), dev deps (pytest, pytest-cov, ruff, mypy)
- [X] T002 Create source tree: `src/remotask/{__init__.py,_version.py,cli.py}`, `src/remotask/{commands,core,daemon,platform,migrations}/__init__.py`, `templates/`, `tests/{__init__.py,unit/__init__.py,integration/__init__.py}`
- [X] T003 [P] Configure ruff + mypy in `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`); enforce `target-version = "py311"`, `strict = true` for mypy on `src/remotask/core/*`
- [X] T004 [P] Configure pytest in `pyproject.toml` (`[tool.pytest.ini_options]`): markers `unit`, `integration`, `local_only`; `addopts = "-ra --strict-markers"`; `testpaths = ["tests"]`
- [X] T005 [P] Create `tests/conftest.py` with shared fixtures: `tmp_xdg_env` (monkeypatches `XDG_CONFIG_HOME`/`XDG_DATA_HOME`/`XDG_CACHE_HOME` to `tmp_path` subdirs), `cli_runner` (subprocess wrapper invoking `python -m remotask`)

**Checkpoint**: `uv sync` 성공, `uv run pytest` 0개 테스트 정상 종료, `uv run ruff check` 통과.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 모든 user story가 의존하는 공통 모듈(paths·logging·db·migrations)을 완성한다. 이 단계가 끝나기 전에는 어떤 story도 시작할 수 없다.

**⚠️ CRITICAL**: 이 phase 종료 시점에 unit test 전체가 통과해야 한다.

- [X] T006 [P] Write unit tests for path resolution in `tests/unit/test_paths.py`: XDG 환경변수 우선순위, 폴백, `~` 확장
- [X] T007 [P] Write unit tests for structlog config in `tests/unit/test_logging.py`: TTY/non-TTY 분기, JSON 라인 포맷, 컨텍스트 바인딩
- [X] T008 [P] Write unit tests for SQLite migration runner in `tests/unit/test_db_migrations.py`: schema_version 생성, V0001 적용, 멱등성, 트랜잭션 롤백, status CHECK 제약, projects unique, session_events cascade delete
- [X] T009 [P] Write unit tests for secrets in `tests/unit/test_secrets.py`: 토큰 길이/엔트로피, 마스킹(`****<last4>`), `is_secret_key()` 분류
- [X] T010 Implement `src/remotask/core/paths.py` using `platformdirs`: `config_dir()`, `data_dir()`, `cache_dir()`, `pid_path()`, `log_dir()`, `db_path()`, `config_path()` — all return `Path`
- [X] T011 Implement `src/remotask/core/logging.py`: `setup_logging(level, log_dir)` returning configured structlog logger, RotatingFileHandler (10MB × 5), TTY auto-detect renderer
- [X] T012 Implement `src/remotask/core/db.py`: `connect(db_path)` returning `sqlite3.Connection` with `PRAGMA journal_mode=WAL`, `apply_migrations(conn, migrations_dir)` runner that reads `V*.sql`, parses version, runs in transaction, records in `schema_version`
- [X] T013 Create `src/remotask/migrations/V0001__init.sql` with all 5 tables (schema_version, projects, sessions, session_events, locks) per data-model.md §2
- [X] T014 Implement `src/remotask/core/secrets.py`: `generate_token()` using `secrets.token_urlsafe(32)`, `mask(value)` returning `****<last4>`, `is_secret_key(dotted_key)` matching SECRET_KEYS set
- [X] T015 Run `uv run pytest tests/unit/test_paths.py tests/unit/test_logging.py tests/unit/test_db_migrations.py tests/unit/test_secrets.py -v` and ensure all pass

**Checkpoint**: foundational 모듈 4개 + V0001 마이그레이션 + 단위 테스트 모두 통과. user story 진입 준비 완료.

---

## Phase 3: User Story 1 — CLI 진입점·도움말 (Priority: P1) 🎯 MVP

**Goal**: 사용자가 `remotask`를 설치하고 `--version`, `--help`, 각 서브커맨드 `--help`를 호출해 사용법을 즉시 파악할 수 있다.

**Independent Test**: `uv tool install .` 후 `remotask --version`이 버전을 출력하고, `remotask --help`가 8개 서브커맨드를 보여주며, 각 `<subcommand> --help`도 동작한다. `--help` 응답이 1초 이내(SC-002).

### Tests for User Story 1 (TDD — write FIRST, ensure FAIL)

- [X] T016 [P] [US1] Write E2E test `tests/integration/test_cli_help.py::test_version_prints_string` (subprocess `remotask --version` exit 0 + stdout 한 줄)
- [X] T017 [P] [US1] Write E2E test `tests/integration/test_cli_help.py::test_help_lists_all_subcommands` (init, install, uninstall, daemon, config, login, sessions, projects 모두 포함)
- [X] T018 [P] [US1] Write E2E test `tests/integration/test_cli_help.py::test_each_subcommand_help` (loop over 8 subcommands, `--help` exit 0 + non-empty stdout)
- [X] T019 [P] [US1] Write E2E test `tests/integration/test_cli_help.py::test_unknown_command_exits_nonzero` (`remotask foo` exit code != 0)
- [X] T020 [P] [US1] Write performance test `tests/integration/test_cli_help.py::test_help_under_1s` (verify SC-002: `--help` < 1.0s)
- [X] T103 [P] [US1] Write E2E test `tests/integration/test_cli_help.py::test_no_color_in_pipe` — verify SC-010 / FR-005: stdout has no ANSI escapes when piped (subprocess with `stdout=PIPE` and `--no-color` or auto-detect via `NO_COLOR=1`)

### Implementation for User Story 1

- [X] T021 [US1] Implement `src/remotask/_version.py` with `__version__ = "0.1.0"` constant
- [X] T022 [US1] Implement `src/remotask/cli.py` with `app = typer.Typer(name="remotask", no_args_is_help=True)`, global options `--version` (callback), `--verbose`, `--no-color`, `--config`
- [X] T023 [US1] Implement `src/remotask/__main__.py` so `python -m remotask` invokes `cli.app()`
- [X] T024 [P] [US1] Create stub subcommand `src/remotask/commands/init.py` with `app: typer.Typer` and a no-op `init()` function (full impl in US2); register help text from contract
- [X] T025 [P] [US1] Create stub subcommand `src/remotask/commands/install.py` mirror pattern (full impl in US5)
- [X] T026 [P] [US1] Create stub subcommand `src/remotask/commands/uninstall.py` mirror pattern
- [X] T027 [P] [US1] Create stub subcommand `src/remotask/commands/daemon.py` with sub-Typer for run-foreground/start/stop/status/logs; bodies print "not implemented" until US4
- [X] T028 [P] [US1] Create stub subcommand `src/remotask/commands/config_cmd.py` mirror pattern (full impl in US3)
- [X] T029 [P] [US1] Create stub subcommand `src/remotask/commands/login.py` printing "stub — implemented in 002-telegram-trigger"
- [X] T030 [P] [US1] Create stub subcommand `src/remotask/commands/sessions.py` printing "stub — implemented in 003-agent-execution"; `list` outputs "no sessions yet"
- [X] T031 [P] [US1] Create stub subcommand `src/remotask/commands/projects.py` with sub-Typer scaffold for `list`/`add`/`remove` (full impl in US6)
- [X] T032 [US1] Wire all stub subcommands into `cli.py` via `app.add_typer(...)`; ensure each appears in `--help`

**Checkpoint**: T016~T020의 모든 E2E 테스트 통과. 사용자가 `remotask --help`로 8개 서브커맨드를 확인할 수 있다. quickstart.md Step 1 검증 가능.

---

## Phase 4: User Story 2 — init 환경 부트스트랩 (Priority: P1) 🎯 MVP

**Goal**: `remotask init` 한 번으로 XDG 디렉토리 + config.toml(0600) + state.db + 토큰이 생성되어 후속 명령이 즉시 동작 가능한 상태에 도달한다.

**Independent Test**: 격리된 XDG 환경에서 `remotask init` 실행 → 산출물 존재·권한·DB 스키마·토큰 자동 생성 검증. 멱등성과 `--force` 동작 검증. 3초 이내(SC-003).

### Tests for User Story 2 (TDD)

- [X] T033 [P] [US2] Write unit tests for config schema in `tests/unit/test_config.py`: pydantic 검증(범위/타입/enum), 기본값, dotted-path get/set, 정의되지 않은 키 거부, list 타입 set
- [X] T034 [P] [US2] Write E2E test `tests/integration/test_init_command.py::test_init_creates_all_artifacts` (config.toml, state.db, logs/ 생성 확인)
- [X] T035 [P] [US2] Write E2E test `tests/integration/test_init_command.py::test_init_config_permission_0600` (FR-012 / SC-007)
- [X] T036 [P] [US2] Write E2E test `tests/integration/test_init_command.py::test_init_db_schema_v1` (sqlite3로 5개 테이블 + schema_version=1 확인)
- [X] T037 [P] [US2] Write E2E test `tests/integration/test_init_command.py::test_init_generates_auth_token` (config.toml 안 daemon.auth_token 존재 + 길이 ≥ 32)
- [X] T038 [P] [US2] Write E2E test `tests/integration/test_init_command.py::test_init_idempotent` (두 번 호출 후 mtime 변경 없음)
- [X] T039 [P] [US2] Write E2E test `tests/integration/test_init_command.py::test_init_force_overwrites_config_preserves_db` (--force 후 config 갱신, projects 행 보존)
- [X] T040 [P] [US2] Write E2E performance test `tests/integration/test_init_command.py::test_init_under_3s` (SC-003)
- [X] T041 [P] [US2] Write E2E test `tests/integration/test_init_command.py::test_init_rolls_back_on_partial_failure` (모킹된 디스크 오류 시 부분 파일 정리)

### Implementation for User Story 2

- [X] T042 [US2] Implement `src/remotask/core/config.py` with pydantic models (AgentConfig, DaemonConfig, TelegramConfig, LoggingConfig, PathsConfig, ConfigSchema) per contracts/config.schema.md §3
- [X] T043 [US2] Add to `core/config.py`: `load(path) -> ConfigSchema`, `save(path, schema)` writing TOML with `tomli_w`, `get_dotted(schema, "a.b.c")`, `set_dotted(schema, "a.b.c", value)`; reject undefined keys
- [X] T044 [US2] Implement `core/config.py::ensure_permission_0600(path)` validation; called on every load/save
- [X] T045 [US2] Implement `src/remotask/commands/init.py::init(force: bool = False, interpreter: Path | None = None)` per contracts/cli-commands.md §3: create dirs, generate token, write config.toml 0600, run db migrations, print summary
- [X] T046 [US2] Add rollback handler in init: `try/except` cleans newly created files on failure, preserves pre-existing
- [X] T047 [US2] Update `core/db.py::connect()` to invoke `apply_migrations` automatically on first call

**Checkpoint**: T033~T041 모든 테스트 통과. 사용자가 `remotask init` 한 번으로 환경 부트스트랩 완료. quickstart.md Step 2 검증 가능. **여기까지 P1 완료 → MVP의 첫 절반 도달**.

---

## Phase 5: User Story 3 — config get/set (Priority: P2)

**Goal**: 사용자가 텔레그램 토큰·max_concurrent 등을 명령행에서 조회·변경할 수 있다. 시크릿은 마스킹, `--reveal`로만 원문.

**Independent Test**: init 후 `config get` / `set` / `list` / `regenerate-token` 왕복 동작. 정의되지 않은 키 거부, 범위 검증, 마스킹 동작.

### Tests for User Story 3 (TDD)

- [X] T048 [P] [US3] Write E2E test `tests/integration/test_config_command.py::test_get_default_value` (`config get agent.max_concurrent` → `1`)
- [X] T049 [P] [US3] Write E2E test `tests/integration/test_config_command.py::test_set_round_trip` (set 후 get으로 동일 값)
- [X] T050 [P] [US3] Write E2E test `tests/integration/test_config_command.py::test_set_unknown_key_rejected` (`foo.bar` 거부 + 사용 가능한 키 안내)
- [X] T051 [P] [US3] Write E2E test `tests/integration/test_config_command.py::test_set_invalid_format_rejected` (`max_concurrent abc` 거부)
- [X] T052 [P] [US3] Write E2E test `tests/integration/test_config_command.py::test_set_out_of_range_rejected` (`max_concurrent 99` 거부)
- [X] T053 [P] [US3] Write E2E test `tests/integration/test_config_command.py::test_secret_masked_by_default` (`get daemon.auth_token` → `****` 시작)
- [X] T054 [P] [US3] Write E2E test `tests/integration/test_config_command.py::test_reveal_flag_returns_plaintext` (`--reveal` 후 원문)
- [X] T055 [P] [US3] Write E2E test `tests/integration/test_config_command.py::test_list_masks_secrets` (config list가 시크릿 마스킹)
- [X] T056 [P] [US3] Write E2E test `tests/integration/test_config_command.py::test_regenerate_token` (재발급 후 이전 토큰과 다름)
- [X] T057 [P] [US3] Write E2E test `tests/integration/test_config_command.py::test_set_list_value` (`telegram.allowed_user_ids 12345,67890` → `[12345, 67890]`)
- [X] T104 [P] [US3] Write E2E test `tests/integration/test_config_command.py::test_regenerate_token_emits_audit_log` — verify FR-053: audit log entry contains event=`token.regenerated` + name + timestamp (no plaintext token)

### Implementation for User Story 3

- [X] T058 [US3] Implement `commands/config_cmd.py::get(key, reveal)` calling `core.config.load + get_dotted + secrets.mask` if secret
- [X] T059 [US3] Implement `commands/config_cmd.py::set(key, value)` parsing string → typed value, calling `set_dotted` then `save`; surface pydantic validation errors as user-friendly text
- [X] T060 [US3] Implement `commands/config_cmd.py::list_(reveal)` printing tree with masking
- [X] T061 [US3] Implement `commands/config_cmd.py::regenerate_token(name)` calling `secrets.generate_token` and `set_dotted`
- [X] T062 [US3] Add list value parser in `core/config.py::parse_set_value(key, raw)` handling int/bool/list/str by inspecting pydantic field type

**Checkpoint**: T048~T057 통과. quickstart.md Step 3 검증 가능. **사용자는 텔레그램 토큰을 등록할 준비 완료**.

---

## Phase 6: User Story 4 — daemon stub 라이프사이클 (Priority: P2)

**Goal**: `daemon run-foreground` / `start` / `stop` / `status` / `logs`가 동작하며 PID·flock으로 단일 인스턴스 보장, stale PID 자동 정리.

**Independent Test**: 백그라운드 spawn 후 status·stop 사이클 검증, 락 충돌, stale PID 정리. `daemon stop` 5초 이내(SC-004).

### Tests for User Story 4 (TDD)

- [X] T063 [P] [US4] Write unit tests `tests/unit/test_lifecycle.py`: PID 파일 생성/삭제, flock 획득/충돌, SIGTERM 핸들러
- [X] T064 [P] [US4] Write E2E test `tests/integration/test_daemon_lifecycle.py::test_run_foreground_writes_pid_and_acquires_lock`
- [X] T065 [P] [US4] Write E2E test `tests/integration/test_daemon_lifecycle.py::test_second_instance_rejected` (락 충돌, exit 4)
- [X] T066 [P] [US4] Write E2E test `tests/integration/test_daemon_lifecycle.py::test_status_running` (PID + uptime 출력 + exit 0)
- [X] T067 [P] [US4] Write E2E test `tests/integration/test_daemon_lifecycle.py::test_status_not_running` (exit 1)
- [X] T068 [P] [US4] Write E2E test `tests/integration/test_daemon_lifecycle.py::test_stop_graceful` (SIGTERM 후 정상 종료)
- [X] T069 [P] [US4] Write E2E performance test `tests/integration/test_daemon_lifecycle.py::test_stop_under_5s` (SC-004)
- [X] T070 [P] [US4] Write E2E test `tests/integration/test_daemon_lifecycle.py::test_stale_pid_cleanup` (가짜 PID 후 status가 cleanup)
- [X] T071 [P] [US4] Write E2E test `tests/integration/test_daemon_lifecycle.py::test_start_background_spawn` (`daemon start` non-blocking + status로 살아있음 확인)

### Implementation for User Story 4

- [X] T072 [US4] Implement `core/lifecycle.py`: `Lifecycle` context manager that opens PID file, acquires `fcntl.flock(LOCK_EX|LOCK_NB)`, writes PID, registers SIGTERM/SIGINT handlers, cleans up on exit
- [X] T073 [US4] Implement `core/lifecycle.py::is_running(pid_path)` returning `(running: bool, pid: int|None)` with stale detection via `os.kill(pid, 0)`
- [X] T074 [US4] Implement `daemon/stub_runtime.py::run()` using `Lifecycle` ctx + `signal.pause()` idle loop; logs "daemon started, pid=..." and "daemon shutting down" on signal
- [X] T075 [US4] Implement `commands/daemon.py::run_foreground()` calling `stub_runtime.run()`
- [X] T076 [US4] Implement `commands/daemon.py::start()` using `subprocess.Popen` with `start_new_session=True` to detach from terminal; print PID after lifecycle confirms
- [X] T077 [US4] Implement `commands/daemon.py::stop()` reading PID, sending SIGTERM, polling up to 5s, escalating to SIGKILL on timeout; cleans PID file on success
- [X] T078 [US4] Implement `commands/daemon.py::status()` using `is_running` + uptime (from PID file mtime); prints structured output per contract
- [X] T079 [US4] Implement `commands/daemon.py::logs(follow)` tailing `daemon.log` via simple file open + read loop (or `subprocess.run(["tail", "-f", ...])` when `--follow`)

**Checkpoint**: T063~T071 통과. 사용자는 노트북에서 데몬을 직접 띄우고 stop할 수 있다. quickstart.md Step 4 검증 가능. **이 시점부터 다음 feature(`002-telegram-trigger`)가 stub_runtime을 실 runtime으로 교체할 수 있는 자리가 마련됨**.

---

## Phase 7: User Story 5 — install / uninstall (Priority: P3)

**Goal**: `remotask install` 한 명령으로 macOS launchd에 등록되어 부팅 시 자동 실행. `uninstall`로 깨끗이 제거.

**Independent Test**: `install` 후 plist 파일 존재 + `launchctl list`에 노출 + 데몬 헬스 응답. `uninstall` 후 사용자 데이터 보존.

### Tests for User Story 5 (TDD)

- [X] T080 [P] [US5] Write unit tests `tests/unit/test_macos_launchd.py::test_render_basic` (plistlib parse 후 키 검증)
- [X] T081 [P] [US5] Write unit tests `tests/unit/test_macos_launchd.py::test_render_path_includes_claude_dir` (자동 감지된 PATH에 `claude` 위치 포함)
- [X] T082 [P] [US5] Write unit tests `tests/unit/test_macos_launchd.py::test_render_keep_alive_dict` (KeepAlive=dict, SuccessfulExit=false, Crashed=true)
- [X] T083 [P] [US5] Write unit tests `tests/unit/test_macos_launchd.py::test_label_validation` (잘못된 label 거부)
- [X] T084 [P] [US5] Write E2E test `tests/integration/test_install_uninstall.py::test_install_creates_plist` (mocked launchctl)
- [X] T085 [P] [US5] Write E2E test `tests/integration/test_install_uninstall.py::test_uninstall_preserves_user_data` (config·db·logs 존재)
- [X] T086 [P] [US5] Write E2E test `tests/integration/test_install_uninstall.py::test_uninstall_purge_removes_data` (--purge 시 모두 제거)
- [X] T087 [P] [US5] Write opt-in test `tests/integration/test_install_uninstall.py::test_install_loads_with_launchctl` marked `@pytest.mark.local_only`
- [X] T088 [P] [US5] Write opt-in test `tests/integration/test_install_uninstall.py::test_uninstall_unloads_with_launchctl` marked `@pytest.mark.local_only`
- [X] T105 [P] [US5] Write E2E test `tests/integration/test_install_uninstall.py::test_install_replaces_existing_plist` — verify FR-042: pre-existing plist + `--force` → unload old, write new, load, daemon healthy
- [X] T106 [P] [US5] Write E2E test `tests/integration/test_install_uninstall.py::test_install_emits_audit_log` — verify FR-053: audit log entry `event=launchd.install` + label
- [X] T107 [P] [US5] Write E2E test `tests/integration/test_install_uninstall.py::test_uninstall_emits_audit_log` — verify FR-053: audit log entry `event=launchd.uninstall` + label + purge flag

### Implementation for User Story 5

- [X] T089 [US5] Create `templates/launchd.plist.j2` Jinja2 template per contracts/launchd-plist.md §1
- [X] T090 [US5] Implement `platform/macos_launchd.py::render_plist(label, remotask_path, env)` using Jinja2 + parsing back via `plistlib` to validate
- [X] T091 [US5] Implement `platform/macos_launchd.py::detect_environment()` returning dict of PATH (claude dir 포함 보장), HOME, LANG, XDG_*
- [X] T092 [US5] Implement `platform/macos_launchd.py::launchctl_load(plist_path)` and `launchctl_unload(plist_path)` via `subprocess.run`; surface errors with structured logging
- [X] T093 [US5] Implement `commands/install.py::install(label, interpreter, force)` per contract: detect env, render, write plist, load via launchctl, poll 5s for daemon health
- [X] T094 [US5] Implement `commands/uninstall.py::uninstall(label, purge)` per contract: unload, delete plist, optionally remove user data dirs

**Checkpoint**: T080~T088, T105~T107 자동 테스트 통과 + T087/T088 옵트인 통과(사용자 1회 수동). quickstart.md Step 5 검증 가능.

---

## Phase 7.5: User Story 6 — projects CRUD (Priority: P3)

**Goal**: 사용자가 `projects add/list/remove`로 Jira project key ↔ git repo 매핑을 관리할 수 있다. 후속 feature(`002-telegram-trigger`)가 즉시 활용할 수 있도록 본 feature에서 완전 구현.

**Independent Test**: init 후 `projects add ZXTL <repo>` → `projects list`에서 행 확인 → `projects remove ZXTL` → 다시 list에서 사라짐. 잘못된 key·경로·중복은 거부.

### Tests for User Story 6 (TDD)

- [X] T108 [P] [US6] Write unit tests `tests/unit/test_projects.py::test_jira_key_validator` — 정규식 `^[A-Z]{2,10}$` 통과/거부 사례 (`ZXTL` ok, `zxtl` reject, `Z` reject, `TOOLONGNAMES` reject)
- [X] T109 [P] [US6] Write unit tests `tests/unit/test_projects.py::test_repo_path_validator` — 존재하지 않는 경로 거부, `.git` 없는 디렉토리 거부, 정상 git repo 통과 (tmp_path + `git init` fixture)
- [X] T110 [P] [US6] Write E2E test `tests/integration/test_projects_command.py::test_list_empty` — init 직후 `projects list` → "no projects yet" + exit 0
- [X] T111 [P] [US6] Write E2E test `tests/integration/test_projects_command.py::test_add_creates_row` — `projects add ZXTL <git-repo>` 후 DB에 행 존재
- [X] T112 [P] [US6] Write E2E test `tests/integration/test_projects_command.py::test_add_invalid_key_rejected` — 형식 오류 키 거부 (FR-061)
- [X] T113 [P] [US6] Write E2E test `tests/integration/test_projects_command.py::test_add_nonexistent_path_rejected` — 미존재 경로 거부 (FR-062)
- [X] T114 [P] [US6] Write E2E test `tests/integration/test_projects_command.py::test_add_non_git_path_rejected` — `.git` 없는 디렉토리 거부 (FR-062)
- [X] T115 [P] [US6] Write E2E test `tests/integration/test_projects_command.py::test_add_duplicate_rejected` — 동일 key 중복 거부 (FR-063)
- [X] T116 [P] [US6] Write E2E test `tests/integration/test_projects_command.py::test_add_with_branch_option` — `--branch develop` 적용 (FR-064)
- [X] T117 [P] [US6] Write E2E test `tests/integration/test_projects_command.py::test_remove_deletes_row` — 등록된 키 삭제 후 list에서 사라짐 (FR-065)
- [X] T118 [P] [US6] Write E2E test `tests/integration/test_projects_command.py::test_remove_unknown_key_error` — 미등록 키 거부 (FR-065)
- [X] T119 [P] [US6] Write E2E test `tests/integration/test_projects_command.py::test_list_shows_columns` — list 출력에 jira_key·repo_path·base_branch·enabled 컬럼 포함 (FR-060)

### Implementation for User Story 6

- [X] T120 [US6] Implement `src/remotask/core/projects.py::validate_jira_key(key)` raising ValueError with hint on failure
- [X] T121 [US6] Implement `src/remotask/core/projects.py::validate_repo_path(path)` checking exists + is_dir + has `.git` subdir; raise ValueError with hint
- [X] T122 [US6] Implement `src/remotask/core/projects.py::add(conn, jira_key, repo_path, base_branch)` performing INSERT, raising on UNIQUE conflict
- [X] T123 [US6] Implement `src/remotask/core/projects.py::list_all(conn)` returning list of dict rows ordered by jira_key
- [X] T124 [US6] Implement `src/remotask/core/projects.py::remove(conn, jira_key)` raising if missing
- [X] T125 [US6] Implement `src/remotask/commands/projects.py::list_()` calling `core.projects.list_all` + tabulate or simple aligned text output
- [X] T126 [US6] Implement `src/remotask/commands/projects.py::add(jira_key, repo_path, branch)` orchestrating validators + core.add + structured success message
- [X] T127 [US6] Implement `src/remotask/commands/projects.py::remove(jira_key)` orchestrating core.remove + structured success message

**Checkpoint**: T108~T119 모든 테스트 통과. 사용자가 다음 feature(`002-telegram-trigger`)에 진입하기 전에 매핑을 등록할 수 있다. **MVP feature 001 완료**.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: 모든 user story 통합 후 마무리.

- [X] T095 [P] Update `README.md` at repo root with installation & quickstart link
- [X] T096 [P] Add `--help` 응답 시간 회귀 테스트 `tests/integration/test_cli_help.py::test_help_under_1s_after_full_load` (모든 서브커맨드 등록 후에도 SC-002 유지)
- [X] T097 Run full quickstart.md flow manually (Steps 1~5) on the real notebook; record any deviations as follow-up issues
- [X] T098 Run `uv run pytest --cov=remotask tests/` and ensure coverage ≥ 70% (per quickstart.md 종료 조건)
- [X] T099 Run `uv run ruff check src/ tests/` and `uv run mypy src/remotask/core/` with zero findings
- [X] T100 Sanity check: `uv tool install .` from a fresh shell + run quickstart Step 1 commands without errors
- [X] T101 Audit: confirm no SECRET key plaintext leaks in any test fixture or log output (grep `tests/` and `~/.local/share/remotask/logs/`)
- [X] T102 Verify constitution gates checklist in `plan.md` is fully `[x] PASS` after implementation; update Complexity Tracking if any new variance emerged
- [X] T128 [P] Write stress test `tests/integration/test_concurrency_stress.py::test_init_concurrent_100x` — verify SC-008: 동시 init 시도 100회 반복, 한쪽만 성공·다른 쪽 거부, 데이터 무결성 (DB schema·config 0600 유지)
- [X] T129 [P] Write stress test `tests/integration/test_concurrency_stress.py::test_daemon_concurrent_spawn_100x` — verify SC-008: 동시 `daemon run-foreground` 100회 반복, 락 충돌이 정확히 한 번만 성공, PID 파일 일관성

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: 의존성 없음 — 즉시 시작 가능
- **Phase 2 (Foundational)**: Phase 1 완료 후 — **모든 user story의 진입 조건**
- **Phase 3 (US1)**: Phase 2 완료 후 — 다른 story와 독립
- **Phase 4 (US2)**: Phase 2 완료 후 — US1과 독립이지만 같은 P1이므로 동시 머지 권장
- **Phase 5 (US3)**: Phase 2 + US2의 config schema(T042) 완료 후
- **Phase 6 (US4)**: Phase 2 완료 후 — 다른 story와 독립
- **Phase 7 (US5)**: Phase 2 + US4의 daemon command(T078) 완료 후 — install이 데몬 헬스를 폴링하므로 US4가 먼저
- **Phase 7.5 (US6)**: Phase 2 완료 후 — 다른 story와 독립 (US5와 병렬 가능)
- **Phase 8 (Polish)**: 모든 US 완료 후

### User Story Dependencies (그래프)

```
Phase 2 (Foundational)
    │
    ├─▶ Phase 3 (US1: CLI 진입점)
    │
    ├─▶ Phase 4 (US2: init)
    │       │
    │       └─▶ Phase 5 (US3: config) ─ US2의 config schema 의존
    │
    ├─▶ Phase 6 (US4: daemon) ─ Phase 7의 install이 의존
    │       │
    │       └─▶ Phase 7 (US5: install/uninstall)
    │
    ├─▶ Phase 7.5 (US6: projects CRUD)   독립
    │
    └─▶ Phase 8 (Polish)
```

### Within Each User Story

- 테스트(`Write E2E test ...`) 먼저 → **실패 확인** → 구현 → 통과 확인
- 같은 phase 안 [P] 표시 task는 병렬 가능
- checkpoint 도달 시 사용자가 직접 quickstart.md 해당 Step을 실행해 확인

---

## Parallel Opportunities

### Setup (Phase 1) 병렬
T003, T004, T005는 다른 파일 → 동시 작업 가능.

### Foundational (Phase 2) 병렬 — 테스트 작성
T006, T007, T008, T009는 모두 다른 unit test 파일이므로 동시 작성 가능.

### Foundational (Phase 2) 직렬 — 구현
T010 → T011 → T012 → T013 → T014 순서. T012(db.connect)는 T010(paths) + T013(V0001 sql) 완료 후 가능.

### User Story 1 병렬
T016~T020 (테스트 5개)는 같은 파일이지만 독립 함수 — 한 task로 묶여있지 않다면 병렬 작성 가능.
T024~T031 (서브커맨드 stub) 8개는 모두 다른 파일이므로 완전 병렬.

### User Story 2 병렬
T033~T041 (테스트)은 다른 파일 또는 독립 함수 → 병렬 작성 가능.
T042~T044 (config core)은 같은 파일 → 직렬.
T045~T047 (init impl + db connect 갱신)은 함수 단위로 분리되지만 같은 모듈 → 직렬 권장.

### User Story 3 병렬
T048~T057 (테스트 10개)는 같은 파일의 독립 함수 — 병렬 작성 가능.
T058~T062 (구현)은 같은 파일 → 직렬.

### User Story 4 / 5 병렬
US4 테스트와 US5 테스트는 다른 파일이라 동시 작성 가능. 단 US5 구현은 US4 구현 후.

---

## Implementation Strategy

### MVP 1차 (US1 + US2)

1. Phase 1 (Setup) 완료
2. Phase 2 (Foundational) 완료 — **여기까지가 진짜 진입 비용**
3. Phase 3 (US1) 완료 → quickstart Step 1 검증
4. Phase 4 (US2) 완료 → quickstart Step 2 검증
5. **STOP & VALIDATE** — 여기서 사용자는 처음으로 "설치하고 init하면 환경이 부트스트랩되는" 가치를 손에 쥔다.

### MVP 2차 (US3 + US4)

6. Phase 5 (US3) 완료 → quickstart Step 3 검증
7. Phase 6 (US4) 완료 → quickstart Step 4 검증
8. **STOP & VALIDATE** — 데몬을 직접 띄우고 정상 종료할 수 있다. 이 시점부터 `002-telegram-trigger`로 넘어갈 수 있는 base 완성.

### MVP 3차 (US5 + US6)

9. Phase 7 (US5) 완료 → quickstart Step 5 수동 검증 (실제 launchd 등록)
10. Phase 7.5 (US6) 완료 → projects add/list/remove 왕복 검증 (US5와 병렬 작업 가능)
11. Phase 8 (Polish) 완료 → SC-008 stress test + 회귀·커버리지·헌법 게이트 확인
12. **001-cli-bootstrap feature 완료** — 머지 가능 상태 + `002-telegram-trigger` 진입 준비 완료

각 STOP 지점에서 `/speckit-implement`를 종료하고 사용자가 직접 검증하기 좋다.

---

## Notes

- [P] tasks = 다른 파일 + 의존성 없음
- [USx] 라벨은 user story 추적용
- 모든 테스트는 **먼저 작성하고 실패 확인 후 구현으로 통과**시킨다 (사용자 요구: 작은 테스트 단위 실행)
- 각 phase checkpoint마다 quickstart.md의 해당 Step을 손으로 한 번 실행해 보는 것을 권장
- 헌법 II 부분 위반(CLI ↔ daemon HTTP 미도입)은 plan.md Complexity Tracking에 기록되어 있으며 본 feature 범위 내에서 의도된 결정이다
- 커밋은 task 단위 또는 logical group(예: 테스트 5개 + 구현 5개)으로 잘게
- 헌법 V(spec-driven)에 따라 어떤 task도 spec/plan 변경을 요구하면 먼저 본 문서들을 갱신할 것
