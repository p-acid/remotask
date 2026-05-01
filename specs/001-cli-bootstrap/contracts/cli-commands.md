# Contract: CLI Commands

**Feature**: 001-cli-bootstrap
**Date**: 2026-05-01

> 본 문서는 `remote-task` CLI의 명령어 표면을 계약으로 정의한다.
> 명령은 사용자에게 노출되는 외부 인터페이스이므로 변경에는 헌법(거버넌스 절차)이 적용된다.

## 0. 종료 코드 컨벤션

| 코드 | 의미 |
|---|---|
| 0 | 성공 |
| 1 | 일반 실패 (예외, 잘못된 입력) |
| 2 | 사용자 입력 형식 오류 (typer 기본) |
| 3 | 환경 미준비 (init이 필요한 상태에서 다른 명령 실행) |
| 4 | 락 충돌 (단일 인스턴스 제약 위반) |
| 5 | 권한·파일시스템 오류 |
| 6 | 외부 도구 실패 (`launchctl` 비정상 종료 등) |

## 1. 전역 옵션

```
remote-task [OPTIONS] COMMAND [ARGS]...

Options:
  --version              버전 정보 출력 후 종료
  --verbose, -v          DEBUG 레벨 로그 활성
  --no-color             컬러 비활성 (CI/파이프 환경)
  --config PATH          config.toml 경로 override (기본: $XDG_CONFIG_HOME/remote-task/config.toml)
  --help                 도움말
```

## 2. 서브커맨드 목록

| 명령 | 본 feature 구현 | 비고 |
|---|---|---|
| `init` | ✅ 완전 | |
| `install` | ✅ 완전 | macOS launchd |
| `uninstall` | ✅ 완전 | |
| `daemon` | ✅ stub 라이프사이클만 | 비즈니스 로직 X |
| `config` | ✅ 완전 | |
| `login` | ⏳ stub | 후속 feature에서 telegram 등록 |
| `sessions` | ⏳ stub | 후속 feature에서 session list/cancel |
| `projects` | ⏳ stub (CRUD 자리만) | DB는 비어있어도 add/list 동작 |

---

## 3. `init` — 환경 부트스트랩

```
remote-task init [OPTIONS]

Options:
  --force                기존 config.toml 덮어쓰기 (DB 사용자 데이터는 보존)
  --interpreter PATH     plist에 박을 Python 인터프리터 경로 (기본: 현재 sys.executable)

Exit codes:
  0  성공
  1  부분 실패 (생성된 파일은 정리됨)
  5  쓰기 권한 없음
```

**Effect**:
1. `$XDG_CONFIG_HOME/remote-task/`, `$XDG_DATA_HOME/remote-task/{logs}` 생성
2. `config.toml`을 기본값 + 자동 생성된 토큰으로 작성 (권한 0600)
3. `state.db` 생성 + V0001 마이그레이션 적용
4. 산출물 경로를 사용자에게 표시

**Idempotency**: 재실행 시 변경 없음을 보고 (FR-014). `--force`만 덮어쓰기.

**Rollback**: 단계 (2)~(3) 사이 실패 시 (1)에서 만든 디렉토리 보존, 새 파일은 삭제.

---

## 4. `install` — launchd 등록

```
remote-task install [OPTIONS]

Options:
  --label TEXT           plist Label override (기본: kr.mission-driven.remote-task)
  --interpreter PATH     Python 인터프리터 경로 override (기본: 자동 감지)
  --force                기존 plist 덮어쓰기 (확인 prompt 생략)

Exit codes:
  0  성공
  3  init 미완료
  5  ~/Library/LaunchAgents/ 쓰기 권한 없음
  6  launchctl 실패
```

**Effect**:
1. 사용자 환경 감지(`PATH`, `HOME`, `LANG`, `XDG_*`)
2. `~/Library/LaunchAgents/<label>.plist` 생성
3. `launchctl load -w <plist>` 실행
4. 데몬 헬스(PID 파일) 5초 폴링 후 결과 보고

**Pre-condition**: `init`이 선행되어야 한다. 미완료면 종료 코드 3.

**Re-install**: plist가 이미 있으면 사용자 확인 prompt → `--force`이면 생략. 갱신 시 기존 데몬 stop → unload → 새 plist load → start.

---

## 5. `uninstall` — launchd 해제

```
remote-task uninstall [OPTIONS]

Options:
  --label TEXT           plist Label override
  --purge                사용자 데이터(config·db·logs)도 삭제 (기본은 보존)

Exit codes:
  0  성공 (이미 미등록 상태도 0)
  6  launchctl unload 실패
```

