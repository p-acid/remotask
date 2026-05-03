# Architecture

> 현재 시점 시스템 정의. 이 문서는 "무엇이 어떻게 생겼는가"에 답한다.
> "왜 이렇게 결정했는가"는 [`ARD.md`](./ARD.md), "무엇을 만드는가"는
> [`PRD.md`](./PRD.md), "어떤 원칙은 절대 어기지 않는가"는
> [`.specify/memory/constitution.md`](./.specify/memory/constitution.md).

---

## 1. System overview

remotask는 **macOS launchd로 관리되는 단일 daemon 프로세스**다. 이 프로세스가
모든 비즈니스 로직과 시스템 권한을 보유하며, 다른 모든 표면(CLI, Telegram bot,
향후 웹 UI)은 daemon의 클라이언트로만 동작한다.

```
                       ┌──────────────────┐
                       │   Telegram        │
                       │   (mobile / desk) │
                       └────────┬──────────┘
                                │ Bot API long-poll (HTTPS)
                                ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                  remotask daemon (launchd)                   │
   │                                                              │
   │   ┌──────────────┐    ┌──────────────────┐                  │
   │   │  Listener    │───▶│   Dispatcher      │                 │
   │   │  (asyncio)   │    │  (slash + plain)  │                 │
   │   └──────────────┘    └────────┬──────────┘                 │
   │                                │                             │
   │                                ▼                             │
   │   ┌──────────────────────────────────────────┐              │
   │   │  Session lifecycle (sessions.py)          │              │
   │   │   enqueued → starting → running           │              │
   │   │     → {pr_created, completed, canceled,   │              │
   │   │        failed}                             │              │
   │   └────────┬─────────────────────────────────┘              │
   │            │                                                  │
   │            ▼                                                  │
   │   ┌──────────────────────────────────────────┐              │
   │   │  Worker (asyncio.create_subprocess_exec) │              │
   │   │   - git worktree                           │              │
   │   │   - claude-agent-sdk subprocess            │              │
   │   │   - PROGRESS / FINAL stdout protocol       │              │
   │   │   - SIGUSR1 → grace → SIGTERM/SIGKILL     │              │
   │   └────────┬─────────────────────────────────┘              │
   │            │                                                  │
   │            ▼                                                  │
   │   ┌──────────────────────────────────────────┐              │
   │   │  Topic poster (sessions.py / topic.py)    │              │
   │   │   - format_progress(issue_key, body)      │              │
   │   │     ⇒ "[<issue_key>] <body>"              │              │
   │   └──────────────────────────────────────────┘              │
   │                                                              │
   │   ┌──────────────────────────────────────────┐              │
   │   │  SQLite (V0001):                          │              │
   │   │   sessions / session_events /             │              │
   │   │   projects / locks                        │              │
   │   └──────────────────────────────────────────┘              │
   │                                                              │
   │   ┌──────────────────────────────────────────┐              │
   │   │  audit.log (append-only JSON lines)       │              │
   │   └──────────────────────────────────────────┘              │
   └─────────────────────────────────────────────────────────────┘
                       ▲
                       │ (Phase 2: HTTP API on 127.0.0.1:6789)
                  ┌────┴─────┐
                  │ remotask │
                  │   CLI    │
                  └──────────┘
```

Phase 2의 HTTP/WebSocket API와 React 웹 GUI는 위 다이어그램의 daemon 외부에
얹히는 형태로 설계됐으며, 현재(Phase 1) 시점에는 미구현이다. PRD §2 MVP 표 참조.

## 2. Component responsibilities

