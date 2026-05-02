# Contract: Alias Removal Protocol

**Feature**: 006-remove-termination-aliases
**Phase**: 1 — Design & Contracts
**Date**: 2026-05-02

이 문서는 운영자가 옛 종료 별칭을 발송했을 때 dispatcher가 수행해야 하는 분기 결정과, 발행되어야 할(또는 발행되지
**않아야** 할) 감사 이벤트를 명세한다. 005의 contract(`/cancel` 캐노니컬, `[<issue_key>]` prefix)는 본 contract의
전제이며 변경되지 않는다.

---

## 1. Slash command dispatch tree

```
Telegram message arrives
    │
    ▼
match_slash_command(message, bot_username) → SlashInvocation | None
    │
    ├── None  ─────────────────────────────────►  PLAIN TEXT BRANCH (§2)
    │
    └── SlashInvocation(name, args_text, message_thread_id)
            │
            ├── name == "run"      ──► §1.1 _handle_run_command
            ├── name == "cancel"   ──► §1.2 _handle_slash_cancel    (preserved from 005)
            ├── name == "status"   ──► §1.3 _handle_status_command
            └── name ∈ {anything else, including "done"}
                                   ──► §1.4 unknown_command rejection
```

> **006 변경점**: 005에 존재하던 `name == "done"` 분기와 그 분기 안에서 호출되던 `_emit_alias_warning(...)` +
> `_handle_slash_cancel(..., alias_token="/done")` 흐름이 통째로 사라진다. `/done`은 §1.4의 fall-through로 떨어진다.

### 1.4 Unknown slash command rejection

**Pre-conditions**: `match_slash_command`이 `name`을 반환했고, 그 `name`이 `commands.CURATED_COMMANDS`에 없다.

**Action**:
1. dispatcher는 어떤 세션 상태도 변경하지 않는다.
2. dispatcher는 어떤 outbound Telegram 메시지도 보내지 않는다 (004의 silent reject 정책).
3. audit 로그에 `EV_SLASH_COMMAND_REJECTED` 이벤트를 기록한다. 필드 (현재 구현
   기준 `dispatcher._handle_slash_command`):
   - `command`: parser가 정규화한 lowercased name (예: `"done"`)
   - `reason`: `"unknown_command"`
   - `chat_id`, `message_thread_id`, `sender_id`: 메시지 원본에서 추출
   - `message_id`, `args_text_truncated`: 메시지 원본에서 추출

**Post-conditions**:
- 실행 중인 세션은 영향을 받지 않는다.
- 새로운 audit row 1건 (`slash_command_rejected`).
- `EV_ALIAS_DEPRECATION_USED` 이벤트 **0건**.
- `REASON_MAIN_CHAT_DONE` 사용 **0건**.

**Test reference**: `tests/integration/test_done_command_removed.py` (FR-019).

---

## 2. Plain-text dispatch tree

```
Plain text message in topic
    │
    ▼
006 ────────────────────────────────►  fall through to default text handling
                                       (no termination grammar matching)
```

> **005까지의 흐름 (006에서 제거)**:
>
> ```
> 005 ────►  if message_thread_id is not None and match_termination_command(text) is not None:
>                _emit_alias_warning(...)
>                trigger cancel ladder
> ```

### 2.1 평문 `done` / `stop` / `finish` 처리

**Pre-conditions**: 운영자가 active 세션의 토픽 안에서 정확히 `done`, `stop`, 또는 `finish` 한 토큰을 보냄.

**Action**: dispatcher는 이 메시지를 일반 텍스트로 취급한다. parser에서 `match_termination_command`가 사라졌으므로
이 분기는 코드상 존재하지 않는다.

**Post-conditions**:
- 세션 상태 변경 0건.
- outbound 메시지 0건.
- `session_events` row 0건.
- audit row 0건 (`alias_deprecation_used` 또는 다른 어떤 이벤트도 발행되지 않음).

**Edge case**: 토큰 앞뒤로 공백/구두점이 있어도 (`"done."`, `"  stop  "`) 동일하다 — dispatcher는 어떤 매칭도 시도하지
않는다.

**Test reference**: `tests/integration/test_plain_termination_dead.py` (FR-020).

---

## 3. `/cancel` 캐노니컬 (005에서 변경 없음)

`/cancel`의 동작 contract는 005의 `specs/005-dm-channel/contracts/cancel-command-protocol.md`를 그대로 따른다. 본
feature에서 다음을 보호한다:

