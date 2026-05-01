# Feature Specification: CLI Bootstrap

**Feature Branch**: `001-cli-bootstrap`
**Created**: 2026-05-01
**Status**: Draft
**Input**: User description: "CLI bootstrap with typer subcommands, XDG path layout, SQLite schema, and stub daemon entry point - foundation for installing and managing remotask on macOS"

## User Scenarios & Testing *(mandatory)*

> 각 사용자 스토리는 **독립적으로 실행·검증 가능한 작은 단위**로 분해되었다.
> 우선순위 순서대로 구현하면 매 단계마다 사용자가 직접 확인할 수 있는 산출물이 생긴다.

### User Story 1 - CLI 명령어가 설치되고 도움말이 표시된다 (Priority: P1)

사용자는 패키지 설치 후 터미널에서 `remotask` 명령을 호출할 수 있어야 하며, 사용 가능한 서브커맨드와 옵션을 도움말로 확인할 수 있어야 한다.

**Why this priority**: CLI 진입점이 없으면 다른 모든 기능에 접근할 수 없다. 모든 후속 스토리의 전제 조건.

**Independent Test**: 패키지를 설치(`uv tool install .`)한 뒤 `remotask --help`, `remotask --version`을 실행해 출력이 표시되면 통과.

**Acceptance Scenarios**:

1. **Given** 사용자가 패키지를 설치한 직후, **When** `remotask --version`을 실행하면, **Then** 현재 버전 문자열이 표준출력에 한 줄로 표시된다.
2. **Given** 사용자가 패키지를 설치한 직후, **When** `remotask --help`를 실행하면, **Then** `init`·`install`·`uninstall`·`daemon`·`config`·`login`·`sessions`·`projects` 서브커맨드가 모두 목록에 표시된다.
3. **Given** 사용자가 패키지를 설치한 직후, **When** 각 서브커맨드에 `--help`를 붙여 실행하면, **Then** 해당 서브커맨드의 사용법과 옵션이 표시된다.
4. **Given** 사용자가 존재하지 않는 서브커맨드(예: `remotask foo`)를 실행하면, **Then** 0이 아닌 종료 코드와 함께 알 수 없는 명령 메시지가 표시된다.

---

### User Story 2 - init 명령이 사용자 환경을 안전하게 부트스트랩한다 (Priority: P1)

사용자는 한 번의 명령으로 설정 파일·상태 디렉토리·데이터베이스·기본 토큰을 모두 준비할 수 있어야 한다.

**Why this priority**: 모든 후속 명령은 init이 만든 산출물에 의존한다. P1과 묶어 동등 우선순위로 둔다.

**Independent Test**: 빈 사용자 환경에서 `remotask init` 실행 후 (a) 표준 경로의 파일·디렉토리 존재, (b) DB 스키마 적용, (c) 설정 파일에 자동 생성된 토큰이 채워졌는지 확인.

**Acceptance Scenarios**:

1. **Given** XDG 경로에 어떤 파일도 없는 새 사용자, **When** `remotask init`을 실행하면, **Then**
   - `~/.config/remotask/config.toml`이 권한 `0600`으로 생성된다.
   - `~/.local/share/remotask/state.db`가 생성되고 정의된 스키마가 적용된다.
   - `~/.local/share/remotask/logs/` 디렉토리가 생성된다.
   - 자동 생성된 인증 토큰이 `config.toml`에 기록된다.
2. **Given** 이미 init이 끝난 사용자, **When** `remotask init`을 다시 실행하면, **Then** 기본값으로는 기존 파일을 보존하고 변경 없음을 보고한다.
3. **Given** 이미 init이 끝난 사용자, **When** `remotask init --force`를 실행하면, **Then** 기존 설정을 덮어쓰지만 데이터베이스의 사용자 데이터(sessions, projects)는 보존한다.
4. **Given** 디스크 쓰기 권한이 없는 위치를 가리키도록 환경이 잘못 설정된 사용자, **When** `remotask init`을 실행하면, **Then** 0이 아닌 종료 코드와 명확한 오류 메시지를 출력하고 부분 생성된 파일은 정리한다.

---

### User Story 3 - config 명령으로 설정을 조회·변경할 수 있다 (Priority: P2)

사용자는 텔레그램 토큰·허용 사용자 ID·max_concurrent 같은 설정을 명령행에서 안전하게 조회·변경할 수 있어야 한다.

**Why this priority**: 사용자가 설치 후 첫 단계에서 텔레그램 토큰을 등록해야 하므로 init 직후 가장 먼저 필요한 기능이다.

