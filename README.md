# remotask

Remote agent trigger for Claude Code via Telegram. 휴대폰에서 `/run ZXTL-1234`
한 줄로 로컬 PC의 Claude Code 세션을 시작해 Jira 이슈를 처리하고 Draft PR까지
자동으로 만든다.

## What it does

- Telegram에서 `/run <Jira-key>` (또는 평문 `ZXTL-1234`)로 세션 트리거.
- 화이트리스트 사용자만 트리거 가능, forum topic 단위로 세션 격리.
- daemon이 `git worktree` + Claude Agent SDK로 작업을 수행.
- 진행 상황은 같은 토픽에 `[ZXTL-1234] Status: …` 형식으로 실시간 보고.
- 첫 commit이 생기면 GitHub Draft PR을 자동 생성, 토픽에 링크 회신.
- 잘못 가고 있으면 같은 토픽에서 `/cancel` 한 번으로 graceful 종료
  (응답 없으면 grace 후 force-kill).
- 머지는 사람이 GitHub 모바일 앱에서 직접 수행.

## Status

Phase 1 (MVP) 완료. Phase 2(웹 GUI)는 예정. 자세한 범위는 [`PRD.md`](./PRD.md) §2,
현재까지 머지된 feature stack은 [`ARCHITECTURE.md`](./ARCHITECTURE.md) §8 참조.

## Install

```bash
uv tool install .
```

## Quickstart

```bash
remotask init                                  # config + DB + token bootstrap
remotask config set agent.max_concurrent 1
remotask projects add ZXTL ~/Developments/zextool
remotask install                               # macOS launchd agent 등록
remotask daemon status                         # ✓ running
```

Telegram 측 셋업(봇 생성, supergroup forum 활성화, 화이트리스트 추가)은
`remotask init` 마법사 안내에 따라 진행한다. 채널 이용 흐름은 각 feature의
quickstart 문서가 가장 정확하다 — 가장 최근 것은
[`specs/006-remove-termination-aliases/quickstart.md`](./specs/006-remove-termination-aliases/quickstart.md).

## CLI

```
remotask init                  # 인터랙티브 설정 마법사
remotask install / uninstall   # launchd plist 등록/해제
remotask daemon start | stop | status | logs -f
remotask daemon run-foreground # launchd가 호출하는 진입점
remotask config get | set <key> [value]
remotask login                 # Telegram 토큰·그룹 등록
remotask sessions list | cancel <issue-key>
remotask projects list | add <jira-key> <repo-path> | remove <jira-key>
```

## Telegram surface (운영자 명령)

큐레이션된 슬래시 셋 (BotFather UI 자동완성):

| 명령 | 설명 |
|------|------|
| `/run <Jira-key | free-text>` | 세션 시작 |
| `/cancel` | 활성 세션 종료 (토픽 안에서) |
| `/status` | 활성 세션 목록 (메인 챗) / 토픽 상세 (토픽 안) |

평문 메시지 중에서 인식되는 형식: `[A-Z][A-Z0-9_]{1,9}-\d{1,6}` 패턴이 있는 메시지를
세션 트리거로 받는다 (예: `please look at ZXTL-1234`). 그 외 평문은 일반 채팅으로
무시된다.

## Development

```bash
uv sync
uv run pytest                          # 전체 테스트 (~60s)
uv run ruff check src/ tests/
uv run mypy src/remotask/core/
```

테스트는 `tests/unit/`, `tests/integration/` 아래에 있다. 옵트인 `local_only`
마커는 실제 launchctl 상태를 변경하는 테스트 전용이다 — `pytest -m local_only`로
실행.

## Documentation map

| 문서 | 답하는 질문 |
|------|-------------|
| [`.specify/memory/constitution.md`](./.specify/memory/constitution.md) | 절대 어기지 않는 원칙 |
| [`PRD.md`](./PRD.md) | 누가, 왜, 무엇을/안 만드는가 (제품 layer) |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | 무엇이 어떻게 생겼는가 (현재 시스템 정의) |
| [`ARD.md`](./ARD.md) | 왜 이 시스템 구조를 골랐는가 (결정 이력) |
| [`specs/<feature>/`](./specs) | 구체 변경의 명세 / 회귀 테스트 의도 |
| [`CLAUDE.md`](./CLAUDE.md) | AI agent 런타임 인덱스 (현재 active plan 포인터) |

새 feature는 `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` →
`/speckit-implement` 흐름을 따른다 (헌법 §V).
