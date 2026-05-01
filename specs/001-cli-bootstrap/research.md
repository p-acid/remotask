# Phase 0 — Research: CLI Bootstrap

**Feature**: 001-cli-bootstrap
**Date**: 2026-05-01
**Status**: Complete

각 항목은 결정·근거·기각된 대안 형식으로 기록한다.

---

## R1. typer 서브커맨드 구조와 lazy 로딩

**Decision**: 단일 `typer.Typer()` 루트 + 서브커맨드별 `Typer()`를 `add_typer`로 마운트. 각 서브커맨드 모듈은 `commands/<name>.py`에서 자체 `app: typer.Typer`를 export.

**Rationale**:
- 서브커맨드가 8개로 예상되어 단일 파일에 몰면 도움말 응답이 느려질 가능성 + 모듈 결합 증가.
- typer는 `add_typer(name=...)` 한 줄로 마운트 → 라이트한 구조.
- import는 typer가 lazy하게 처리하지 않으므로, 무거운 의존성(예: `claude-agent-sdk`)이 들어올 후속 feature에 대비해 **명령 함수 본문 안에서만 무거운 import를 수행**하는 규칙을 둔다.

**Alternatives rejected**:
- click — 표준이지만 typer가 type hint 기반으로 더 간결함.
- argparse — 도움말 UX·형식 검증 모두 typer가 우월.
- 단일 파일 모놀리식 — 현재는 가능하지만 후속 feature가 무거워지면 깨짐.

---

## R2. SQLite 마이그레이션 패턴

**Decision**: 자체 간이 마이그레이션 러너(파일명 정렬 기반).
- 디렉토리: `src/remote_task/migrations/`
- 파일명 규칙: `V<seq>__<slug>.sql` (예: `V0001__init.sql`)
- 적용 시점: `db.connect()` 호출 시 `schema_version`을 읽어 미적용 분만 트랜잭션으로 실행.
- 다운그레이드 미지원 (전진 전용).

**Rationale**:
- 외부 의존성(alembic) 없이 < 100줄 Python으로 구현 가능.
- alembic은 SQLAlchemy 모델 + 환경 설정 + autogenerate 등 부가 기능이 1인용 도구에 과함.
- 파일명 정렬 + `schema_version` 테이블 + `BEGIN; ... COMMIT;`만으로 충분히 안전.

**Alternatives rejected**:
- alembic — 과한 기능 + 학습/유지 비용.
- yoyo-migrations — 의존성 추가 가치 작음.
- 마이그레이션 없이 매 init마다 `CREATE TABLE IF NOT EXISTS` — 컬럼 추가 시 대응 불가.

**Implementation note**: 트랜잭션 실패 시 롤백되며 사용자 데이터는 보존된다(spec FR-014, edge case 항목과 일치).

---

## R3. macOS launchd plist 스펙

**Decision**: User-level Launch Agent (`~/Library/LaunchAgents/`)를 사용. 필수 키:
- `Label`: `kr.mission-driven.remote-task` (역방향 도메인)
- `ProgramArguments`: `[<remote-task 절대경로>, "daemon", "run-foreground"]`
- `RunAtLoad`: `true`
- `KeepAlive`: `{ "SuccessfulExit": false, "Crashed": true }` (정상 종료엔 재시작 안 함, 크래시엔 재시작)
- `EnvironmentVariables`: `PATH`, `HOME`, `LANG`, `XDG_*` (사용자 환경에서 자동 감지·하드코딩)
- `StandardOutPath` / `StandardErrorPath`: `~/.local/share/remote-task/logs/launchd.{out,err}.log`
- `WorkingDirectory`: `$HOME`
- `ThrottleInterval`: `10` (재시작 최소 간격, 무한 루프 방지)

**Rationale**:
- User-level Agent는 사용자 로그인 시 자동 실행되며 sudo 불필요.
- `KeepAlive.Crashed=true`로 비정상 종료에만 재시작 → 의도적 `daemon stop`과 충돌하지 않음.
- launchd는 사용자 셸 환경을 거의 상속하지 않으므로 `EnvironmentVariables`에 PATH 등 명시 필수(spec edge case와 일치).

**Alternatives rejected**:
- `KeepAlive: true` (단순 boolean) — 의도적 종료 시에도 재시작되어 `daemon stop` 불가.
- `LaunchDaemons` (시스템 수준) — sudo 필요 + 1인용 도구에 부적합.

---