**Independent Test**: `remotask config set telegram.bot_token=...` 실행 → `remotask config get telegram.bot_token` 호출 → 동일 값 반환 → `config.toml`을 외부에서 열어도 동일 값 확인.

**Acceptance Scenarios**:

1. **Given** init이 완료된 사용자, **When** `remotask config get agent.max_concurrent`를 실행하면, **Then** 현재 값(예: `1`)이 출력된다.
2. **Given** init이 완료된 사용자, **When** `remotask config set agent.max_concurrent 2`를 실행하면, **Then** 설정 파일에 값이 반영되고 0 종료 코드로 성공한다.
3. **Given** 사용자가 정의되지 않은 키(예: `foo.bar`)를 set하려 하면, **Then** 명령은 거부되고 사용 가능한 키 목록을 안내한다.
4. **Given** 사용자가 잘못된 형식(예: max_concurrent에 문자열)을 set하려 하면, **Then** 명령은 거부되고 기대 형식을 안내한다.
5. **Given** 사용자가 시크릿 키(`telegram.bot_token`)를 get하면, **Then** 기본적으로 마스킹된 형태(`****1234`)로 표시되며, `--reveal` 플래그가 있을 때만 원문을 출력한다.

---

### User Story 4 - daemon이 포어그라운드 stub으로 기동·종료된다 (Priority: P2)

사용자는 `daemon run-foreground` 명령으로 데몬 프로세스를 직접 띄울 수 있어야 하며, `daemon status`/`daemon stop`으로 라이프사이클을 관리할 수 있어야 한다.

**Why this priority**: launchd 등록(P3) 전에 데몬이 단독 실행 가능함을 검증해야 한다. 비즈니스 로직은 후속 feature에서 추가하므로 이 단계는 PID/lock/정상 종료만 동작하는 stub.

**Independent Test**: 터미널 1에서 `remotask daemon run-foreground` 실행 → 터미널 2에서 `remotask daemon status`가 PID와 uptime을 보고 → `remotask daemon stop`으로 종료 → status가 "not running"을 보고.

**Acceptance Scenarios**:

1. **Given** init이 완료되고 데몬이 실행 중이 아닌 상태, **When** `remotask daemon run-foreground`를 실행하면, **Then** 프로세스가 포그라운드에서 실행되고 PID 파일이 생성된다.
2. **Given** 데몬이 이미 실행 중, **When** 또 다른 `remotask daemon run-foreground`를 실행하면, **Then** 락 충돌로 거부되고 0이 아닌 종료 코드와 기존 PID를 안내한다.
3. **Given** 데몬이 실행 중, **When** `remotask daemon status`를 실행하면, **Then** PID·uptime·상태(`running`)가 출력된다.
4. **Given** 데몬이 실행 중, **When** `remotask daemon stop`을 실행하면, **Then** 데몬에 SIGTERM이 전송되고 5초 이내 종료되며 PID 파일이 정리된다.
5. **Given** 데몬이 실행 중이 아님, **When** `remotask daemon status`를 실행하면, **Then** "not running" 상태와 0이 아닌 종료 코드가 반환된다.
6. **Given** 데몬이 비정상 종료되어 stale PID 파일이 남은 상태, **When** `remotask daemon status`를 실행하면, **Then** stale로 진단하고 자동 정리한 뒤 "not running"을 보고한다.

---

### User Story 5 - install/uninstall 명령으로 macOS launchd에 등록·해제된다 (Priority: P3)

사용자는 `remotask install` 한 번으로 부팅 시 자동 시작되는 launchd 에이전트를 등록할 수 있고, `remotask uninstall`로 깨끗이 제거할 수 있어야 한다.

**Why this priority**: 외출 중 트리거의 핵심 가치는 "노트북이 깨어 있는 한 항상 듣고 있다"이고, 이는 launchd 등록을 전제로 한다.

**Independent Test**: `remotask install` → `launchctl list | grep remotask`로 등록 확인 → 데몬 헬스 응답 확인 → `remotask uninstall` → 다시 list에서 사라짐 확인.

**Acceptance Scenarios**:

