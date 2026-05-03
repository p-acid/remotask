# Architecture Decision Record (ARD)

> 이 시스템이 **왜** 지금의 모습인지에 대한 결정 이력.
> "지금의 모습 자체"는 [`ARCHITECTURE.md`](./ARCHITECTURE.md), "절대 어기지
> 않는 원칙"은 [`CONSTITUTION.md`](../CONSTITUTION.md).

각 entry는 영구적이다. 결정이 후속 결정으로 뒤집히면 *덮어쓰지 않고* 새 entry를
추가하여 이력을 보존한다.

---

## D1 — 자체 워크스페이스 대신 Jira를 SoT로 유지

**결정**: 자체 task / issue / workspace 도메인을 모델링하지 않는다. 우리 SQLite는
실행 메타데이터(sessions / projects / locks / events)만 저장한다.

**사유**: 이중관리·싱크 비용을 피한다. 1인 셀프호스트 도구가 감당할 수 없는
부담. (헌법 §I와 동치.)

---

## D2 — Telegram을 1차 트리거 채널로 채택

**결정**: 모바일 트리거 채널은 Telegram bot.

**사유**: 모바일 UX 즉시성, 1인 워크플로우 적합. Forum topic으로 다중 세션 표시
지원. Slack 대비 봇 등록 마찰 적음.

---

## D3 — Slack은 Phase 5 옵션

**결정**: Slack 통합은 1차 범위에서 제외.

**사유**: 1인 환경에서 채널 다중화는 복잡도만 추가. 필요해질 때 도입.

---

## D4 — Claude Agent SDK 채택 (`-p` 단발 모드 X)

**결정**: 워커는 `claude` CLI의 `-p` 단발 모드가 아니라 `claude-agent-sdk`로
spawn.

**사유**: 양방향 인터랙션·hook 이벤트 수집이 가능해야 모니터링/제어가 풍부해진다.
단발 모드는 "한 번 호출하고 끝"이라 진행 상황 가시성이 낮음.

---

## D5 — 별도 API key 미사용 (CLI OAuth credential 위임)

**결정**: API key를 별도로 발급받지 않고 `claude` CLI의 OAuth credential을 그대로
사용.

**사유**: Pro/Max 구독을 그대로 활용. 토큰 관리 표면 축소.

---

## D6 — macOS Keychain 사용 가능하지만 강제하지 않음

**결정**: Telegram bot token은 0600 파일 보관이 기본. Keychain 통합은 옵션.

**사유**: 1인용 단순성 우선. Keychain 의존을 강제하면 다른 OS로 이식 시 재작업.

---

## D7 — PR 자동 생성·push, 머지는 사람이 GitHub 앱에서

**결정**: Draft PR 생성 + push까지만 자동. 머지는 사용자가 GitHub 모바일 앱에서
직접 수행.

**사유**: 사용자 명시 요청. 안전을 위해 머지 결정 권한은 사람에게 남긴다.

---

## D8 — 다중 세션은 worktree + Telegram forum topic으로 격리

**결정**: 세션마다 별도 worktree·branch. Telegram 표시는 forum topic으로 분리.

**사유**: 컨텍스트 자연 분리. 단, 헌법 v1.1.0(2026-05-02) 이후 Telegram 채널
매핑은 presentation-layer로 분리되었다 (D19 참조).

---

## D9 — 데스크탑 앱 대신 로컬 웹 채택

**결정**: GUI는 Phase 2부터 React 웹앱으로 제공. 데스크탑 네이티브 앱은 만들지
않음.

**사유**: daemon이 풀 권한 백엔드라 능력 동등. 모바일 브라우저로도 접근 가능.
개발 속도가 훨씬 빠름.

---

## D10 — 데스크탑은 Phase 5 옵션 (Tauri로 같은 React 코드 래핑)

**결정**: 필요해지면 Tauri로 동일 React 빌드를 셸 래핑.

**사유**: 수평 진화 경로 확보. 처음부터 도입하면 1인용에 오버헤드.

---

## D11 — Python 채택

**결정**: daemon·CLI 모두 Python 3.11+ 단일 언어.

**사유**: claude-agent-sdk + telegram lib 모두 성숙. 데몬·CLI 양쪽에 적합. 1인
유지보수에 인지 부담 적음.

---

## D12 — XDG 디렉토리 표준 채택