## R4. 단일 인스턴스 보장: PID 파일 + flock

**Decision**: `~/.local/share/remote-task/daemon.pid` 파일을 `fcntl.flock(LOCK_EX | LOCK_NB)`로 잠근다.
- daemon 시작 시: PID 파일 열고 비차단 락 시도 → 실패하면 기존 인스턴스로 간주, `EBUSY` 종료.
- PID 파일에 현재 PID 기록.
- daemon 종료 시: 락 해제 + PID 파일 삭제.
- stale 감지: `daemon status`는 PID 파일이 존재하지만 해당 PID 프로세스가 죽어 있으면 stale로 판단하고 자동 정리.

**Rationale**:
- POSIX 표준 + Python stdlib(`fcntl`)만 사용 → 추가 의존성 0.
- 락 + PID 동시 활용으로 **(a) 비정상 종료 후 락 자동 해제 + (b) 사용자 친화적 PID 노출** 둘 다 만족.
- macOS에서 `fcntl.flock`은 BSD flock 의미론으로 동작(파일 디스크립터 단위) → 정상 작동.

**Alternatives rejected**:
- `psutil` 기반 프로세스 검색 — 의존성 추가 가치 작음.
- `os.kill(pid, 0)` 단독 — 락이 없어 동시 실행 race condition 발생 가능.
- `tempfile`의 NamedTemporaryFile — 자동 정리 정책이 헷갈림.

---

## R5. structlog 구성

**Decision**:
- **포맷**: JSON 라인 (`structlog.processors.JSONRenderer`).
- **출력**: stderr + 파일(`logs/daemon.log`).
- **파일 로테이션**: `logging.handlers.RotatingFileHandler(maxBytes=10*1024*1024, backupCount=5)`.
- **레벨**: 기본 `INFO`, `--verbose`로 `DEBUG`.
- **공통 컨텍스트**: `logger = structlog.get_logger().bind(component="cli|daemon|...", session_id=..., issue_key=...)` 형태로 구조화.
- **TTY 감지**: 터미널이면 `ConsoleRenderer`(컬러), 비-TTY는 JSON으로 자동 전환.

**Rationale**:
- JSON 라인은 후속 단계(웹 UI 로그 뷰어·grep·jq)와 자연 호환.
- structlog는 stdlib `logging`과 인터페이스 호환 → 외부 라이브러리 로그도 같은 파이프라인에 합쳐짐.
- TTY/비-TTY 자동 전환으로 사용자 경험과 기계 가독성 둘 다 확보.

**Alternatives rejected**:
- 표준 `logging` 단독 — JSON 포맷 직접 작성 + context 바인딩 코드가 늘어남.
- `loguru` — 매력적이지만 stdlib 호환성이 떨어져 외부 라이브러리 로그가 분리됨.

---

## R6. 토큰 생성·회전·마스킹

**Decision**:
- **생성**: `secrets.token_urlsafe(32)` (256bit 이상 엔트로피).
- **저장**: `config.toml` 안에 평문 + 파일 권한 `0600`.
- **회전**: `remote-task config regenerate-token` 명령(이 feature가 자리만 마련, 실제 회전 로직은 동일).
- **마스킹**: 시크릿 분류 키(`telegram.bot_token`, `daemon.auth_token`)는 기본 `****<last4>` 표시. `--reveal` 플래그가 있을 때만 원문.
- **Keychain**: Phase 4 옵션으로 미룸. `config.toml`에서 `bot_token = "@keychain:remote-task.bot_token"` 같은 referencing 문자열을 처음부터 인식할 수 있도록 reader에 hook 자리만 준비(실 호출은 후속).

**Rationale**:
- 1인용에서 권한 0600 파일은 충분히 안전. Keychain은 가치는 있으나 macOS 종속성 + 재인증 UX 부담.
- `--reveal` 분리는 우발적 화면 공유·로그 노출 차단.
- referencing 문자열을 reader에서 인식하도록 만들면 후속에 코드 변경 없이 Keychain 통합 가능.

**Alternatives rejected**:
- 첫 단계부터 Keychain 강제 — 1인 셀프호스트의 단순성 원칙 위배(헌법 IV).
- 환경변수 단독 — launchd가 환경 상속을 하지 않아 부팅 시 토큰 누락.

---

## R7. dotted-path config get/set

