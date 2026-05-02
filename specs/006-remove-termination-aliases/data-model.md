# Phase 1 Data Model — Remove Deprecated Termination Aliases (006)

**Feature**: 006-remove-termination-aliases
**Date**: 2026-05-02

> 본 feature는 **데이터 모델을 줄이는** 작업이다. 새 엔티티·새 필드·새 인덱스를 도입하지 않으며, SQLite 스키마
> V0001은 변동 없이 유지된다. 본 문서는 (1) 무엇이 *그대로* 남는지, (2) 무엇이 *제거*되는지를 명시적으로 기록한다.

---

## 1. SQLite Schema (V0001) — **변경 없음**

| Table             | 변경 여부 | 비고                                                                                  |
|-------------------|----------|---------------------------------------------------------------------------------------|
| `sessions`        | 변경 없음 | `topic_id`(nullable, 005에서 그대로) 포함 모든 컬럼 유지.                              |
| `session_events`  | 변경 없음 | event type 추가/제거 없음.                                                            |
| `projects`        | 변경 없음 |                                                                                       |
| `locks`           | 변경 없음 |                                                                                       |

마이그레이션 산출물은 0건. `src/remotask/migrations/`에 새 파일을 추가하지 않는다.

---

## 2. In-memory State — `Runtime`

### 2.1 보존되는 상태 (005에서 도입, 006에서 그대로 유지)

| Field                              | Type                                  | 목적                                                          |
|------------------------------------|---------------------------------------|---------------------------------------------------------------|
| `_operator_stop_in_flight`         | `set[str]`                            | session_id별 cancel ladder 진입 1회 보장.                       |
| `_worker_pid_by_session`           | `dict[str, int]`                      | SIGUSR1/SIGTERM/SIGKILL 신호 송신 대상 PID lookup.             |

### 2.2 **제거**되는 상태 (005에서 도입, 006에서 삭제)

| Field                              | Type                                  | 도입 시기 | 제거 사유                                       |
|------------------------------------|---------------------------------------|----------|-------------------------------------------------|
| `_alias_deprecation_warned`        | `set[tuple[str, str]]`                | 005      | 별칭 경로 자체가 사라지므로 작성자 부재.       |
| `has_alias_deprecation_warned()`   | `(alias_token, session_id) -> bool`   | 005      | 호출자 제거.                                    |
| `record_alias_deprecation_warned()`| `(alias_token, session_id) -> None`   | 005      | 호출자 제거.                                    |
| `clear_alias_deprecation_for_session()` | `(session_id) -> None`           | 005      | 호출자 제거.                                    |

---

## 3. `DispatchContext` (dataclass)

### 3.1 보존되는 필드

```python
@dataclass
class DispatchContext:
    conn: sqlite3.Connection
    client: TelegramClient
    chat_id: int
    bot_username: str | None

    is_operator_stop_in_flight: Callable[[str], bool]
    record_operator_stop_in_flight: Callable[[str], None]
    clear_operator_stop_in_flight: Callable[[str], None]
    get_worker_pid: Callable[[str], int | None]

    # ... (그 외 005 이전부터 존재한 필드들)
```

### 3.2 **제거**되는 필드 (005에서 도입, 006에서 삭제)

```python
# 모두 제거:
has_alias_deprecation_warned: Callable[[str, str], bool] | None
record_alias_deprecation_warned: Callable[[str, str], None] | None
clear_alias_deprecation_for_session: Callable[[str], None] | None
```

`Runtime._on_message`에서 `DispatchContext`를 채우는 부분의 세 키워드 인자도 함께 제거한다.

---

## 4. Audit 모듈 상수

### 4.1 보존되는 상수

| Constant                        | Value                            | 도입 | 비고                                          |
|---------------------------------|----------------------------------|------|-----------------------------------------------|
| `EV_SLASH_COMMAND_REJECTED`     | `"slash_command_rejected"`       | 004  | `/done` unknown_command 거부 시 그대로 사용.  |
| `EV_OPERATOR_CANCEL`            | `"operator_cancel"` (또는 동치) | 003/005 | `/cancel` 발동 시 사용.                       |
| `REASON_MAIN_CHAT_CANCEL`       | `"main_chat_cancel"`             | 005  | `/cancel`이 메인 챗에서 들어왔을 때 사유.    |
| `REASON_UNKNOWN_COMMAND`        | `"unknown_command"`              | 004  | curated set에 없는 슬래시 거부 사유.          |