**결정**: 사용자 데이터를 `~/.config`, `~/.local/share`, `~/.cache`로 분리.

**사유**: 추후 패키징·배포 친화적. 다른 macOS/리눅스 도구와 일관.

---

## D13 — typer 서브커맨드 구조를 처음부터 도입

**결정**: 단일 명령이라도 typer 서브커맨드 구조로 시작.

**사유**: 추후 CLI 확장 시 갈아엎음 방지. typer 보일러플레이트는 충분히 가볍다.

---

## D14 — IPC를 Unix socket 대신 HTTP로 통일

**결정**: daemon ↔ 모든 클라이언트 간 통신은 HTTP/WebSocket 단일
인터페이스(`127.0.0.1:6789`).

**사유**: CLI · 웹 UI · 향후 외부 트리거가 동일 API를 쓰므로 추상화 한 단으로
줄어든다. Unix socket은 웹/모바일이 못 쓰니 결국 HTTP가 필요해진다.

---

## D15 — daemon과 GUI 프로세스 분리

**결정**: GUI는 daemon과 독립 프로세스.

**사유**: GUI를 닫아도 트리거 처리가 끊기지 않아야 한다. launchd가 daemon만
관리.

---

## D16 — 동시 실행은 Phase 3로 미룸 (Phase 1은 1개로 시작)

**결정**: MVP에서는 `max_concurrent = 1`. 다중 세션은 Phase 3.

**사유**: 큐·락·격리를 충분히 검증한 뒤 확장. 1인용에서 1개로도 일단 가치 검증
가능.

---

## D17 — MVP에서 웹 GUI 제외

**결정**: 핵심 가치(원격 트리거)를 먼저 검증. 모니터링은 CLI + Telegram으로
충분.

**사유**: 헌법 §IV (MVP-First, Incremental Hardening)와 정합. 검증되지 않은 가치에
인프라를 미리 투자하지 않는다.

---

## D18 — spec-kit 도입, `/speckit-*` 명령으로 스펙 주도 개발

**결정**: PRD → spec → plan → tasks → implement 흐름 표준화. `/speckit-specify`
부터 시작하는 흐름.

**사유**: AI 협업 친화적. 무인 실행 환경에서 의도와 구현의 추적 가능성은 안전성의
전제. (헌법 §V와 동치.)

---

## D19 — 헌법 §III "Strict Session Isolation" 완화 (v1.0.0 → v1.1.0, 2026-05-02)

**결정**: 헌법 §III의 1:1:1:1 매핑을 1:1:1로 완화.
- 변경 전: `1 Jira issue = 1 git worktree = 1 git branch = 1 Telegram forum topic`
- 변경 후: `1 Jira issue = 1 git worktree = 1 git branch` (Telegram 채널 매핑은
  presentation-layer 결정)

**사유**: 005가 forum-topic 모델을 유지하되 `[<issue_key>]` prefix와 `/cancel`
캐노니컬화로 multi-session 가독성을 별도 메커니즘으로 보장하게 되면서, 채널
매핑을 헌법적 격리 모델에 박아둘 필요가 사라졌다. 향후 1:1 DM·web UI 등 다른
presentation으로 확장 시 헌법 amend 없이 spec 수준에서 결정 가능.

**근거 spec**: `../specs/005-dm-channel/`

**MINOR bump 이유**: 원칙 제거가 아니라 invariant 완화 (additive). 더 많은 구현
형태를 허용하는 방향.

---

## D20 — `/cancel`을 운영자 종료 명령의 캐노니컬로 채택 (005)

**결정**: 운영자가 활성 세션을 종료하는 슬래시 명령을 `/cancel`로 통일.
`setMyCommands` 큐레이션 셋은 `{run, cancel, status}`.

**사유**:
- DB의 terminal status가 `canceled`이므로 명령어와 결과 상태가 의미적으로 일치.
- Telegram BotFather UI 자동완성에서 운영자가 "이게 진짜 취소되는 거구나"를
  바로 인지.
- 003에서 잠시 사용한 평문 `done` 종료 grammar는 토픽 안 일반 채팅과 충돌
  가능성이 있어 명시적 슬래시로 격상.

**근거 spec**: `../specs/005-dm-channel/`

