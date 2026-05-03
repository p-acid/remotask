# Changelog

기능 단위 history. **append-only**, 시간 오름차순 (오래된 → 최신). 신규 entry는
**파일 맨 아래에 추가**한다. 각 섹션은 5~15줄 이내로 짧게: motivation → 핵심
결과 → PR / ARD 참조. 디테일이 필요하면 ARD entry나 코드를 본다.

> 본 파일은 `specs/`의 7-file pattern을 폐기하고 단일-파일 spec + history
> stack 모델로 전환하면서 도입됐다 (process overhaul, 2026-05-03 머지 예정).
> 그 이전의 spec 자료는 git history(merge commit + 본 entry)에서 추적한다.

## Contents

- [001 — CLI bootstrap](#v001)
- [002 — Telegram trigger](#v002)
- [003 — End-to-end demo workflow + operator-stop ladder](#v003)
- [004 — Telegram slash-command surface](#v004)
- [005 — `/cancel` canonical + `[KEY]` prefix chokepoint](#v005)
- [006 — Remove deprecated termination aliases](#v006)
- [007 — Agent SDK integration (placeholder → real claude-agent-sdk)](#v007)
- [Process overhaul (2026-05-03)](#v-process-overhaul)

---

<a id="v001"></a>

## 001 — CLI bootstrap

**Commit**: `bf2557d`

typer 서브커맨드 골격(`init / install / daemon / config / login / sessions /
projects`), XDG 경로(`~/.config`, `~/.local/share`, `~/.cache`), V0001 스키마,
daemon shell, macOS launchd plist 등록. 단일 명령이라도 처음부터 서브커맨드
구조로 시작해 추후 갈아엎음 방지(D13).

<a id="v002"></a>

## 002 — Telegram trigger

**Commit**: `d861225` · 이후 PR #1로 합류

평문 메시지에서 issue-key 정규식 추출(US1), 화이트리스트 미통과는 audit-log
거부(US2), 활성 세션 거부(US3), forum topic 자동 생성 + 토픽 격리(US4).
SQLite V0001 스키마 정착(`sessions / session_events / projects / locks`),
audit 이중 저장(세션-바운드 → DB / 거부·인증 실패 → JSON lines).
worker 스캐폴딩만 두고 실 워크로드는 003에서 채움.

<a id="v003"></a>

## 003 — End-to-end demo workflow + operator-stop ladder

**PR**: [#1](https://github.com/p-acid/remotask/pull/1)

placeholder `demo_worker` 도입 — PROGRESS/FINAL stdout 프로토콜만 emit하는
deterministic 워크로드로 daemon-side 전체 흐름(worktree 생성, 상태 전이,
토픽 회신, 종료 처리)을 가짜 LLM 없이 검증. 운영자 cooperative 종료 ladder
정의: SIGUSR1 → grace → SIGTERM → 5s → SIGKILL. 003 stdout protocol
(`PR_URL=`, `PROGRESS i/N ts`, `FINAL i reason`)은 이후 005/007에서도
super-set으로 그대로 보존.

<a id="v004"></a>

## 004 — Telegram slash-command surface

**PR**: [#2](https://github.com/p-acid/remotask/pull/2)

`setMyCommands`로 BotFather UI 자동완성에 큐레이션 셋 노출
(`{run, done, status}` — `done`은 005에서 `cancel`로 변경됨). dispatcher가
`bot_command` entity를 우선 분기(슬래시) → 평문 issue-key 추출 → 거부
순서로 처리. `/run`은 Jira-key 또는 free-text 인자, `/status`는 메인 챗
요약 / 토픽 상세 두 모드.

<a id="v005"></a>

## 005 — `/cancel` canonical + `[KEY]` prefix chokepoint

**PR**: [#3](https://github.com/p-acid/remotask/pull/3) · **ARD**: D19 (헌법
§III 완화 v1.0.0 → v1.1.0), D20

운영자 종료 명령을 `/cancel`로 캐노니컬화 (DB terminal status `canceled`와
의미 일치). 모든 세션-바운드 outbound 메시지가 `topic.format_progress(
issue_key, body)` chokepoint를 통과해 `[<issue_key>]` prefix를 일관되게 가짐
(multi-session 가독성). 헌법 §III의 1:1:1:1 매핑을 1:1:1로 완화 — Telegram
채널 매핑은 presentation-layer 결정으로 분리. `/done` + 평문 종료어는 한
릴리스 deprecated 후 006에서 제거.

<a id="v006"></a>

## 006 — Remove deprecated termination aliases

**PR**: [#4](https://github.com/p-acid/remotask/pull/4) · **ARD**: D21

005가 한 릴리스 동안 deprecated로 유지한 4개 별칭(`/done` 슬래시 + 평문
`done`/`stop`/`finish`)을 완전 제거. `/cancel`만 종료 명령으로 인식.
dispatcher 분기·runtime in-memory set·worker 콜백·audit 상수까지 함께 제거.

<a id="v007"></a>

## 007 — Agent SDK integration (placeholder → real claude-agent-sdk)

**PR**: [#6](https://github.com/p-acid/remotask/pull/6) · **ARD**: D22

placeholder `demo_worker`(003)를 진짜 `claude-agent-sdk` 기반 driver
(`remotask.agent.sdk_worker`)로 교체. 운영자 `/run <Jira-key>` 한 번으로 실제
코드가 작성되고 Draft PR 링크가 토픽에 도착하는 흐름을 처음으로 end-to-end
검증. permission_mode `bypassPermissions` + driver-level PreToolUse 훅으로
헌법 §VI deny-list invariant 보존(token-based shlex 분석으로 flag 변형·체이닝
모두 차단). 003 stdout protocol을 super-set 확장(`STEP <body>`,
`EVENT <type> <json>` 두 라인 셰이프 추가) — `fake_agent` 그대로 회귀 통과.
Draft PR 생성은 agent-side(`gh pr create --draft` 등 슬래시 스킬에서) — daemon은
GitHub 자격증명 미보유, URL relay만. CodeRabbit 4 라운드 피드백 반영
(env allowlist · session_id 명시 · FINAL emit race guard · deny-list 강화 등).

<a id="v-process-overhaul"></a>

## Process overhaul (2026-05-03)

**Branch**: `chore/process-overhaul` · **ARD**: D23 (예정)

speckit 7-file pattern 폐기. 단일 파일 spec + 본 CHANGELOG 모델로 전환.
헌법은 `.specify/memory/constitution.md`에서 루트 `CONSTITUTION.md`로 이전.
`.specify/`, `.claude/skills/speckit-*` 전체 제거. `CLAUDE.md`는
Karpathy-style 4 행동 원칙 + §5 프로젝트 컨벤션으로 재작성.