| 모듈 | 위치 | 책임 |
|------|------|------|
| **CLI** | `src/remotask/cli.py`, `src/remotask/commands/` | 사용자가 직접 호출하는 typer subcommand. daemon 기동/중지/상태, 설정, 프로젝트 매핑. |
| **Listener** | `src/remotask/daemon/listener.py` | Telegram Bot API long-poll. 인바운드 message를 dispatcher로 넘긴다. |
| **Dispatcher** | `src/remotask/daemon/dispatcher.py` | 메시지 → 의도 분기. 화이트리스트 게이트, slash-command branch (`/run`/`/cancel`/`/status`), 평문 issue-key 트리거 branch, 거부 경로 audit. |
| **Session lifecycle** | `src/remotask/daemon/sessions.py` | 상태 전이, topic_id 바인딩, lock acquisition/release, 토픽 메시지 포스팅 chokepoint. |
| **Worker** | `src/remotask/daemon/worker.py` | git worktree 생성, agent subprocess spawn, PROGRESS/FINAL/STEP/EVENT stdout 파싱, SIGUSR1 그레이스 래더, 종료 transition. |
| **SDK driver** | `src/remotask/agent/sdk_worker.py` | claude-agent-sdk 호출 wrapper (007). `/work-start <key>` 초기 prompt 송신, PostToolUse/Stop 훅을 STEP/EVENT 라인으로 변환, PreToolUse 훅으로 헌법 §VI deny-list 강제, SIGUSR1 → `client.interrupt()` 협조적 종료. |
| **Topic formatter** | `src/remotask/daemon/topic.py` | `format_progress(issue_key, body)` 단일 chokepoint로 모든 세션-바운드 outbound 메시지에 `[<issue_key>]` prefix 부여 + 표준 템플릿 보유. |
| **Telegram client / parser / commands** | `src/remotask/telegram/` | Bot API 호출, 메시지 파싱(`extract_first_issue_key`, `match_slash_command`), `setMyCommands` 큐레이션 셋. |
| **Audit** | `src/remotask/daemon/audit.py` | 세션-바운드 이벤트는 `session_events` 테이블, 비-바운드(거부·인증 실패)는 `audit.log`로 분리. |
| **Runtime** | `src/remotask/daemon/runtime.py` | listener 스레드, asyncio loop, signal handler, in-memory state (`operator_stop_in_flight` 셋, `worker_pid_by_session` 맵). |
| **Core libs** | `src/remotask/core/` | config schema (pydantic), XDG paths, SQLite connection/migration, structlog 셋업. |

## 3. Process & data layout

**프로세스**
- 단일 daemon 프로세스. launchd가 PID 관리.
- listener는 별도 thread, asyncio loop를 그 thread 안에서 운영.
- worker는 daemon이 spawn하는 자식 프로세스 (별도 PID, process group).

**데이터** (XDG)
- `~/.config/remotask/config.toml` — 설정 (0600).
- `~/.local/share/remotask/state.db` — SQLite WAL.
- `~/.local/share/remotask/logs/audit.log` — append-only audit.
- `~/.local/share/remotask/logs/session-<id>.log` — 세션별 stdout/stderr.
- `~/.local/share/remotask/daemon.pid` — flock 기반 단일 인스턴스 보장.
- `<worktree_root>/<issue_key>` — 세션 격리 worktree (config의 `agent.worktree_root`).

## 4. Concurrency & isolation model

**격리 단위 (헌법 §III, v1.1.0 이후)**
- `1 Jira issue = 1 git worktree = 1 git branch.` 파일시스템·git 상태 격리.
- Telegram 채널 매핑(forum topic)은 presentation-layer 결정으로, 헌법적
  격리 모델의 일부가 아니다. 현재 구현은 forum-topic 모델 유지.

**동시성 가드**
- `max_concurrent_sessions` (config, 기본 1) — 초과 트리거는 거부.
- 동일 issue 재트리거 — 활성 세션 있으면 거부 + 안내.
- `locks` 테이블 — 공유 자원(lockfile, DB 마이그레이션 등) advisory lock.
- `_operator_stop_in_flight` 셋 (in-memory) — `/cancel` 1회 보장 의미론.

## 5. Operator control plane (Telegram)

**큐레이션된 슬래시 셋** (`setMyCommands`로 BotFather UI에 노출):
- `/run <issue-key | free-text>` — 세션 시작
- `/cancel` — 활성 세션 종료 (토픽 안에서)
- `/status` — 활성 세션 목록 (메인 챗) / 토픽 상세 (토픽 안)