**시간 박스**: 옛 `/done` 슬래시 + 평문 `done`/`stop`/`finish`는 한 릴리스 동안
deprecated alias로 유지하다 다음 릴리스(006)에서 제거 — D21 참조.

---

## D21 — 종료 별칭 4개 완전 제거 (006)

**결정**: 005가 한 릴리스 동안 deprecated로 유지한 4개 별칭(`/done` 슬래시 +
평문 `done`/`stop`/`finish`)을 완전히 제거. `/cancel`만 종료 명령으로 인식.

**사유**:
- 005의 deprecation timebox 약속을 지킨다.
- 평문 `done`/`stop`/`finish`는 토픽 안 일반 채팅에서 우발적으로 등장 가능 →
  control 동작이 일반 텍스트와 분리되는 것이 안전성에 더 부합.
- dispatcher 분기·runtime in-memory 셋·worker 콜백을 함께 제거하여 코드 표면
  축소.

**근거 spec**: `../specs/006-remove-termination-aliases/`

**Audit 영향**:
- `EV_ALIAS_DEPRECATION_USED` 이벤트, `REASON_MAIN_CHAT_DONE` 사유 상수 제거.
- 과거 audit 로그 라인의 두 문자열은 append-only 정책에 따라 보존.

---

## D22 — claude-agent-sdk 실 통합 채택 (007)

**결정**: 003에서 도입한 placeholder `demo_worker`를 실제 `claude-agent-sdk`
기반 driver(`remotask.agent.sdk_worker`)로 교체. 운영자가 `/run <key>`를 보내면
daemon이 worktree를 만들고 그 안에서 driver subprocess를 spawn한다. driver는
`/work-start <key>` 슬래시 스킬로 세션을 시작하고 `/work-done`으로 마무리한다.
권한 정책은 `permission_mode="bypassPermissions"`이며, 헌법 §VI deny-list는
driver-level `PreToolUse` 훅으로 enforce된다 (per-tool prompt 우회와 무관하게
banned 명령은 차단). cooperative cancel은 SIGUSR1 → asyncio Event →
`client.interrupt()` 경로로 003 ladder를 그대로 보존한다. Draft PR 생성은
**agent-side**(슬래시 스킬 안에서 `gh pr create --draft` 등)이며 driver는
assistant 메시지 텍스트에서 `PR_URL=(\S+)`를 scrape하여 stdout으로 그대로
emit한다. daemon은 GitHub API 자격증명을 보유하지 않는다.

stdout protocol은 003의 `PR_URL=` / `PROGRESS` / `FINAL`을 보존한 채 두
라인 셰이프(`STEP <body>`, `EVENT <type> <json>`)를 super-set으로 추가한다.
`fake_agent`는 003-006 회귀 테스트용 stand-in으로 그대로 유지하여 회귀 표면을
최소화한다.

**사유**:
- daemon-thin 유지(헌법 §II): SDK 호출은 worker subprocess에 격리되고 daemon은
  여전히 stdout 라인 파서·상태 전이·토픽 chokepoint만 소유.
- 헌법 §VI deny-list invariant 보존: `bypassPermissions`로 인해 비활성화될 뻔한
  banned-command 차단을 driver-level 훅으로 다시 강제.
- Draft PR 생성을 agent-side로 두면 daemon에 GitHub PAT 추가 책임이 생기지 않고,
  PR 템플릿/메타데이터는 운영자의 슬래시 스킬 디자인 자유에 맡길 수 있다.
- 003 stdout protocol을 super-set으로 확장한 덕에 003-006 통합 테스트 한 줄도
  수정하지 않아도 된다 (`fake_agent`는 새 셰이프를 emit하지 않음).

**근거 spec**: `../specs/007-agent-sdk-integration/`

**Constitution impact**: 헌법 v1.1.0 그대로. waiver 없음. plan.md의 Constitution
Check 7/7 PASS.

---

## 향후 결정을 추가할 때

새 ARD entry 형식:

```markdown
## DNN — 짧은 결정 제목

**결정**: 한두 문장.

**사유**: 핵심 트레이드오프.

**근거 spec**: `../specs/NNN-feature/` (해당되는 경우).

**대체된 결정**: D??? (해당되는 경우 — 이전 entry는 보존하고 여기에 포인터만).
```

번호는 단조 증가. 실수로 같은 번호가 나오지 않도록 마지막 entry를 확인 후 +1.