### 4.2 **제거**되는 상수 (005에서 도입, 006에서 삭제)

| Constant                        | Value                          | 도입 | 제거 사유                                     |
|---------------------------------|--------------------------------|------|-----------------------------------------------|
| `EV_ALIAS_DEPRECATION_USED`     | `"alias_deprecation_used"`     | 005  | 발행자 제거(별칭 경로 삭제).                 |
| `REASON_MAIN_CHAT_DONE`         | `"main_chat_done"`             | 005  | `/done`이 더 이상 인식되지 않음.             |

> **과거 audit 로그 라인**에 들어 있는 두 문자열(`"alias_deprecation_used"` 이벤트, `"main_chat_done"` 사유)은 그대로
> 보존된다. append-only 정책(헌법 VII)에 따라 **로그 정정은 하지 않는다**. 코드 측 상수 식별자만 사라지고, 과거 로그
> 분석 시 두 문자열이 등장한다면 "006 이전 데이터"로 해석된다.

---

## 5. Audit 이벤트 흐름 변화

| Operator action                                   | 005 (현재)                          | 006 (이후)                          |
|---------------------------------------------------|-------------------------------------|-------------------------------------|
| `/cancel` (토픽)                                  | `operator_cancel` + cancel ladder   | 동일.                                |
| `/cancel` (메인 챗)                               | `slash_command_rejected reason=main_chat_cancel` | 동일.                  |
| `/done` (토픽)                                    | cancel ladder + `alias_deprecation_used` 1회 | `slash_command_rejected reason=unknown_command` (세션 미변동) |
| `/done` (메인 챗)                                 | `slash_command_rejected reason=main_chat_done` + `alias_deprecation_used` | `slash_command_rejected reason=unknown_command` |
| 평문 `done`/`stop`/`finish` (토픽)                | cancel ladder + `alias_deprecation_used` 1회 | (이벤트 없음, 일반 채팅으로 무시)   |
| 평문 `done` (메인 챗)                             | (이벤트 없음, 005부터 비-제어)       | 동일 (이벤트 없음).                 |

---

## 6. Worker 인터페이스 변화

`worker.run_worker(...)`의 시그니처에서 다음 파라미터가 사라진다:

```python
# 제거:
on_terminal: Callable[[str], None] | None = None
```

호출부(`dispatcher._handle_run_command` 내부)에서 인자 전달도 제거한다. worker 종료 경로의 try/except cleanup hook
호출 코드도 제거한다.

---

## 7. Parser 모듈 변화

`src/remotask/telegram/parser.py`에서 함수 하나가 사라진다:

```python
# 제거:
def match_termination_command(text: str) -> str | None: ...
```

남아있는 parser 공개 API:

| Function                              | 변경 여부 | 비고                                              |
|---------------------------------------|----------|---------------------------------------------------|
| `extract_first_issue_key(text)`       | 변경 없음 | 002에서 도입.                                     |
| `split_prefix(issue_key)`             | 변경 없음 | 002에서 도입.                                     |
| `match_slash_command(message, ...)`   | 변경 없음 | 004에서 도입, `/cancel`/`/run`/`/status` 등 처리. |

---

## 8. State Machine — 변경 없음

세션 상태 머신은 005와 동일하다 (`enqueued → starting → running → {pr_created, completed, canceled, failed}`).
별칭 제거는 어떤 상태도 추가/제거하지 않으며, 어떤 transition도 변경하지 않는다.

---

## 9. 외부 contract 표면

본 feature는 daemon HTTP API 변경 없음. CLI 변경 없음. config 스키마 변경 없음. setMyCommands curated set은 005에서
이미 `{run, cancel, status}`로 갱신되어 있어 본 feature에서 그대로 유지한다.

운영자가 보는 변화는 단 하나: `/done` 슬래시 명령이 unknown_command로 거부된다. 평문 `done`/`stop`/`finish`는
어차피 운영자 측면에서 "어떤 응답도 오지 않는" 동일한 결과로 끝난다(005에서는 cancel + 경고가 발동했으나,
운영자가 의도적으로 평문을 쓸 가능성이 낮으므로 사용성 영향은 무시 가능).