**Decision**:
- 키 표기: `agent.max_concurrent`, `telegram.bot_token` 같은 dotted-path.
- 내부적으로 TOML을 dict 트리로 로드 → 키를 `.split(".")`로 따라가며 접근.
- 정의 가능한 키는 `pydantic` 모델(`ConfigSchema`)로 화이트리스트 강제.
- `set` 시 모델 재검증 → 실패 시 사용자에게 안내 후 거부.

**Rationale**:
- pydantic 모델은 타입·범위 검증을 자동화해주고 mypy 친화.
- 화이트리스트는 spec FR-022(정의되지 않은 키 거부)와 직결.
- TOML은 사람이 직접 편집할 수도 있으므로 round-trip 보존을 위해 `tomli` (읽기) + `tomli_w` (쓰기) 조합. 단, 쓰기 시 주석은 보존되지 않으므로 `init`이 처음 작성한 파일에는 `# 사용자가 손으로 편집해도 됩니다` 같은 헤더 주석을 넣지 않는다(쓰기로 손실됨). 대신 `config.toml.example`을 별도 제공.

**Alternatives rejected**:
- ConfigParser INI — TOML이 표준이고 표현력 우월.
- JSON — 사람이 편집하기 불편.
- YAML — 들여쓰기 사고 위험 + 추가 의존성.

---

## R8. CLI E2E 테스트 — subprocess 기반

**Decision**:
- pytest fixture에서 `subprocess.run([sys.executable, "-m", "remote_task", ...])`로 실제 진입점 호출.
- XDG 경로는 `monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))` 형태로 격리.
- daemon 라이프사이클 테스트는 `subprocess.Popen`으로 백그라운드 spawn → status/stop 검증 후 정리.

**Rationale**:
- typer의 `CliRunner`도 있으나 진짜 신호·PID·flock 동작을 검증하려면 실제 프로세스 spawn이 필요함.
- 테스트 격리를 환경변수로 제어하면 사용자 실 환경을 오염시키지 않음.

**Alternatives rejected**:
- `typer.testing.CliRunner` 단독 — daemon 라이프사이클 검증 불가.
- 모킹된 파일시스템 — `fcntl.flock` 같은 시스템 호출은 모킹이 어려움.

---

## R9. launchd 통합 테스트 전략

**Decision**:
- 단위 테스트: plist 렌더링 결과를 dict로 파싱(`plistlib`)해서 키·값 검증. `launchctl`은 mocking.
- 통합 테스트: 실제 `launchctl load/unload`는 CI/CD에서 돌릴 수 없으므로 **로컬 옵트인 테스트**로 분리 (`@pytest.mark.local_only`).
- 로컬 옵트인 테스트는 `pytest -m local_only`로만 실행되며 일반 `pytest`에서는 자동 skip.

**Rationale**:
- launchd 명령은 시스템 상태를 변경하므로 격리 어려움 + CI에서 root/agent 환경 제약.
- plist 렌더링·파싱은 충분히 단위 테스트 가능.
- 사용자 1인이 매 PR 전 한 번 `pytest -m local_only`로 검증하면 충분.

**Alternatives rejected**:
- 실제 `launchctl` 호출을 단위 테스트에 포함 — 시스템 상태 오염 + 격리 어려움.
- launchd 자체를 모킹하는 fake — 구현 비용 대비 가치 작음.

---

## R10. SC-002~SC-005 성능 검증 방법

| 지표 | 검증 방법 |
|---|---|
| SC-002 (`--help` < 1s) | `tests/integration/test_cli_help.py::test_help_under_1s`, `time.perf_counter()` |
| SC-003 (init < 3s) | `test_init_command.py::test_init_under_3s` |
| SC-004 (`daemon stop` < 5s) | `test_daemon_lifecycle.py::test_stop_under_5s` (Popen + SIGTERM 후 wait) |
| SC-005 (재부팅 후 30s 내 헬스) | 본 feature에서는 헬스 엔드포인트 미존재. **Phase 2에서 검증.** 본 feature는 launchd가 데몬을 띄우는 것까지만 검증 |

**Rationale**: SC-005는 헬스 응답 지표인데 본 feature는 HTTP 헬스 엔드포인트가 없으므로 부분 검증만 가능. 완전 검증은 Phase 2에서 자연스럽게 합쳐진다. spec의 SC-005는 **001-cli-bootstrap의 종료 조건이 아닌 후속 feature까지 누적된 종료 조건**으로 해석한다.

---

## 미해결 질문

없음. spec 단계의 [NEEDS CLARIFICATION] 0건이 그대로 유지된다.