**메시지 처리 우선순위** (dispatcher):
1. 화이트리스트 게이트
2. 슬래시 커맨드 — 큐레이션 셋에 있으면 핸들러, 없으면 `slash_command_rejected reason=unknown_command`
3. 평문 issue-key 트리거 — 정규식 매치 시 accept-trigger 흐름
4. 그 외 평문 — 일반 채팅으로 무시 (control 동작 없음)

**종료 ladder** (`/cancel` 또는 worker timeout):
1. SIGUSR1 (cooperative)
2. `operator_stop_grace_seconds` 동안 대기
3. SIGTERM (process group)
4. 5초 후 SIGKILL

**메시지 형식**
- 모든 세션-바운드 outbound 메시지는 `topic.format_progress(issue_key, body)`을
  통과해 `[<issue_key>] <body>` 형식으로 발송된다 (005 / FR-011).

## 6. State machine — `sessions.status`

```
   enqueued ──▶ starting ──▶ running ──┬─▶ pr_created ──▶ completed
                                        ├─▶ completed
                                        ├─▶ canceled
                                        └─▶ failed
```

전이는 모두 `sessions.transition(...)`을 거치며, 각 전이는 `state_transition`
이벤트로 `session_events`에 기록된다.

## 7. Tech stack (current)

- **언어/런타임**: Python 3.11+, uv 패키지 매니저
- **CLI**: typer
- **HTTP**: httpx (Telegram client)
- **Agent**: claude-agent-sdk (CLI OAuth credential 위임, 별도 API key 불필요). 007부터 production path가 `remotask.agent.sdk_worker`를 통해 SDK를 직접 구동(`demo_worker`는 003-style 회귀 테스트용으로만 잔존).
- **데이터**: SQLite (V0001 schema), WAL mode
- **로깅**: structlog (JSON lines)
- **데몬 관리**: launchd (macOS)
- **테스트**: pytest, pytest-asyncio, pytest-cov

Phase 2 도입 예정: FastAPI + uvicorn (HTTP/WebSocket), React 19 + Vite + Tailwind.

## 8. Spec-kit-driven evolution

본 시스템은 spec-kit 워크플로우(`/speckit-specify` → `/speckit-plan` →
`/speckit-tasks` → `/speckit-implement`)를 따라 점진적으로 진화한다. 현재
머지된 feature stack은 다음과 같다:

| feature | 핵심 결과물 |
|---------|-------------|
| `001-cli-bootstrap` | typer CLI, XDG 경로, V0001 스키마, daemon shell, launchd 등록 |
| `002-telegram-trigger` | Listener, dispatcher, topic 생성, audit, worker scaffolding |
| `003-e2e-demo` | placeholder worker, operator-stop ladder, FINAL line 프로토콜 |
| `004-slash-commands` | `setMyCommands`, `/run` grammar, `/status`, slash-command dispatch |
| `005-dm-channel` | `/cancel` 캐노니컬, `[<issue_key>]` prefix chokepoint, 별칭 deprecation |
| `006-remove-termination-aliases` | deprecation 별칭 4개 완전 제거 |
| `007-agent-sdk-integration` | placeholder `demo_worker` → 진짜 claude-agent-sdk driver(`agent/sdk_worker.py`), STEP/EVENT 라인 셰이프 super-set, driver-level deny-list 훅, agent-side Draft PR 생성 |

각 feature의 spec/plan/research/data-model/contracts/quickstart는
`specs/<feature>/` 아래에 보존되며, 이 문서들이 해당 시점의 SoT다.

## 9. What lives where (summary)

| 알고 싶은 것 | 보는 곳 |
|--------------|---------|
| 절대 어기지 않는 원칙 | `.specify/memory/constitution.md` |
| 제품의 정체성·MVP 범위·시나리오 | `PRD.md` |
| **현재 시스템 모습 (이 문서)** | `ARCHITECTURE.md` |
| **시스템 결정의 이유 (D1, D2, …)** | `ARD.md` |
| 구체 변경 명세 / 회귀 테스트 의도 | `specs/<feature>/` |
| 현재 active plan 포인터 (AI agent용) | `CLAUDE.md` |
| 외부 사용자 onboarding | `README.md` |
| 코드 그 자체 | `src/remotask/` |