**Effect**:
1. `launchctl unload -w <plist>` 실행 (이미 unload돼 있으면 무시)
2. `<plist>` 파일 삭제
3. `--purge` 시: `$XDG_CONFIG_HOME/remote-task/`, `$XDG_DATA_HOME/remote-task/` 삭제

**Default behavior**: 사용자 데이터 보존 (FR-043). `--purge`만 완전 삭제.

---

## 6. `daemon` — 라이프사이클 (stub)

```
remote-task daemon SUBCOMMAND
```

| 서브 | 설명 |
|---|---|
| `run-foreground` | 데몬을 포그라운드에서 실행 (launchd가 호출하는 진입점) |
| `start` | 백그라운드에서 데몬 spawn (사용자 수동 실행용) |
| `stop` | SIGTERM 후 5초 내 종료. 실패 시 SIGKILL |
| `status` | PID·uptime·살아있음 여부 출력 |
| `logs [-f]` | 데몬 로그 tail (`-f`로 follow) |

```
remote-task daemon run-foreground

Exit codes:
  0  정상 종료 (SIGTERM 수신)
  4  락 충돌 (이미 실행 중)
  5  PID 파일 쓰기 실패

remote-task daemon start

Exit codes:
  0  spawn 성공 (PID 표시)
  4  이미 실행 중

remote-task daemon stop

Exit codes:
  0  종료 완료
  1  데몬이 실행 중이 아님 (사용자에게 안내)
  6  종료 실패 (5초 + SIGKILL 후에도)

remote-task daemon status

Exit codes:
  0  실행 중
  1  미실행 또는 stale

Output (running):
  status: running
  pid: 12345
  uptime: 1h 23m 45s
  log: /Users/samuel/.local/share/remote-task/logs/daemon.log

Output (not running):
  status: not running
```

**stub 동작**: `run-foreground`는 PID/락만 잡고 SIGTERM 대기 무한 루프 (`signal.pause()`). 비즈니스 로직 없음.

---

## 7. `config` — 설정 조회·변경

```
remote-task config get <key> [--reveal]
remote-task config set <key> <value>
remote-task config list [--reveal]
remote-task config regenerate-token [--name TEXT]
```

| 서브 | 설명 |
|---|---|
| `get <key>` | dotted-path 키의 현재 값 출력. 시크릿은 마스킹 |
| `set <key> <value>` | 정의된 키에 값 저장. 형식 검증 후 거부 가능 |
| `list` | 전체 키 트리 표시. 시크릿 마스킹 |
| `regenerate-token [--name daemon]` | 토큰 재발급 (기본: `daemon.auth_token`) |

**Exit codes**:
- 0 성공
- 1 정의되지 않은 키
- 2 형식 오류

**Examples**:

```
$ remote-task config get agent.max_concurrent
1
$ remote-task config set agent.max_concurrent 2
✓ agent.max_concurrent = 2
$ remote-task config get telegram.bot_token
****8h2k
$ remote-task config get telegram.bot_token --reveal
1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ12345678h2k
```

---

## 8. `login` — (stub)

```
remote-task login

본 feature에서는 stub. "이 명령은 002-telegram-trigger feature에서 구현됩니다." 메시지 후 종료 코드 0.
```

---

## 9. `sessions` — (stub)

```
remote-task sessions list
remote-task sessions cancel <issue-key>

list: 현재 DB의 sessions 테이블을 단순 select로 표시. 본 feature에서는 항상 "no sessions yet" 출력.
cancel: 본 feature에서는 stub. "이 명령은 003-agent-execution feature에서 구현됩니다." 후 종료 코드 0.
```

---

## 10. `projects` — CRUD 자리

```
remote-task projects list
remote-task projects add <jira-key> <repo-path> [--branch TEXT]
remote-task projects remove <jira-key>
```

본 feature에서는 DB CRUD까지 동작한다(후속 feature가 즉시 사용할 수 있도록). UI(폴더 트리 피커)는 Phase 2.

| 서브 | 설명 |
|---|---|
| `list` | projects 테이블의 전체 행 표 형태 출력 |
| `add` | INSERT (정규식 + 경로 검증 통과 시) |
| `remove` | DELETE (활성 세션이 참조 중이면 거부) |

**Exit codes**:
- 0 성공
- 1 키 형식 오류 / 경로 비존재 / git repo 아님
- 1 (remove에서) 활성 세션 참조 중

---

## 11. 변경 정책

이 계약 표면을 변경하려면:
1. 새로운 spec(`002-...` 등)에서 변경을 명시
2. 본 문서를 갱신
3. 사용자 도움말과 자동완성 스크립트 갱신
4. 외부 사용자가 의존할 수 있는 종료 코드는 의미를 깨지 않는 방향으로만 확장
