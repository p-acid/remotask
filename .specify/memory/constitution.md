<!--
SYNC IMPACT REPORT
==================
Version change: 1.0.0 → 1.1.0
Bump rationale: Principle III ("Strict Session Isolation") relaxed to remove
  the Telegram-topic dimension from the constitutional invariant. The 1:1:1:1
  mapping becomes 1:1:1 (issue = worktree = branch); the Telegram channel
  correspondence (DM thread, forum topic, future surfaces) moves to the
  presentation layer. MINOR per the project's amendment policy because no
  principle is removed and the change is additive guidance (the relaxation
  *expands* the set of valid implementations rather than narrowing it).

Modified principles:
  - III. Strict Session Isolation: invariant changed from
    "1 Jira issue = 1 git worktree = 1 git branch = 1 Telegram forum topic"
    to "1 Jira issue = 1 git worktree = 1 git branch". Telegram-channel
    mapping is now presentation-layer.

Added sections:
  - None.

Removed sections:
  - None.

Templates requiring updates:
  - ✅ .specify/memory/constitution.md          (this file, amended)
  - ✅ .specify/templates/plan-template.md       (Constitution Check III line
       updated to drop the Telegram-topic dimension)
  - ✅ .specify/templates/spec-template.md       (no constitution-specific
       sections; alignment OK)
  - ✅ .specify/templates/tasks-template.md      (no constitution-specific
       sections; alignment OK)
  - ✅ CLAUDE.md                                 (no principle references;
       generic guidance only)
  - ✅ PRD.md                                    (still aligns; the §C "1
       issue = 1 topic" decision is a presentation policy and is the part
       being relaxed by 005)

Follow-up TODOs:
  - None.
-->

# Remote Task Constitution

## Core Principles

### I. Jira as Single Source of Truth (NON-NEGOTIABLE)

Jira는 모든 task·이슈의 단일 진실 원천이다.

- 자체 task / issue / workspace 도메인을 모델링하지 않는다.
- 작업 컨텍스트(제목·설명·댓글·상태)는 항상 Jira에서 fetch하며, 로컬에 영구 복제하지 않는다.
- 우리 SQLite는 **실행 메타데이터만** 저장한다(sessions, projects, locks, events).
- Jira와 우리 시스템의 정보가 충돌하면 Jira가 우선이다.

**근거**: Multica·자체 워크스페이스를 도입하지 않는 이유 그 자체. 이중관리·싱크 비용은 1인 셀프호스트 도구가 감당할 수 없다.

### II. Daemon-Centric Architecture

비즈니스 로직과 시스템 권한은 모두 daemon에 위치한다.

- CLI·웹 UI(Phase 2~)·Telegram bot은 모두 **daemon HTTP API의 클라이언트**다.
- daemon은 launchd가 관리하는 독립 프로세스이며, 어떤 클라이언트가 살아있는지와 무관하게 동작한다.
- 파일시스템·git·외부 호출은 daemon만 수행한다. 클라이언트는 명령·표시만.
- 인증은 daemon 진입점 단일 지점에서 강제한다(Bearer token + Telegram 화이트리스트).

**근거**: GUI를 닫아도 텔레그램 트리거 처리가 끊기지 않아야 하고, 모든 실행 경로가 동일한 추상화를 통과해야 일관성·감사가 가능하다.

### III. Strict Session Isolation (NON-NEGOTIABLE)

세션 격리는 **1:1:1 매핑**을 강제한다 (presentation 채널은 별도 layer).

- **1 Jira issue = 1 git worktree = 1 git branch.**
- 동시 실행되는 세션은 파일시스템·git 컨텍스트가 완전히 격리된다.
- 공유 자원(lockfile, DB 마이그레이션, 패키지 설치)에 영향을 주는 작업은 advisory lock으로 직렬화한다.
- 동일 issue 재트리거는 기존 세션이 active이면 거부하거나 명시적 takeover만 허용한다.
- **Telegram 채널 매핑**(1:1 DM 스레드, 그룹 forum topic, 향후 web UI 등)은 presentation-layer 결정이며 헌법적 격리 모델의 일부가 아니다. 단, 채택된 매핑은 feature spec에 명시되어야 하고 audit 추적이 가능해야 한다.

