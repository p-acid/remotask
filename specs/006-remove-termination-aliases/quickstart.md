# Quickstart — Remove Deprecated Termination Aliases (006)

**Feature**: 006-remove-termination-aliases
**Date**: 2026-05-02
**Audience**: 변경을 손으로 검증하려는 개발자/운영자

> 005 quickstart의 forum-topic 환경(supergroup `is_forum: true`, 화이트리스트 사용자, 토픽 자동 생성)을 그대로
> 재사용한다. 본 quickstart는 6개 단계로 별칭 제거 동작만 검증한다.

## 사전 준비

- Remotask daemon이 005 이후 버전으로 빌드되어 있고, 본 feature 브랜치(`006-remove-termination-aliases`)의 변경이
  적용된 상태.
- Telegram supergroup 한 개 + 그 안에 화이트리스트된 사용자 1명. 005 quickstart §1과 동일 환경.
- daemon은 foreground 또는 launchd로 동작 중.
- 다음 두 명령이 손에 잡혀 있어야 한다:
  - `tail -f ~/.local/share/remotask/logs/audit.log` (감사 로그 라이브 스트림)
  - `sqlite3 ~/.local/share/remotask/state.db` (세션·이벤트 인스펙트)

---

## Step 1 — Baseline: `/cancel` 정상 동작 확인 (회귀 가드)

1. supergroup에서 `/run ZXTL-1234`로 새 세션 트리거.
2. dispatcher가 토픽을 생성하고 `[ZXTL-1234] Status: starting`이 토픽에 도착하는지 확인.
3. 토픽 안에서 `/cancel` 송신.
4. 다음을 확인:
   - 토픽에 `[ZXTL-1234] Session canceled by operator.` 도착.
   - `audit.log`에 `operator_cancel` 이벤트가 1건 추가됨.
   - `sessions` 테이블에서 해당 row의 `status`가 `canceled`로 전이됨.

**기대 결과**: 005에서와 동일. 본 feature가 `/cancel` 경로를 건드리지 않았음을 확인.

---

## Step 2 — `/done` 슬래시는 unknown_command로 거부됨 (FR-001 / FR-019)

1. `/run ZXTL-2222`로 새 세션 트리거.
2. 생성된 토픽 안에서 `/done` 송신.
3. 다음을 확인:
   - 토픽에 `Session canceled by operator.` 또는 그 어떤 종료 메시지도 **도착하지 않는다**.
   - 세션은 계속 `running` 상태 (`SELECT status FROM sessions WHERE issue_key = 'ZXTL-2222'`로 확인).
   - `audit.log`에 새 라인 1건 추가:
     `{"event_type": "slash_command_rejected", "command_name": "done", "reason": "unknown_command", ...}`
   - `audit.log`에 `alias_deprecation_used` 이벤트는 **0건** (`grep alias_deprecation_used audit.log` →
     본 feature 이후 추가된 라인이 없어야 함; 과거 005 시점 라인은 보존되어 있을 수 있음).
4. 같은 토픽에서 `/cancel` 송신 → 정상 종료. (별칭 거부가 이후 캐노니컬 동작을 망가뜨리지 않음을 확인.)

---

## Step 3 — `/done@<bot_username>` 형도 동일하게 거부 (Edge Case)

1. `/run ZXTL-3333`로 새 세션 트리거.
2. 토픽 안에서 `/done@<your_bot_username>` 송신 (Telegram autocomplete를 끄고 직접 입력).
3. Step 2와 동일한 검증. `command_name`은 여전히 `"done"`(`@<bot_username>` 부분이 parser에서 정규화되어 떨어진 결과).
4. 정상 종료를 위해 `/cancel`로 마무리.

---

## Step 4 — 평문 `done`/`stop`/`finish`는 무시됨 (FR-002 / FR-020)

1. `/run ZXTL-4444`로 새 세션 트리거.
2. 토픽 안에서 다음을 차례로 송신:
   - `done`
   - `stop`
   - `finish`