1. **Given** init이 완료된 사용자, **When** `remotask install`을 실행하면, **Then** `~/Library/LaunchAgents/`에 plist가 생성되고 `launchctl load`가 자동 실행되어 데몬이 즉시 시작된다.
2. **Given** install이 완료되어 데몬이 실행 중인 사용자, **When** 노트북을 재부팅하면, **Then** 로그인 후 데몬이 자동으로 다시 실행된다.
3. **Given** plist가 이미 등록된 상태, **When** `remotask install`을 다시 실행하면, **Then** 사용자 확인 후 plist를 갱신하고 데몬을 재시작한다.
4. **Given** install이 완료된 사용자, **When** `remotask uninstall`을 실행하면, **Then** `launchctl unload`가 실행되고 plist가 삭제되며 사용자 데이터(config·db·logs)는 보존된다.
5. **Given** install된 데몬에서, **When** plist에 정의된 환경변수가 누락되어 데몬이 실패하면, **Then** launchd가 정해진 정책으로 재시작을 시도하며 그 시도 사실이 로그에 기록된다.

---

---

### User Story 6 - 프로젝트 매핑(Jira project ↔ git repo)을 CLI로 관리할 수 있다 (Priority: P3)

사용자는 `projects add`로 Jira project key와 로컬 git repo 경로의 매핑을 등록하고, `projects list`로 확인하고, `projects remove`로 해제할 수 있어야 한다.

**Why this priority**: 후속 feature(`002-telegram-trigger`)는 issue key prefix(예: `ZXTL`)로부터 어느 git repo에서 worktree를 뽑을지 결정해야 하므로, 본 feature 안에서 매핑 등록이 가능해야 002 진입이 가능하다. install(US5)과 동일한 P3 우선순위.

**Independent Test**: init 후 `projects add ZXTL ~/Developments/zextool` → `projects list`에서 행 확인 → `projects remove ZXTL` → 다시 list에서 사라짐. 잘못된 key 형식·존재하지 않는 경로·중복 key는 거부.

**Acceptance Scenarios**:

1. **Given** init이 완료된 사용자(projects 비어있음), **When** `remotask projects list`를 실행하면, **Then** 빈 표 또는 "no projects yet" 메시지가 출력되고 종료 코드 0.
2. **Given** init이 완료된 사용자, **When** `remotask projects add ZXTL /Users/samuel/Developments/zextool`을 실행하면, **Then** projects 테이블에 행이 추가되고 종료 코드 0.
3. **Given** projects에 `ZXTL` 행이 있음, **When** 같은 키로 `add`를 다시 실행하면, **Then** 중복 거부 + 종료 코드 1.
4. **Given** init이 완료된 사용자, **When** 형식이 맞지 않는 key(예: `zxtl-1`, `Z`, `TOOLONGKEYNAME`)로 `add`를 실행하면, **Then** key 형식 오류 + 사용 가능한 형식 안내.
5. **Given** init이 완료된 사용자, **When** 존재하지 않는 경로로 `add`를 실행하면, **Then** 경로 오류 + 안내.
6. **Given** init이 완료된 사용자, **When** git repo가 아닌 경로(`.git` 부재)로 `add`를 실행하면, **Then** "git 저장소가 아닙니다" 오류.
7. **Given** projects에 행이 있음, **When** `remotask projects remove ZXTL`을 실행하면, **Then** 해당 행이 삭제되고 종료 코드 0.
8. **Given** 존재하지 않는 키로 `remove`를 실행하면, **Then** "등록되지 않은 키" 메시지 + 종료 코드 1.
9. **Given** projects에 여러 행이 있음, **When** `list`를 실행하면, **Then** jira_key·repo_path·base_branch·enabled 컬럼이 표 형태로 정렬 출력된다.

---

### Edge Cases

- **PATH 누락**: 사용자의 셸 환경에는 `claude` CLI가 PATH에 있지만 launchd 환경에는 없는 경우. install 명령이 사용자 PATH를 감지해 plist에 명시 기록한다.
- **HOME 미설정**: launchd가 `$HOME`을 빈 값으로 넘기는 경우. plist에서 명시 설정한다.
- **TOML 파싱 실패**: 사용자가 손으로 config.toml을 편집해 깨뜨린 경우. CLI는 라인·컬럼이 명시된 오류를 출력하고 종료한다.
- **DB 스키마 마이그레이션 실패**: 마이그레이션 도중 오류 발생 시 트랜잭션 롤백으로 이전 상태 유지 + 사용자에게 안내.
- **동시 init 호출**: 두 터미널에서 동시에 `init` 실행 시 한쪽만 성공하고 다른 쪽은 거부.
- **권한 부족**: `~/Library/LaunchAgents/` 쓰기 실패 시 명확한 오류 메시지.
- **uninstall 후 잔여 launchctl entry**: unload 실패 시 사용자에게 수동 정리 명령 안내.

## Requirements *(mandatory)*