**근거**: 무인 실행 환경에서 컨텍스트 누수·작업 손실은 즉시 신뢰를 무너뜨린다. 격리의 본질은 파일시스템·git 상태이며, Telegram 채널 매핑은 UX 결정이라 분리되어 진화할 수 있어야 한다(예: 002~004의 forum-topic 모델 → 005의 1:1 DM 모델 전환). 단일 동시 실행이라도 worktree·branch 격리는 처음부터 강제되어야 한다.

### IV. MVP-First, Incremental Hardening

각 Phase는 명시적 진입·종료 기준을 가지며, 검증되지 않은 가치에 인프라를 미리 투자하지 않는다.

- 핵심 가치(원격 트리거)를 최단 경로로 검증하는 것이 MVP의 정의다.
- Phase 1(MVP) 완료 전에는 다음을 도입하지 않는다:
  - 다중 동시 세션(`max_concurrent ≥ 2`)
  - 웹 GUI / 모니터링 대시보드
  - 외부 노출(Tailscale, Cloudflare Tunnel)
  - 데스크탑 앱(Tauri 등)
  - Slack 등 대체 채널
- 새로운 Phase 진입은 이전 Phase의 가치 검증을 전제로 한다.
- "혹시 나중에 필요할까봐"는 거부 사유로 충분하다.

**근거**: 1인 도구에서 미리 만든 인프라는 곧 유지비용이다. PRD §12 로드맵·D17 결정에 부합.

### V. Spec-Driven Development

모든 의미 있는 변경은 spec → plan → tasks → implement 흐름을 따른다.

- 새 feature는 `/speckit-specify`로 시작한다.
- 즉흥(off-spec) 구현은 금지한다. 단순 버그 픽스(< 30분, 1 파일 이내)만 예외다.
- spec과 구현은 같은 PR에서 함께 리뷰된다.
- spec이 없으면 review · merge되지 않는다.
- AI agent가 자동 실행하는 모든 비-trivial 작업은 spec을 가져야 한다.

**근거**: 무인 실행 환경에서 의도와 구현의 추적 가능성은 안전성의 전제다. PRD §13 D18에 부합.

### VI. Security by Default

기본값은 가장 안전한 설정이며, 위험은 사용자의 명시적 행동을 통해서만 활성화된다.

- daemon HTTP는 `127.0.0.1` 단일 바인딩이 기본. 외부 노출은 사용자 명시 활성화.
- 모든 토큰·비밀은 권한 0600 파일 또는 macOS Keychain.
- Telegram 사용자 ID 화이트리스트는 강제이며, 비어있으면 daemon 거부 응답.
- 다음 명령은 차단 목록(deny by default):
  - `git push --force` (force-with-lease는 별도 옵션)
  - `git reset --hard`, `git clean -fd`
  - `rm -rf <절대경로>`, `sudo *`
- 차단 목록 우회는 사용자가 휴대폰에서 confirm 후에만 1회성으로 허용된다.
- 토큰은 회전 가능해야 한다(`config regenerate-token`).

**근거**: 무인·자동 실행 + 외부 트리거 가능 = 보안 사고 시 영향 큼. 1인용도 예외 없다.

### VII. Observability & Auditability

자동 실행은 인간 감시 없이 동작하므로, 사후 추적이 보장되어야 한다.

- 모든 로그는 구조화 로깅(JSON lines), `~/.local/share/remotask/logs/`에 보관한다.
- 모든 세션의 시작·종료·실패는 SQLite `sessions` + `session_events`에 기록된다.
- 다음 행위는 별도 audit 로그에 남긴다:
  - 외부 네트워크 호출
  - git destructive 명령
  - 차단 목록 우회 승인
  - 토큰 발급·회전
- daemon 헬스체크 엔드포인트(`GET /api/health`)는 항상 동작해야 한다.
- 로그 로테이션은 정해진 정책(10MB × 5)을 따른다.

**근거**: "어제 자동으로 무엇을 했는지" 추적이 안 되면 신뢰가 무너지고 시스템 자체를 못 쓴다.

## Architecture & Technology Constraints

