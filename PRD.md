# Remote Task — PRD

> 휴대폰에서 트리거하는 로컬 AI 에이전트 원격 실행 플랫폼.
> Jira 이슈를 받아 자동으로 구현·PR 생성까지 진행하고, 향후 웹 GUI로 모니터링한다.

- **Owner**: Samuel (acid@mission-driven.kr)
- **Status**: Draft v0.3
- **작성일**: 2026-05-01
- **마지막 갱신**: 2026-05-03
- **레퍼런스**: [multica-ai/multica](https://github.com/multica-ai/multica)

> 이 문서는 **제품 layer**의 진실 원천이다.
> "절대 어기지 않는 원칙"은 [`.specify/memory/constitution.md`](./.specify/memory/constitution.md),
> "현재 시스템 모습"은 [`ARCHITECTURE.md`](./ARCHITECTURE.md),
> "왜 이 시스템 구조를 골랐는가"는 [`ARD.md`](./ARD.md),
> "각 변경의 명세"는 [`specs/<feature>/`](./specs)가 SoT다.

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
- 트리거 채널은 Telegram, 모니터링 GUI는 향후 로컬 웹.
- 작업 결과는 GitHub PR로 출력되고, 최종 머지는 GitHub 모바일 앱에서 사람이 수행한다.

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
- 데스크탑 네이티브 앱(옵션, 후기 Phase에서 검토).
- iOS/Android 네이티브 클라이언트(Telegram + 모바일 브라우저로 충분).

### MVP 스코프 (★ 중요)
**MVP는 웹 GUI를 포함하지 않는다.** Telegram 트리거 + 데몬 + Agent SDK + Draft PR 생성까지가 MVP다.
구체적 포함/제외는 다음 표:

| 영역 | MVP 포함 여부 |
|---|---|
| Telegram bot (long-poll, forum topic, 화이트리스트) | ✅ MVP |
| 세션 라이프사이클 (단일 동시 세션) | ✅ MVP |
| Claude Agent SDK 실행 | ✅ MVP |
| `git worktree` 격리 + Draft PR 자동 생성 | ✅ MVP |
| typer CLI (init, install, daemon, sessions, projects) | ✅ MVP |
| launchd 등록 / 부팅 자동 시작 | ✅ MVP |
| 프로젝트 매핑 (config seed + DB) | ✅ MVP (CRUD는 CLI만) |
| FastAPI HTTP API + WebSocket | ⛔ Post-MVP (Phase 2) |
| React 웹 GUI (Dashboard / Session Detail / Projects / Skills / Settings) | ⛔ Post-MVP (Phase 2) |
| 다중 동시 세션 (`max_concurrent ≥ 2`) | ⛔ Post-MVP (Phase 3) |
| 양방향 인터랙션 (Telegram → SDK stdin) | ⛔ Post-MVP (Phase 3) |
| Tailscale·외부 노출 | ⛔ Post-MVP (Phase 4) |
| Tauri 데스크탑 셸 | ⛔ Post-MVP (Phase 5) |

---

## 3. 사용자 / 사용 시나리오

### Primary Persona
- **Samuel** — 1인 사용자. Claude Code Pro/Max 구독자. macOS 사용.
  Jira·GitHub·Telegram을 평소에 모두 사용 중.

### 핵심 사용자 시나리오

**[S1] 외출 중 버그 수정 트리거**
1. 카페에서 Slack으로 버그 리포트를 받는다.
2. Jira에 이슈를 생성한다(`ZXTL-1234`).
3. Telegram 봇 채팅에서 `/run ZXTL-1234`를 보낸다.
4. 봇이 worktree 생성, 컨텍스트 파악, 구현, 테스트를 자동 수행한다.
5. 첫 commit이 생기면 Draft PR을 자동 생성하고 PR 링크를 Telegram에 회신한다.
6. GitHub 모바일 앱에서 diff를 확인하고 머지한다.

**[S2] 진행 상황 모니터링**
1. 자리에 돌아와 노트북을 연다.
2. (Phase 2) 브라우저로 daemon 웹 UI를 연다.
3. 활성 세션 카드, 큐 대기 세션, 오늘 완료된 세션을 확인한다.
4. 특정 세션의 상세 페이지에서 turn-by-turn 로그를 확인한다.
5. 외출 중에 처리된 작업이 모두 PR 단계까지 가 있다.

**[S3] 신규 프로젝트 등록**
1. 새 git repo를 로컬에 클론한다.
2. (Phase 2) 웹 UI의 Projects 화면에서 [Add] 버튼을 누르거나, CLI로 `remotask projects add ABC <repo-path>`.
3. Jira project key(`ABC`)와 repo 경로를 등록한다.
4. 이후 `ABC-***` 이슈는 자동으로 해당 repo에서 처리된다.

**[S4] 다중 세션 동시 실행**
1. 출근길에 두 개의 이슈를 연속 트리거(`ZXTL-1234`, `ABC-89`).
2. 봇이 두 세션을 동시 실행(`max_concurrent` 범위 내).
3. 각 세션은 별도 worktree·별도 브랜치로 격리된다(헌법 §III).
4. 점심 즈음 둘 다 Draft PR로 도착한다.

**[S5] 진행 중 세션 종료**
1. 세션이 잘못된 방향으로 가고 있음을 PR 미리보기에서 발견.
2. 해당 세션의 토픽에서 `/cancel`을 보낸다.
3. 봇이 cooperative 종료 신호를 보내고, 응답 없으면 force kill.
4. worktree·브랜치는 사후 검사를 위해 보존되고, 세션은 `canceled` 상태로 남는다.

---

## 4. 단계별 로드맵

> 각 Phase의 구체적 task 분해는 `specs/<feature>/tasks.md`가 SoT다. 본 절은
> 제품 layer의 진척 마일스톤만 명시한다.

### Phase 0 — 인프라 셋업 ✅ 완료
- 디렉토리·`pyproject.toml` 골격, typer CLI 진입점
- XDG 경로, SQLite V0001 스키마, daemon shell, launchd 등록
- spec-kit 워크플로우 도입
- **근거 spec**: `specs/001-cli-bootstrap/`

### Phase 1 — Telegram 트리거 + Agent SDK 실행 ✅ 완료 (MVP)
- Telegram bot long-poll, 화이트리스트 인증, forum topic 자동 생성
- 평문 메시지 → issue key 추출 → 세션 시작
- 슬래시 커맨드 표면 (`/run`, `/cancel`, `/status`) + `setMyCommands`
- Cooperative SIGUSR1 → grace → SIGTERM/SIGKILL 종료 ladder
- `[<issue_key>]` prefix로 다중 세션 가독성
- Draft PR 자동 생성, Telegram에 PR 링크 회신
- 동시 실행 1개로 시작
- **🎯 MVP 완료 지점.** 추후 Phase는 MVP 가치 검증 후 점진적으로 추가.
- **근거 spec**: `specs/002-telegram-trigger/` ~ `specs/006-remove-termination-aliases/`

### Phase 2 — 웹 GUI ⛔ 예정
- FastAPI HTTP/WebSocket 서버 daemon 임베드
- React + Vite 프로젝트
- Dashboard / Session Detail / Projects / Skills / Settings
- daemon이 빌드된 React를 정적 서빙

### Phase 3 — 다중 세션 + 양방향 인터랙션 ⛔ 예정
- `max_concurrent` 상향 (2~3)
- advisory lock 도입(lockfile, DB 마이그레이션 등)
- Agent의 사용자 질문을 Telegram으로 forwarding, 답변을 stdin으로 주입
- 세션 재시작 후 복구 정책

### Phase 4 — 운영 안정화 ⛔ 옵션
- macOS Keychain 통합, 로그 로테이션·메트릭, Tailscale 가이드, `init` 마법사 정교화

### Phase 5 — 옵션 확장 ⛔ 필요 시점에
- Homebrew tap, Tauri 데스크탑 셸, Slack 채널, 팀 모드 등

---

## 5. 오픈 이슈 / 리스크

### 미해결 질문
- **Q1**: Agent SDK가 한국어 스킬(`/work-start` 등)을 그대로 실행 가능한가? → 검증 진행 중.
- **Q2**: launchd가 `claude` CLI의 PATH·환경변수를 정확히 상속하는가? → `install` 명령에서 환경 자동 감지·plist에 명시.
- **Q3**: Telegram forum group의 봇 권한(매니저)은 사용자가 수동으로 부여해야 하는가? → 그렇다, `init` 마법사에서 단계별 안내.
- **Q4**: 동시 세션이 같은 lockfile을 동시에 수정하는 시나리오의 빈도는? → 실측 후 advisory lock 도입 시점 결정 (Phase 3).

### 리스크
- **R1**: Claude Pro/Max의 사용량 한도 초과 시 daemon이 무한 재시도할 가능성 → exponential backoff + 한도 감지 시 사용자 통지.
- **R2**: launchd가 데몬을 죽였다 살리는 사이클에서 worktree·branch 잔재 누적 → 시작 시 stale 세션 정리 루틴.
- **R3**: Telegram bot token 노출 위험 → 권한 0600 + Keychain 옵션 (헌법 §VI).
- **R4**: 외부 노출(Tailscale 등) 시 토큰 탈취 위험 → 토큰 회전 명령 제공.
- **R5**: Jira 이슈 컨텍스트가 너무 부족해 Agent가 헛다리 짚을 가능성 → 사용자가 Telegram에서 추가 컨텍스트를 보낼 수 있는 흐름.

---

## 6. 확장 지향점 — 메신저·Agent 교체 가능성

> 본 절은 **현재 만들지 않는 것**을 명시하기 위한 지향점이다. 실제 어댑터·플러그인
> 인프라는 두 번째 구체 수요(다른 메신저 또는 다른 agent)가 발생할 때 spec을
> 통해 도입한다. 헌법 §IV "MVP-First" 정합.

### 파이프라인 모양 (현재)

```
[Messenger 서비스] ──▶ [remotask daemon] ──▶ [AI Agent subprocess]
   Telegram                                       claude-agent-sdk
   (Slack 등 추후)                                  (Codex 등 추후)
```

세 단계는 이미 분리돼 있다. 003부터 worker는 stdout protocol(현재 5종 라인 셰이프)
만 말하면 되는 별도 프로세스이고, 헌법 v1.1.0(ARD D19)은 Telegram 채널 매핑을
presentation-layer로 분리해 두었다.

### 비대칭한 교체 비용

- **AI Agent 교체 — 저비용**. `src/remotask/agent/<name>_worker.py`로 새 driver를
  추가하고 동일 stdout protocol(`PR_URL=` / `PROGRESS` / `FINAL` / `STEP` /
  `EVENT`)만 emit하면 daemon-side 변경은 거의 없다. config flag로
  `_default_worker_argv()`만 분기하면 된다. 신규 추상화 불필요.
- **Messenger 교체 — 고비용**. `dispatcher.py` / `listener.py` / `topic.py` /
  `runtime.py`에 Telegram 개념(forum topic, `message_thread_id`, Bot API,
  `setMyCommands`, bot_command entity)이 직접 박혀 있다. Slack 등을 붙이려면
  `MessengerAdapter` 인터페이스(receive_inbound · send_outbound ·
  create_session_channel · parse_command · format_session_label)를 추출하고
  dispatcher가 그 추상에만 의존하도록 뒤집어야 한다.

### 도입 트리거 (when, not now)

- **새 agent 도입 시점**: 사용자가 두 번째 agent(예: Codex CLI)를 1주 이상
  일상으로 쓰겠다는 결정이 있을 때. spec 한 개로 driver 추가 + config flag
  도입(짧은 feature). Adapter 같은 큰 추상화는 필요 없다.
- **새 messenger 도입 시점**: 두 번째 메신저(예: Slack)를 같은 의미에서 실제로
  쓰겠다는 결정이 있을 때, 또는 ARD D3에 약속된 Phase 5 진입 시. 그 시점에 spec
  으로 (a) MessengerAdapter 추출, (b) Telegram을 그 첫 구현체로 retrofit,
  (c) 두 번째 어댑터 추가 — 세 단계를 한 feature로 묶는 게 over-engineering이
  안 되는 가장 안전한 패턴. 첫 어댑터일 때 추상화하면 두 번째 어댑터의 실제
  요구사항을 모른 채 인터페이스를 박는다.

### 도입 전 / 후 invariants

- 헌법 §III(`1 issue = 1 worktree = 1 branch`)는 어떤 메신저·어떤 agent로도
  바뀌지 않는다.
- stdout protocol(007 super-set)은 agent-agnostic이며 늘어나기는 해도 줄어들지
  않는다.
- daemon은 GitHub API 자격증명을 보유하지 않는다(D5/Q1) — agent-side에서 PR
  생성, daemon은 URL relay만.

---

## 7. 참고 자료

- Multica: https://github.com/multica-ai/multica
- Claude Agent SDK (Python): `claude-agent-sdk`
- Telegram Bot API — Forum topics: https://core.telegram.org/bots/api#forum-topic-actions
- XDG Base Directory: https://specifications.freedesktop.org/basedir-spec/

---

## 8. 변경 이력

| 버전 | 날짜 | 작성자 | 내용 |
|---|---|---|---|
| 0.1 | 2026-05-01 | Samuel | 최초 초안 작성 |
| 0.2 | 2026-05-02 | Samuel | 5-layer 문서 분리: 아키텍처 정의를 `ARCHITECTURE.md`, 결정 로그를 `ARD.md`로 이동. 기능 요구사항 디테일·SQLite 스키마·HTTP API 명세는 spec/code SoT로 위임하고 PRD를 제품 layer 근간으로 슬림화. |
| 0.3 | 2026-05-03 | Samuel | §6 "확장 지향점" 추가 — Messenger·Agent 교체 가능성, 비대칭 교체 비용, 도입 트리거를 명시. 어댑터 인프라는 두 번째 구체 수요 시점까지 보류. |