| Property                                              | 보존 여부 |
|-------------------------------------------------------|----------|
| 토픽 내 `/cancel` → graceful SIGUSR1 → grace → SIGTERM/SIGKILL 사다리 | 보존     |
| 메인 챗 `/cancel` → `slash_command_rejected reason=main_chat_cancel` | 보존     |
| `Session canceled by operator.` 템플릿                | 보존     |
| `Session force-canceled by operator (grace window exceeded).` 템플릿 | 보존     |
| `[<issue_key>]` prefix on session-bound outbound messages | 보존     |
| `_operator_stop_in_flight` set 1회 보장 의미론        | 보존     |

**Test reference**: `tests/integration/test_cancel_canonical.py` (005, 회귀 보호 대상).

---

## 4. Audit event 정합성

본 feature 적용 후, 운영자가 일으킬 수 있는 모든 종료-관련 입력에 대한 audit 이벤트 발행 매트릭스:

| Operator input                          | Channel        | Audit event                                  | Reason field           | Side effects on session |
|-----------------------------------------|----------------|----------------------------------------------|------------------------|-------------------------|
| `/cancel`                               | Topic (active) | `slash_command_received` + `telegram_termination_received` | (n/a) | Cancel ladder triggered |
| `/cancel`                               | Main chat      | `slash_command_rejected`                     | `main_chat_cancel`     | None                    |
| `/cancel something`                     | Topic (active) | `slash_command_received` + `telegram_termination_received` (args 무시 — 005 정책) | (n/a) | Cancel ladder triggered |
| `/done`                                 | Topic (active) | `slash_command_rejected`                     | `unknown_command`      | None                    |
| `/done`                                 | Main chat      | `slash_command_rejected`                     | `unknown_command`      | None                    |
| `/done@<bot_username>`                  | Topic / Main   | `slash_command_rejected`                     | `unknown_command`      | None                    |
| `/anything_else_uncurated`              | Any            | `slash_command_rejected`                     | `unknown_command`      | None                    |
| 평문 `done` / `stop` / `finish`           | Topic (active) | (none)                                       | (n/a)                  | None                    |
| 평문 `done` / `stop` / `finish`           | Main chat      | (none)                                       | (n/a)                  | None                    |
| 그 외 평문                               | Any            | (none)                                       | (n/a)                  | None                    |

**검증 가능한 invariants**:

- A1. `EV_ALIAS_DEPRECATION_USED` 이벤트는 dispatcher가 발행하는 어떤 경로에서도 작성되지 않는다.
- A2. `REASON_MAIN_CHAT_DONE` 사유는 dispatcher가 작성하는 어떤 audit row에도 등장하지 않는다.
- A3. 운영자가 `/done`을 보내고 즉시 `/cancel`을 보내는 시나리오에서, 첫 번째는 `slash_command_rejected`만 남기고
  세션은 변동 없으며, 두 번째에서 비로소 cancel ladder가 시작된다.

---

## 5. Backward compatibility

본 contract는 **005에서 명시적으로 약속된 시간 박스의 종료**다. 005 spec에 다음 문장이 있다:

> "deprecated aliases [are] kept for one release; they will be removed in the next."

따라서 운영자 측면에서 backward compatibility는 다음과 같이 정의된다:

- 005 시점에 `/cancel`로 이미 마이그레이션 완료한 운영자: 영향 없음.
- 005 시점에 별칭을 계속 사용하던 운영자: 본 feature 적용 후 별칭이 더 이상 동작하지 않음. 이는 **의도된 단절**이며,
  005의 deprecation warning 메시지가 그 마이그레이션 vehicle이었다.

migration period나 graceful degradation period는 추가로 두지 않는다.

---

## 6. 외부 시스템 contract

| Surface              | 변경 여부 | 비고                                                                          |
|----------------------|----------|-------------------------------------------------------------------------------|
| Telegram setMyCommands | 변경 없음 | 005에서 `{run, cancel, status}`로 갱신 완료. 본 feature에서 추가 호출 불필요. |
| daemon HTTP API      | 변경 없음 | 본 feature는 daemon API 표면을 건드리지 않음.                                  |
| SQLite schema V0001  | 변경 없음 | data-model.md §1 참조.                                                        |
| Config 스키마         | 변경 없음 |                                                                                |
| structlog field 셋   | 변경 없음 | `alias_deprecation` 로거 이름은 dispatcher에서 사용 중단되지만 schema는 free-form. |