### 언어·런타임
- 데몬·CLI는 Python 3.11+ 단일 언어.
- 별도 API key 사용 없이 Claude Code OAuth credential 사용(`claude-agent-sdk`).
- 패키지 매니저는 uv. 사용자 설치는 `uv tool install .`.

### 디렉토리 표준
- 사용자 데이터는 XDG Base Directory 표준을 따른다:
  - 설정: `~/.config/remotask/`
  - 상태(DB·로그·소켓): `~/.local/share/remotask/`
  - 캐시: `~/.cache/remotask/`
- 프로젝트 내부에는 사용자별 상태를 두지 않는다.

### IPC
- daemon ↔ 모든 클라이언트 간 통신은 단일 HTTP/WebSocket 인터페이스(`127.0.0.1:6789`).
- Unix socket·named pipe 등 별도 IPC를 두지 않는다(D14).

### 의존성 정책
- 새 외부 의존성 추가는 spec에 정당화 사유 명시 필수.
- "편의를 위해" 단독으로는 정당화되지 않는다.
- 표준 라이브러리·이미 채택된 라이브러리로 가능하면 그쪽을 우선한다.

## Development Workflow

### 변경 흐름
1. PRD 또는 issue로 변경 의도 정의.
2. `/speckit-specify`로 feature spec 작성.
3. (필요 시) `/speckit-clarify`로 모호함 제거.
4. `/speckit-plan`으로 구현 계획 작성. **Constitution Check 게이트 통과 필수**.
5. (필요 시) `/speckit-checklist`로 요구사항 검증.
6. `/speckit-tasks`로 task 분해.
7. (선택) `/speckit-analyze`로 일관성 점검.
8. `/speckit-implement`로 구현.

### Constitution Check 게이트
- 모든 plan은 7개 원칙 각각에 대한 적합성을 명시적으로 확인한다.
- 위반이 필요하면 plan의 "Complexity Tracking" 표에 다음을 기록한다:
  - 어느 원칙을 위반하는가
  - 왜 필요한가
  - 더 단순한 대안이 거부된 이유

### 리뷰 / 머지
- spec과 구현은 동일 PR에서 함께 리뷰된다.
- daemon이 자동 생성한 PR은 사람의 머지 승인을 거쳐야 한다(자동 머지 금지).
- 위반 항목이 기록되지 않은 채로 원칙 위반이 발견되면 차단 사유다.

### 브랜치
- 모든 작업은 issue 단위 worktree·branch에서 수행된다.
- main 직접 push 금지. force-push는 차단 목록.

## Governance

### 우선순위
이 헌법은 PRD를 포함한 모든 다른 문서·관행보다 우선한다. PRD가 헌법과 충돌하면 헌법이 이긴다.

### 개정 절차
1. 개정 제안자가 변경 사유와 영향 범위를 spec으로 작성한다.
2. `/speckit-constitution`을 호출하여 이 문서를 갱신한다.
3. Sync Impact Report를 갱신하고 영향받는 템플릿·문서를 함께 수정한다.
4. 버전 번호를 다음 규칙에 따라 증가시킨다:
   - **MAJOR**: 원칙 제거 또는 호환되지 않는 governance 변경
   - **MINOR**: 새 원칙·섹션 추가 또는 가이드의 실질적 확장
   - **PATCH**: 표현·오탈자·비-의미적 정리
5. 단일 commit으로 헌법 갱신을 머지한다(`docs: amend constitution to vX.Y.Z`).

### 준수 검토
- 모든 PR 리뷰어는 변경이 헌법에 부합하는지 확인할 의무가 있다.
- 자동 PR(daemon 생성)도 동일 기준이 적용된다.
- 원칙 위반이 합당한 사유로 의도된 경우 plan의 Complexity Tracking에 명시되어야 하며, 그렇지 않은 위반은 머지 차단 사유다.

### 런타임 가이드
- `.specify/memory/constitution.md` (이 문서) — 원칙
- `PRD.md` — 제품 정의·결정 로그
- `CLAUDE.md` — AI agent 런타임 안내(spec-kit 워크플로우)
- 충돌 시 우선순위: 이 헌법 > PRD > CLAUDE.md > 일반 문서

**Version**: 1.1.0 | **Ratified**: 2026-05-01 | **Last Amended**: 2026-05-02