### Functional Requirements

#### CLI 일반
- **FR-001**: 시스템은 단일 진입점(`remotask`)을 통해 모든 서브커맨드에 접근할 수 있게 해야 한다.
- **FR-002**: 시스템은 `--version`과 `--help` 전역 옵션을 지원해야 한다.
- **FR-003**: 모든 서브커맨드는 `--help`로 사용법을 출력해야 한다.
- **FR-004**: 알 수 없는 명령·옵션은 명확한 오류와 0이 아닌 종료 코드로 응답해야 한다.
- **FR-005**: 출력은 터미널 색상이 비활성된 환경(파이프·CI)에서도 가독성 있게 표시되어야 한다.

#### init / 환경 부트스트랩
- **FR-010**: 시스템은 XDG Base Directory 표준에 따라 설정·상태·캐시 경로를 결정해야 한다.
- **FR-011**: `init`은 표준 경로의 디렉토리 구조를 생성해야 한다.
- **FR-012**: `init`은 기본값과 자동 생성된 인증 토큰을 포함한 `config.toml`을 권한 `0600`으로 생성해야 한다.
- **FR-013**: `init`은 정의된 SQLite 스키마를 새 DB 파일에 적용해야 한다.
- **FR-014**: `init`은 멱등성을 가져야 한다(재실행 시 기존 파일 보존, `--force`로만 덮어쓰기).
- **FR-015**: `init`은 부분 실패 시 생성된 파일을 정리해야 한다.

#### config
- **FR-020**: `config get <key>`은 정의된 키의 현재 값을 출력해야 한다.
- **FR-021**: `config set <key> <value>`은 정의된 키에 한해 값을 갱신해야 한다.
- **FR-022**: 정의되지 않은 키에 대한 `set`은 거부되어야 하며 사용 가능한 키를 안내해야 한다.
- **FR-023**: 시크릿 키 카테고리는 기본 마스킹되어야 하며 `--reveal` 플래그가 필요해야 한다.
- **FR-024**: 값 형식 검증(타입·범위)이 실패하면 수정 가능한 안내가 표시되어야 한다.

#### daemon (stub 라이프사이클)
- **FR-030**: `daemon run-foreground`는 PID 파일을 생성하고 SIGTERM/SIGINT를 그레이스풀하게 처리해야 한다.
- **FR-031**: 동시에 둘 이상의 데몬이 실행되지 않도록 락(file lock)으로 보호되어야 한다.
- **FR-032**: `daemon status`는 살아있음 여부·PID·uptime을 보고해야 한다.
- **FR-033**: `daemon stop`은 SIGTERM 후 정해진 시간(5초) 안에 종료를 보장하고, 실패 시 SIGKILL로 강제 종료할 수 있어야 한다.
- **FR-034**: stale PID 파일은 자동 감지·정리되어야 한다.
- **FR-035**: 데몬은 구조화 로깅(JSON lines)을 표준 로그 디렉토리로 기록해야 한다.

#### install / uninstall (launchd)
- **FR-040**: `install`은 사용자 환경(`PATH`, `HOME`, 현재 인터프리터 경로)을 감지해 plist에 반영해야 한다.
- **FR-041**: `install`은 plist를 생성하고 `launchctl load`를 자동 실행해야 한다.
- **FR-042**: 이미 등록된 상태에서의 `install`은 사용자 확인 후 plist 갱신 + 데몬 재시작을 수행해야 한다.
- **FR-043**: `uninstall`은 `launchctl unload`와 plist 삭제를 수행해야 하며 사용자 데이터는 보존해야 한다.
- **FR-044**: launchd plist의 KeepAlive·RunAtLoad 정책은 비정상 종료 시 자동 재시작을 보장해야 한다.

#### projects (Jira ↔ repo 매핑 CRUD)
- **FR-060**: `projects list`는 활성·비활성 모든 행을 표 형태로 출력해야 하며 비어있을 때는 "no projects yet"을 안내해야 한다.
- **FR-061**: `projects add <jira-key> <repo-path>`은 jira-key가 정규식 `^[A-Z]{2,10}$`을 만족할 때만 허용해야 한다.
- **FR-062**: `projects add`는 repo-path가 실제로 존재하고 `.git` 디렉토리를 가진 git 저장소일 때만 허용해야 한다.
- **FR-063**: `projects add`는 동일 jira-key 중복 등록을 거부해야 한다.
- **FR-064**: `projects add`는 옵션 `--branch`로 base_branch를 지정할 수 있으며, 기본값은 `main`이어야 한다.
- **FR-065**: `projects remove <jira-key>`는 등록된 키만 삭제해야 하며 미등록 키는 명확한 메시지로 거부해야 한다.
- **FR-066**: 모든 projects 명령은 종료 코드와 메시지가 contracts/cli-commands.md §10과 일치해야 한다.

