# Remote Task — PRD

> 휴대폰에서 트리거하는 로컬 AI 에이전트 원격 실행 플랫폼.
> Jira 이슈를 받아 자동으로 구현·PR 생성까지 진행하고, 웹 GUI로 모니터링한다.

- **Owner**: Samuel (acid@mission-driven.kr)
- **Status**: Draft v0.1
- **작성일**: 2026-05-01
- **레퍼런스**: [multica-ai/multica](https://github.com/multica-ai/multica)

---

## 1. 배경 (Why)

### 현재 상황
- 팀은 Jira로 태스크를 관리한다. 버그·수정 요청은 Jira 이슈로 등록된다.
- 작업자는 PC 앞에 있을 때만 Claude Code로 작업을 진행할 수 있다.
- 자리를 비운 동안에도 발생하는 단순·반복 작업이 누적된다.

### 문제
- 외출·이동 중에 들어온 Jira 이슈를 즉시 처리할 수 없다.
- PC 앞으로 돌아올 때까지 시작 시점이 지연된다.
- 단순 버그 수정처럼 컨텍스트가 자명한 작업도 동일한 지연을 겪는다.

### Multica를 채택하지 않는 이유
- 팀의 단일 진실 원천(SoT)이 Jira로 정해져 있다.
- Multica를 도입하면 Multica 워크스페이스 ↔ Jira 사이 **이중관리·싱크 비용**이 발생한다.
- 우리에게 필요한 건 워크스페이스/보드가 아니라 **원격 트리거 + 모니터링**뿐이다.

### 해결 방향
- Jira를 SoT로 그대로 두고, **로컬 PC의 Claude Code를 휴대폰에서 트리거**할 수 있는 얇은 자체 도구를 구축한다.
- 트리거 채널은 Telegram, 모니터링 GUI는 로컬 웹.
- 작업 결과는 GitHub PR로 출력되고, 최종 머지는 GitHub 모바일 앱에서 수행한다.

---

## 2. 목표 / 비목표

### 목표 (In-scope)
- Telegram 메시지로 Jira 이슈를 지정해 로컬 Claude Code 세션을 원격 시작할 수 있다.
- Jira 이슈 컨텍스트(제목·설명·댓글)를 자동으로 읽어 작업을 수행한다.
- 작업 결과를 자동으로 Draft PR로 생성하고 Telegram에 링크를 회신한다.
- 동시에 다수의 세션을 안전하게 실행할 수 있다(worktree 기반 격리).
- 로컬 웹 GUI로 활성/완료 세션, 로그, 프로젝트 매핑, 스킬 설정을 관리한다.
- 부팅 시 자동 시작되는 데몬으로 동작한다(launchd).
- CLI 한 명령으로 설치·기동·상태 확인이 가능하다.

### 비목표 (Out-of-scope)
- Jira의 대체 또는 보완 워크스페이스 제공.
- 멀티 사용자/팀 단위 권한 모델, 조직 관리 기능.
- 클라우드 호스팅·SaaS 형태 배포(1인 셀프 호스트 전제).
- 코드 머지 자동화(머지는 사용자가 GitHub 앱으로 수행).
- 데스크탑 네이티브 앱(Phase 5 이후 옵션으로 검토).
- iOS/Android 네이티브 클라이언트(Telegram + 모바일 브라우저로 충분).

### MVP 스코프 (★ 중요)
**MVP는 웹 GUI를 포함하지 않는다.** Telegram 트리거 + 데몬 + Agent SDK + Draft PR 생성까지가 MVP.

| 영역 | MVP 포함 여부 |
|---|---|
| Telegram bot (long-poll, forum topic, 화이트리스트) | ✅ MVP |
| 세션 라이프사이클 (단일 동시 세션) | ✅ MVP |
| Claude Agent SDK 실행 (`/work-start` → `/work-done`) | ✅ MVP |
| `git worktree` 격리 + Draft PR 자동 생성 | ✅ MVP |
| typer CLI (init, install, daemon start/stop/status, sessions list, projects add/list) | ✅ MVP |
| launchd 등록 / 부팅 자동 시작 | ✅ MVP |
| 프로젝트 매핑 (config.toml seed + DB) | ✅ MVP (CRUD는 CLI만) |
| SQLite 스키마 (sessions, projects, session_events, locks) | ✅ MVP |
| FastAPI HTTP API | ⛔ Post-MVP (Phase 2) |
| WebSocket 이벤트 스트림 | ⛔ Post-MVP (Phase 2) |
| React 웹 GUI | ⛔ Post-MVP (Phase 2) |
| Monaco 스킬 에디터 | ⛔ Post-MVP (Phase 2) |
| 폴더 트리 피커 | ⛔ Post-MVP (Phase 2) |
| 다중 동시 세션 (`max_concurrent ≥ 2`) | ⛔ Post-MVP (Phase 3) |
| 양방향 인터랙션 (Telegram → SDK stdin) | ⛔ Post-MVP (Phase 3) |
| Tailscale·외부 노출 | ⛔ Post-MVP (Phase 4) |
| Tauri 데스크탑 셸 | ⛔ Post-MVP (Phase 5) |

---

## 3. 사용자 / 사용 시나리오

### Primary Persona
- **Samuel** — 1인 사용자. Claude Code Pro/Max 구독자. macOS 사용. 평소에 Jira·GitHub·Telegram을 모두 사용 중.

### 핵심 사용자 시나리오

**[S1] 외출 중 버그 수정 트리거**
1. 카페에서 Slack으로 버그 리포트를 받는다.
2. Jira에 이슈를 생성한다(`ZXTL-1234`).
3. Telegram 봇 그룹의 적절한 topic에 `ZXTL-1234 작업 시작` 메시지를 보낸다.
4. 봇이 worktree 생성, 컨텍스트 파악, 구현, 테스트를 자동 수행한다.
5. 첫 commit이 생기면 Draft PR을 자동 생성하고 PR 링크를 Telegram에 회신한다.
6. GitHub 모바일 앱에서 diff를 확인하고 머지한다.

**[S2] 진행 상황 모니터링**
1. 자리에 돌아와 노트북을 연다.
2. 브라우저로 `http://127.0.0.1:6789`을 연다.
3. 활성 세션 카드, 큐 대기 세션, 오늘 완료된 세션을 확인한다.
4. 특정 세션의 상세 페이지에서 turn-by-turn 로그를 확인한다.
5. 외출 중에 처리된 작업이 모두 PR 단계까지 가 있다.

**[S3] 신규 프로젝트 등록**
1. 새 git repo를 로컬에 클론한다.
2. 웹 UI의 Projects 화면에서 [Add] 버튼을 누른다.
3. 폴더 트리 피커로 repo 위치를 선택한다.
4. Jira project key(`ABC`)를 입력한다.
5. 이후 `ABC-***` 이슈는 자동으로 해당 repo에서 처리된다.

**[S4] 다중 세션 동시 실행**
1. 출근길에 두 개의 이슈를 연속 트리거(`ZXTL-1234`, `ABC-89`).
2. 봇이 두 세션을 동시 실행(max_concurrent=2 범위 내).
3. 각 세션은 별도 worktree, 별도 Telegram topic, 별도 브랜치로 격리된다.
4. 점심 즈음 둘 다 Draft PR로 도착한다.

---

## 4. 아키텍처

### 컴포넌트 구성

```
                     ┌──────────────────┐
                     │  Telegram (모바일) │
                     └────────┬─────────┘
                              │ long-poll
                              ▼
   ┌────────────────────────────────────────────────────────┐
   │                Daemon (launchd, 항상 실행)              │
   │                                                        │
   │  ┌──────────────┐   ┌──────────────────┐              │
   │  │ Telegram Bot │──▶│ Command Router    │              │
   │  └──────────────┘   └────────┬──────────┘              │
   │                              ▼                          │
   │  ┌──────────────────────────────────────────┐          │
   │  │ Session Manager (큐, 동시성, lifecycle)   │◀──┐      │
   │  └────────┬──────────────────────────────────┘  │      │
   │           ▼                                     │      │
   │  ┌──────────────────────────────────────────┐  │      │
   │  │ Worker Pool (1 worker = 1 session)       │  │      │
   │  │  - git worktree                           │  │      │
   │  │  - Claude Agent SDK                       │  │      │
   │  │  - hook event 수집                        │  │      │
   │  └────────┬──────────────────────────────────┘  │      │
   │           │                                     │      │
   │           ▼                                     │      │
   │  ┌──────────────────────────────────────────┐  │      │
   │  │ Notifier (Telegram topic 단위 전송)      │  │      │
   │  └──────────────────────────────────────────┘  │      │
   │                                                 │      │
   │  ┌──────────────────────────────────────────┐  │      │
   │  │ FastAPI HTTP/WebSocket Server            │──┘      │
   │  │  - REST: /api/*                           │         │
   │  │  - WebSocket: /ws/events                  │         │
   │  │  - Static: /  (React 빌드 산출물 서빙)    │         │
   │  └──────────────────┬───────────────────────┘         │
   │                     │                                  │
   │  ┌──────────────────────────────────────────┐         │
   │  │ SQLite (sessions, queue, projects, locks)│         │
   │  └──────────────────────────────────────────┘         │
   └────────────────────┬───────────────────────────────────┘
                        │ HTTP (127.0.0.1:6789)
            ┌───────────┴───────────┐
            ▼                       ▼
     ┌────────────┐          ┌────────────┐
     │ Browser    │          │ remote-task│
     │ (Web UI)   │          │ CLI        │
     └────────────┘          └────────────┘
```

### 핵심 설계 원칙
- **Daemon은 단일 진실 원천**. CLI도 웹 UI도 모두 daemon의 HTTP API를 호출한다.
- **Daemon과 GUI는 독립 프로세스**. GUI를 닫아도 트리거 처리는 계속된다.
- **세션 = Jira issue 단위**. 1 issue → 1 worktree → 1 branch → 1 Telegram topic.
- **Jira는 SoT**. 자체 task 모델을 만들지 않는다. 우리 DB는 실행 메타데이터만 저장.

---

## 5. 기능 요구사항

### 5.1 Telegram 트리거
- Forum group의 topic에서 메시지 수신.
- 메시지 본문에서 Jira issue key를 정규식으로 추출(`[A-Z]{2,10}-\d+`).
- 사용자 ID 화이트리스트로 인증.
- 명령어: `/cancel`, `/status`, `/queue`.
- 봇이 자동으로 issue 단위 forum topic을 생성(매니저 권한 보유).

### 5.2 세션 라이프사이클
- **enqueued**: 큐 등록됨, 시작 대기.
- **starting**: worktree 생성 중.
- **running**: Claude Agent SDK 실행 중.
- **pr_created**: 첫 PR 생성됨(여전히 작업 진행 가능).
- **completed**: 정상 종료.
- **failed**: 오류로 종료.
- **canceled**: 사용자 취소.

### 5.3 Claude Agent SDK 실행
- 별도 API key 사용 안 함. `claude` CLI의 OAuth credential을 그대로 사용(Pro/Max 구독).
- `permission_mode="acceptEdits"`로 PR 생성·push까지 자동 허용.
- 초기 prompt는 기존에 구축된 `/work-start <issue-key>` 스킬 호출로 시작.
- 종료 시점에 `/work-done` 스킬을 호출하여 PR·Jira·Telegram을 정리.
- Hooks(`PostToolUse`, `Stop`)로 진행 이벤트를 daemon event bus에 publish.

### 5.4 다중 세션 / 동시성
- 기본 `max_concurrent_sessions = 2` (config로 조정).
- 초과 트리거는 큐에 대기, 자리 나면 자동 시작.
- 동일 issue 재트리거: 기존 세션이 active면 거부 + 사용자 confirm.
- 락이 필요한 자원(lockfile 변경, DB 마이그레이션)은 advisory lock으로 직렬화.

### 5.5 PR 워크플로우
- 첫 commit 발생 시점에 Draft PR을 자동 생성.
- Push마다 Telegram에 진행 알림(파일 수, +/- 라인 수).
- 작업 종료 시 Draft → Ready for review로 전환.
- 머지는 사용자가 GitHub 모바일 앱에서 직접 수행(자동화 안 함).

### 5.6 프로젝트 매핑
- Jira project key ↔ 로컬 git repo 경로 매핑.
- config.toml의 seed로 초기값 등록 가능.
- 웹 UI에서 CRUD 가능(`projects` 테이블).
- 매핑 없는 issue key는 거부 + Telegram에 안내.

### 5.7 웹 GUI ⛔ Post-MVP (Phase 2)
> MVP에 포함되지 않음. 모니터링·관리는 MVP에서 CLI(`remote-task sessions list` 등) + Telegram 알림으로 대체한다.

- **Dashboard**: 활성 세션, 큐 대기, 오늘 완료/실패, daemon 헬스.
- **Session Detail**: 메타 정보, turn-by-turn 로그(스트리밍), hook 이벤트 타임라인, worktree 경로, cancel 버튼.
- **Projects**: Jira key ↔ repo 매핑 CRUD, 폴더 트리 피커, base branch 설정.
- **Skills**: `~/.claude/skills/` 목록·편집(Monaco 에디터).
- **Settings**: Telegram 연결 상태, allowed user, max_concurrent, 토큰 재발급.

### 5.8 CLI 인터페이스
```
remote-task init                  # 인터랙티브 설정 마법사
remote-task install               # launchd plist 생성 + load
remote-task uninstall

remote-task daemon start          # 데몬 시작(launchd로 위임)
remote-task daemon stop
remote-task daemon status
remote-task daemon logs -f
remote-task daemon run-foreground # launchd가 호출하는 진입점

remote-task config get|set <key> [value]
remote-task login                 # Telegram 토큰·그룹 등록
remote-task ui                    # 브라우저로 GUI 열기

remote-task sessions list
remote-task sessions cancel <issue-key>

remote-task projects list
remote-task projects add <jira-key> <repo-path>
```

---

## 6. 비기능 요구사항

### 6.1 성능
- Telegram 메시지 → 세션 시작까지 5초 이내.
- 웹 UI 초기 렌더 1초 이내(로컬 환경 기준).
- WebSocket 이벤트 지연 200ms 이내.

### 6.2 안정성
- daemon 크래시 시 launchd가 자동 재시작.
- 재시작 후 진행 중 세션 복구 정책: 사용자에게 confirm 요청(자동 재실행 X).
- SQLite WAL 모드로 동시 읽기·쓰기.

### 6.3 보안
- daemon HTTP는 `127.0.0.1`에만 바인딩 기본.
- Bearer token 자동 생성, config.toml에 보관(권한 0600).
- Telegram bot token: macOS Keychain 저장 옵션 지원(`@keychain:` referencing).
- Telegram allowed user ID 화이트리스트 강제.
- 외부 노출(Tailscale 등)은 사용자가 명시적으로 활성화.
- `git push --force`, `rm -rf`, `git reset --hard` 등 위험 명령은 차단 목록.

### 6.4 관측성
- 구조화 로깅(JSON lines), `~/.local/share/remote-task/logs/`.
- 세션별 로그 파일 분리.
- 헬스체크 엔드포인트 `GET /api/health`.
- 로그 로테이션(10MB × 5).

---

## 7. 기술 스택

### 백엔드 (daemon)
- **Python 3.11+**, **uv** 패키지 매니저
- **typer** — CLI 프레임워크
- **FastAPI + uvicorn** — HTTP/WebSocket 서버 (daemon 내부 임베드)
- **python-telegram-bot** — Telegram long-poll
- **claude-agent-sdk** — Claude Code Agent SDK (CLI 인증 위임, 별도 API key 불필요)
- **SQLite + sqlalchemy** (또는 sqlite3 직접) — 상태 저장
- **GitPython** 또는 subprocess git — worktree 조작
- **structlog** — 구조화 로깅

### 프론트엔드 (web) ⛔ Post-MVP (Phase 2)
> MVP에서는 사용하지 않는다.

- **React 19 + Vite + TypeScript**
- **TanStack Query** — 서버 상태 관리
- **Tailwind CSS + shadcn/ui** — UI 컴포넌트
- **Monaco Editor** — 스킬 편집기
- **react-router** — 라우팅

### 배포·운영
- **launchd** — macOS 데몬 관리(plist는 `install` 명령이 동적 생성)
- **uv tool install .** — Phase 1 단일 사용자 설치
- 추후 검토: Homebrew tap, GitHub Releases install.sh

---

## 8. 디렉토리 구조

```
remote-task/
├── pyproject.toml
│   # [project.scripts] remote-task = "remote_task.cli:app"
├── README.md
├── .env.example
├── .gitignore
├── PRD.md                           ← 이 문서
│
├── src/remote_task/
│   ├── __init__.py
│   ├── cli.py                       ← typer app, 진입점
│   ├── config.py                    ← TOML 로드, XDG 경로
│   ├── paths.py                     ← XDG 헬퍼
│   ├── db.py                        ← SQLite 스키마/마이그레이션
│   │
│   ├── commands/                    ← typer 서브커맨드
│   │   ├── __init__.py
│   │   ├── init.py                  ← 설정 마법사
│   │   ├── install.py               ← launchd plist 생성/로드
│   │   ├── daemon.py                ← start/stop/status/logs/run-foreground
│   │   ├── config_cmd.py            ← config get/set
│   │   ├── login.py                 ← 토큰 등록
│   │   ├── ui.py                    ← 브라우저로 GUI 열기
│   │   ├── sessions.py              ← list/cancel
│   │   └── projects.py              ← list/add/remove
│   │
│   ├── daemon/                      ← 데몬 본체
│   │   ├── __init__.py
│   │   ├── runtime.py               ← bot + sm + api 가동
│   │   ├── lifecycle.py             ← PID, signal, lock
│   │   ├── api_server.py            ← FastAPI app
│   │   ├── api/                     ← REST 라우트
│   │   │   ├── health.py
│   │   │   ├── sessions.py
│   │   │   ├── projects.py
│   │   │   ├── skills.py
│   │   │   ├── fs.py                ← 폴더 트리 피커 백엔드
│   │   │   ├── logs.py
│   │   │   └── events_ws.py         ← WebSocket
│   │   └── event_bus.py
│   │
│   ├── core/                        ← 비즈니스 로직
│   │   ├── __init__.py
│   │   ├── bot.py                   ← Telegram 핸들러
│   │   ├── dispatcher.py            ← 메시지 → command 라우팅
│   │   ├── session_manager.py       ← 큐, lifecycle, 동시성
│   │   ├── worker.py                ← Agent SDK 실행
│   │   ├── notifier.py              ← Telegram topic 전송
│   │   ├── git_ops.py               ← worktree
│   │   └── jira.py                  ← Jira 컨텍스트 fetch (선택)
│   │
│   └── web/                         ← 빌드된 React 산출물 (포함 배포)
│       └── dist/                    ← gitignore, 빌드 시 채워짐
│
├── web/                             ← React 소스
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/                     ← daemon HTTP/WS 클라이언트
│       │   ├── client.ts
│       │   └── hooks.ts             ← TanStack Query 훅
│       ├── components/
│       │   ├── FolderPicker.tsx
│       │   ├── SessionCard.tsx
│       │   ├── LogStream.tsx
│       │   └── ...
│       ├── pages/
│       │   ├── Dashboard.tsx
│       │   ├── SessionDetail.tsx
│       │   ├── Projects.tsx
│       │   ├── Skills.tsx
│       │   └── Settings.tsx
│       └── styles/
│
├── templates/
│   └── launchd.plist.j2             ← install 명령이 렌더
│
└── tests/
    ├── test_dispatcher.py
    ├── test_session_manager.py
    └── ...
```

### 사용자 데이터 위치 (XDG)

```
~/.config/remote-task/config.toml             # 설정
~/.local/share/remote-task/state.db           # SQLite
~/.local/share/remote-task/logs/              # 세션 로그
~/.local/share/remote-task/daemon.pid         # PID
~/.cache/remote-task/                         # 캐시
```

---

## 9. 데이터 모델 (SQLite)

```sql
-- 프로젝트 매핑
CREATE TABLE projects (
  jira_key       TEXT PRIMARY KEY,
  repo_path      TEXT NOT NULL,
  base_branch    TEXT NOT NULL DEFAULT 'main',
  enabled        INTEGER NOT NULL DEFAULT 1,
  added_at       INTEGER NOT NULL,
  updated_at     INTEGER NOT NULL
);

-- 세션 (실행 인스턴스)
CREATE TABLE sessions (
  id             TEXT PRIMARY KEY,        -- uuid
  issue_key      TEXT NOT NULL,
  status         TEXT NOT NULL,           -- enqueued/starting/running/pr_created/completed/failed/canceled
  worktree_path  TEXT,
  branch         TEXT,
  pr_url         TEXT,
  pr_number      INTEGER,
  pid            INTEGER,
  topic_id       INTEGER,                 -- Telegram forum topic
  trigger_user   INTEGER,                 -- Telegram user id
  trigger_text   TEXT,                    -- 원본 메시지
  enqueued_at    INTEGER NOT NULL,
  started_at     INTEGER,
  ended_at       INTEGER,
  error_message  TEXT,
  log_path       TEXT
);

CREATE INDEX idx_sessions_issue ON sessions(issue_key);
CREATE INDEX idx_sessions_status ON sessions(status);

-- 세션 이벤트 (모니터링용)
CREATE TABLE session_events (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id     TEXT NOT NULL,
  type           TEXT NOT NULL,           -- log/tool_use/turn/pr_created/...
  payload        TEXT NOT NULL,           -- JSON
  created_at     INTEGER NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX idx_events_session ON session_events(session_id, created_at);

-- 자원 락
CREATE TABLE locks (
  resource       TEXT PRIMARY KEY,        -- e.g. "lockfile", "db-migration"
  holder_session TEXT,
  acquired_at    INTEGER
);

-- 스키마 버전 (마이그레이션)
CREATE TABLE schema_version (
  version        INTEGER PRIMARY KEY,
  applied_at     INTEGER NOT NULL
);
```

---

## 10. HTTP API 인터페이스 (초안)

### 인증
- 모든 요청에 `Authorization: Bearer <token>` 필수.
- 토큰은 `config.toml`에 자동 생성되어 보관됨.

### REST 엔드포인트

```
# 헬스
GET    /api/health

# 세션
GET    /api/sessions                   ?status=running&limit=50
GET    /api/sessions/{id}
POST   /api/sessions/{id}/cancel
GET    /api/sessions/{id}/events       ?since=<ts>
GET    /api/sessions/{id}/logs         (text/plain, tail 기본)

# 프로젝트
GET    /api/projects
POST   /api/projects                   { jira_key, repo_path, base_branch }
PATCH  /api/projects/{jira_key}        { enabled?, base_branch? }
DELETE /api/projects/{jira_key}

# 스킬
GET    /api/skills
GET    /api/skills/{name}
PUT    /api/skills/{name}              { content }
DELETE /api/skills/{name}

# 파일시스템 (폴더 피커용)
GET    /api/fs/list                    ?path=/Users/samuel/Developments

# 설정
GET    /api/config
PATCH  /api/config                     (부분 업데이트)
POST   /api/config/regenerate-token

# Telegram
GET    /api/telegram/status
POST   /api/telegram/test-message
```

### WebSocket

```
WS  /ws/events
    → 서버 push 메시지:
      { type: "session.started", session_id, issue_key }
      { type: "session.log", session_id, line }
      { type: "session.pr_created", session_id, pr_url }
      { type: "session.completed", session_id }
      { type: "session.failed", session_id, error }
      { type: "queue.changed", depth }
      { type: "daemon.health", uptime, ... }
```

---

## 11. 보안 / 권한 모델

### 신뢰 경계
- daemon은 사용자 권한으로 동작 → 사용자가 할 수 있는 모든 일을 할 수 있음.
- HTTP API는 단일 사용자 1개 토큰만 인정(B2B 권한 모델 없음).
- 외부 노출은 사용자가 Tailscale·Cloudflare Tunnel 등으로 명시 활성화.

### 차단 항목
- `rm -rf /` 등 절대 위험 패턴: Agent SDK 호출 시 `disallowed_tools` 또는 hook으로 거부.
- `git push --force`: 기본 차단, 명시적 옵션 시에만 허용.
- 외부 네트워크 호출 중 사용자 확인 필요한 것: hook으로 사용자 confirm 요청.

### 감사
- 모든 세션 시작 / 종료 / 실패는 `session_events`에 기록.
- 외부 네트워크 호출 / 파일 삭제 / git destructive 명령 등은 별도 audit 로그.

---

## 12. 단계별 로드맵

### Phase 0 — 인프라 셋업 (0.5일) ✅ MVP
- 디렉토리·`pyproject.toml` 골격 (Python 전용, 프론트 X)
- typer CLI 진입점 (모든 서브커맨드 빈 함수로)
- `init` / `install` / `daemon run-foreground` 최소 동작
- SQLite 스키마 + 마이그레이션
- spec-kit 기반 스펙 관리(`/speckit-*` 명령으로 진행)

### Phase 1 — Telegram 트리거 + Agent SDK 실행 (3~4일) ✅ MVP
- Telegram bot long-poll, 화이트리스트 인증
- Forum topic 자동 생성
- 메시지 → issue key 추출 → 세션 시작
- `git worktree add` + Agent SDK `query()` 실행
- `/work-start <key>` → `/work-done` 호출 흐름
- Draft PR 생성, Telegram에 PR 링크 회신
- **동시 실행 1개로 시작**(`max_concurrent=1`)
- 프로젝트 매핑은 config.toml + CLI(`projects add/list`)로만 관리
- launchd 등록, 부팅 시 자동 시작

> **🎯 여기까지가 MVP 완료 지점.** 이후 Phase는 MVP 가치 검증 후 점진적으로 추가.

### Phase 2 — 웹 GUI (4~5일)
- FastAPI HTTP/WebSocket 서버 daemon 임베드
- Bearer token 인증
- React + Vite 프로젝트 셋업
- Dashboard (활성 세션·큐·완료 카드)
- Session Detail (turn-by-turn 로그 스트림)
- Projects CRUD + 폴더 트리 피커
- Skills 편집기 (Monaco)
- Settings 페이지
- daemon이 빌드된 React를 정적 서빙

### Phase 3 — 다중 세션 + 양방향 인터랙션 (3~4일)
- `max_concurrent` 상향(2~3)
- advisory lock(lockfile, DB 마이그레이션 등)
- 세션 cancel
- Agent의 사용자 질문을 Telegram으로 forwarding, 답변을 stdin으로 주입
- 세션 재시작 후 복구 정책

### Phase 4 — 운영 안정화 (옵션)
- macOS Keychain 통합 (Telegram token)
- 로그 로테이션, 메트릭 노출
- Tailscale 통합 가이드(외부 접속)
- 설치 마법사 정교화(`init` 인터랙티브)
- 문서·README 정비

### Phase 5 — 옵션 확장 (필요 시점에)
- Homebrew tap 배포
- Tauri 데스크탑 셸 (네이티브 폴더 피커·트레이·딥링크)
- Slack 채널 추가 지원
- 팀 모드(다중 사용자)

---

## 13. 결정 로그 (Decision Log)

| # | 결정 | 사유 |
|---|---|---|
| D1 | 자체 워크스페이스 대신 Jira를 SoT로 유지 | 이중관리 비용 회피 |
| D2 | Telegram을 1차 트리거 채널로 채택 | 모바일 UX 즉시성, 1인 워크플로우 적합 |
| D3 | Slack은 Phase 5 옵션 | 1인 환경에서 불필요, 복잡도 증가 |
| D4 | Claude Agent SDK 채택 (`-p` 단발 모드 X) | 양방향 인터랙션·hook 이벤트 수집 필요 |
| D5 | 별도 API key 미사용 (CLI OAuth credential 위임) | Pro/Max 구독 그대로 활용 |
| D6 | macOS Keychain 사용 가능하지만 강제 X | 1인용 단순성 우선, 옵션화 |
| D7 | PR 자동 생성·push, 머지는 사람이 GitHub 앱에서 | 사용자 명시 요청 |
| D8 | 다중 세션은 worktree + Telegram forum topic으로 격리 | 컨텍스트 자연 분리 |
| D9 | 데스크탑 앱 대신 로컬 웹 채택 | daemon이 풀 권한 백엔드라 능력 동등, 모바일 접근 가능, 개발 속도 빠름 |
| D10 | 데스크탑은 Phase 5 옵션(Tauri로 같은 React 코드 래핑) | 수평 진화 경로 확보, 처음부터 도입은 1인용에 오버헤드 |
| D11 | Python 채택 | claude-agent-sdk + telegram lib 모두 성숙, 데몬 적합 |
| D12 | XDG 디렉토리 표준 채택 | 추후 패키징·배포 친화적 |
| D13 | typer 서브커맨드 구조를 처음부터 도입 | 추후 CLI 확장 시 갈아엎음 방지 |
| D14 | IPC를 Unix socket 대신 HTTP로 통일 | CLI·웹 UI·Telegram 봇이 동일 API 사용 → 추상화 한 단 |
| D15 | daemon과 GUI 프로세스 분리 | GUI 닫혀도 트리거 처리 지속 |
| D16 | 동시 실행은 Phase 3로 미룸(Phase 1은 1개로 시작) | 큐·락·격리를 충분히 검증 후 확장 |
| D17 | MVP에서 웹 GUI 제외 | 핵심 가치(원격 트리거)를 먼저 검증. 모니터링은 CLI + Telegram으로 충분 |
| D18 | spec-kit(speckit) 도입, `/speckit-*` 명령으로 스펙 주도 개발 | PRD → spec → plan → tasks → implement 흐름 표준화, AI 협업 친화적 |

---

## 14. 오픈 이슈 / 리스크

### 미해결 질문
- **Q1**: Agent SDK가 한국어 스킬(`/work-start` 등)을 그대로 실행 가능한가? → Phase 0에서 1차 검증 필요.
- **Q2**: launchd가 `claude` CLI의 PATH·환경변수를 정확히 상속하는가? → `install` 명령에서 환경 자동 감지·plist에 명시.
- **Q3**: Telegram forum group의 봇 권한(매니저)은 사용자가 수동으로 부여해야 하는가? → 그렇다, `init` 마법사에서 단계별 안내.
- **Q4**: 동시 세션이 같은 lockfile을 동시에 수정하는 시나리오의 빈도는? → 실측 후 advisory lock 도입 시점 결정.

### 리스크
- **R1**: Claude Pro/Max의 사용량 한도 초과 시 daemon이 무한 재시도할 가능성. → exponential backoff + 한도 감지 시 사용자 통지.
- **R2**: launchd가 데몬을 죽였다 살리는 사이클에서 worktree·branch 잔재 누적. → 시작 시 stale 세션 정리 루틴.
- **R3**: Telegram bot token 노출 위험. → 권한 0600 + Keychain 옵션.
- **R4**: 외부 노출(Tailscale 등) 시 토큰 탈취 위험. → 토큰 회전 명령(`config regenerate-token`) 제공.
- **R5**: Jira 이슈 컨텍스트가 너무 부족해 Agent가 헛다리 짚을 가능성. → Phase 1은 사용자가 Telegram에서 추가 컨텍스트를 보낼 수 있는 흐름 포함.

---

## 15. 참고 자료

- Multica: https://github.com/multica-ai/multica
- Claude Agent SDK (Python): `claude-agent-sdk`
- python-telegram-bot: https://python-telegram-bot.org/
- Telegram Bot API — Forum topics: https://core.telegram.org/bots/api#forum-topic-actions
- XDG Base Directory: https://specifications.freedesktop.org/basedir-spec/

---

## 16. 변경 이력

| 버전 | 날짜 | 작성자 | 내용 |
|---|---|---|---|
| 0.1 | 2026-05-01 | Samuel | 최초 초안 작성 |