3. 각 메시지 후마다 다음을 확인:
   - 토픽에 어떤 새 outbound 메시지도 도착하지 않음.
   - 세션은 계속 `running` 상태.
   - `audit.log`에 새 라인이 추가되지 않음 (마지막 라인 timestamp가 이전 step과 동일).
   - `session_events`에 본 메시지로 인한 새 row 0건.
4. `/cancel`로 정상 종료.

---

## Step 5 — `/done`을 메인 챗(토픽 밖)에서 보낸 경우 (Edge Case)

1. supergroup의 메인 챗(General 토픽 또는 토픽 외 영역)에서 `/done` 송신.
2. 다음을 확인:
   - `audit.log`에 `slash_command_rejected reason=unknown_command` 1건 추가.
   - **`reason=main_chat_done` 라인은 추가되지 않음** (해당 reason 상수 자체가 사라짐).

---

## Step 6 — `[<issue_key>]` prefix 보존 (FR-004 회귀 가드)

1. `/run ZXTL-5555`로 새 세션 트리거.
2. dispatcher가 토픽에 송신하는 모든 메시지(`Status: starting`, `Status: running`, 그 후 `/cancel`로 종료 시
   `Session canceled by operator.`)가 `[ZXTL-5555] ` prefix를 가진 형태로 도착하는지 확인.
3. 005의 `[KEY]` chokepoint(`topic.format_progress`)가 본 feature에서 변경되지 않았음을 시각으로 확인.

---

## 자동 검증 (선택)

```bash
# 본 feature 회귀 보호 테스트만 실행
uv run pytest tests/integration/test_done_command_removed.py \
              tests/integration/test_plain_termination_dead.py -v

# 005에서 회귀 보호하던 핵심 테스트
uv run pytest tests/integration/test_cancel_canonical.py \
              tests/integration/test_key_prefix.py \
              tests/integration/test_operator_stop.py \
              tests/integration/test_operator_stop_forced.py -v

# 전체
uv run pytest -q
```

기대 결과:
- 신규 회귀 테스트 2개 모두 PASS.
- 005 보호 테스트 모두 PASS (`test_operator_stop*`은 본 feature에서 `/cancel`로 마이그레이션된 형태).
- 전체 테스트 카운트(현재 PR 기준): 274 passed, 2 skipped, 0 failed (005 baseline 308 → net −34).

---

## 실패 시 점검 포인트

| 증상                                                        | 점검 포인트                                                                          |
|-------------------------------------------------------------|---------------------------------------------------------------------------------------|
| `/done` 송신했는데 세션이 cancel됨                            | dispatcher의 `name == "done"` 분기가 아직 남아있을 가능성. `grep '"done"' src/remotask/daemon/dispatcher.py`. |
| 평문 `done` 송신했는데 audit row 추가됨                       | `match_termination_command` 호출이 dispatcher에 남아있을 가능성. `grep match_termination_command src/`. |
| import 에러 `EV_ALIAS_DEPRECATION_USED`                       | 일부 모듈/테스트가 상수 import를 그대로 들고 있음. 전부 grep해서 제거.               |
| `Runtime` 인스턴스 생성 시 AttributeError                     | `DispatchContext` 콜백 wiring에서 제거된 메서드를 여전히 참조 중. `runtime.py` 확인.  |
| `worker.run_worker` 호출 시 TypeError (unexpected `on_terminal`) | dispatcher 어딘가가 아직 `on_terminal=...`를 전달 중. `grep 'on_terminal=' src/`.    |
| `/cancel` 동작이 회귀                                         | `_handle_slash_cancel` 시그니처가 005에서 `alias_token` 파라미터를 가지고 있었음. 별칭 제거 시 그 파라미터를 같이 제거하면서 호출부도 같이 갱신했는지 확인. |
| `[KEY]` prefix가 빠짐                                         | `topic.format_progress` chokepoint가 변경되었는지 확인. 본 feature에서는 건드리지 않아야 함. |