#### 헌법 준수
- **FR-050**: 모든 시크릿(토큰)은 `0600` 또는 더 엄격한 권한으로 저장되어야 한다(헌법 VI).
- **FR-051**: 모든 명령은 구조화 로그를 남겨 사후 추적이 가능해야 한다(헌법 VII).
- **FR-052**: 데몬은 클라이언트(향후 Telegram bot·웹 UI) 없이도 동작 가능하도록 독립 프로세스로 설계되어야 한다(헌법 II).
- **FR-053**: 시크릿 회전(token regeneration)·launchd install·uninstall은 audit 로그에 기록되어야 한다(헌법 VII).
- **FR-054**: SC-005(재부팅 후 30초 내 헬스 응답)는 본 feature에서는 launchd가 데몬 프로세스를 띄우는 단계까지만 검증되며, HTTP 헬스 엔드포인트 검증은 후속 feature(`002-telegram-trigger` 이후)로 이관된다.

### Key Entities

- **Config**: 사용자 설정의 저장 단위. 텔레그램·에이전트·경로 정보를 포함하며 시크릿 카테고리가 분리된다.
- **State Database**: 실행 메타데이터(sessions·projects·session_events·locks)와 스키마 버전 이력을 저장한다. 이 feature에서는 스키마 생성·버전 관리만 다루고 비즈니스 데이터는 후속 feature에서 채운다.
- **Daemon Process**: 단일 인스턴스로만 실행되는 백그라운드 프로세스. PID 파일과 file lock으로 단일성을 보장한다.
- **Auth Token**: 데몬 HTTP API 호출에 사용될 비밀 값. init 시 자동 생성되며 회전 가능해야 한다.
- **launchd Agent**: 사용자 로그인 시 자동 시작되는 OS 수준 등록 단위. plist 파일과 `launchctl` 등록 상태로 표현된다.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 신규 사용자가 첫 설치 후 5분 이내에 `init` → 토큰 등록 → `install`까지 완료하여 데몬이 자동 실행되는 상태에 도달할 수 있다.
- **SC-002**: 모든 CLI 명령은 도움말 응답을 1초 이내에 표시한다.
- **SC-003**: `init`은 빈 환경에서 3초 이내에 완료된다.
- **SC-004**: `daemon stop`은 정상 종료 신호 수신 후 5초 이내에 프로세스를 정리한다.
- **SC-005**: `install` 후 노트북 재부팅 시 로그인 후 30초 이내에 데몬 헬스가 정상 응답한다.
- **SC-006**: 잘못된 입력(존재하지 않는 키, 형식 오류)은 모두 사용자에게 수정 방법을 안내하는 메시지를 동반한다(즉, "그냥 실패함" 메시지가 한 건도 없다).
- **SC-007**: `config.toml`과 토큰 파일은 사후 점검에서 100% `0600` 이하 권한을 유지한다.
- **SC-008**: 동시 init·동시 daemon 실행을 시도해도 데이터 손상이 발생하지 않는다(반복 100회 검증).
- **SC-009**: `projects add`로 등록된 매핑은 즉시 `projects list`로 조회 가능하며, 잘못된 입력(형식·경로·중복)은 100% 안내 메시지를 동반해 거부된다.
- **SC-010**: ANSI 컬러 escape 시퀀스는 비-TTY 출력(파이프·CI)에서 검출되지 않는다.

## Assumptions

- 사용자는 macOS 사용자로 launchd 환경을 갖는다(Linux/Windows는 후속 단계).
- 사용자는 Python 3.11 이상이 설치된 환경을 가지며 `uv tool install`로 패키지를 설치한다.
- 사용자는 단일 사용자(1인 셀프호스트)이며 시스템 권한 모델은 단순(B2B 권한 모델 없음).
- `claude` CLI는 사용자의 PATH에 이미 설치·로그인되어 있으며 `claude-agent-sdk`가 그 자격을 상속한다(헌법 II).
- 본 feature는 데몬 stub만 다루며 Telegram bot·Agent SDK 실제 호출은 후속 feature(`002-telegram-trigger`, `003-agent-execution`)에서 추가한다.
- 본 feature는 웹 GUI를 포함하지 않는다(MVP 스코프, 헌법 IV).
