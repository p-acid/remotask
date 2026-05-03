# Phase 1 Data Model — Agent SDK Integration

**Status**: SQLite schema V0001 변경 없음. 본 feature는 *새 데이터 형태를 추가하지 않고*, 기존 테이블의 enum-like 컬럼(`session_events.type`)과 `audit.py`의 이벤트 상수에 새 문자열만 추가한다.

---

## 1. Tables (no schema change)

### `sessions` — unchanged

```text
sessions(
  id TEXT PRIMARY KEY,
  issue_key TEXT NOT NULL,
  status TEXT NOT NULL,
  topic_id INTEGER,
  worktree_path TEXT,
  branch TEXT,
  pr_url TEXT,
  pid INTEGER,
  log_path TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)
```

전이 그래프 (003 그대로):

```
enqueued → starting → running ─┬─→ pr_created → completed
                               ├─→ completed
                               ├─→ canceled
                               └─→ failed
```

본 feature는 위 그래프에 **새 상태를 추가하지 않는다.**

### `session_events` — unchanged columns, additive `type` strings

```text
session_events(
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  type TEXT NOT NULL,
  payload_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
)
```

기존 `type` (003): `state_transition`, `worker.spawn`, `worker.exit`, `worker.timeout`.
**추가** (007):

| `type` 문자열 | 발생 조건 | payload 형태 |
|---|---|---|
| `agent.tool_use` | SDK `PostToolUse` 훅 호출 시 | `{"tool": "<name>", "iter": <int>}` |
| `agent.tool_result` | SDK가 도구 실행 결과를 받아 다음 turn으로 넘긴 시점 | `{"tool": "<name>", "iter": <int>, "is_error": <bool>}` |
| `agent.stop` | SDK `Stop` 훅 발화 시 | `{"iter": <int>, "reason": "natural" \| "operator_stop"}` |
| `agent.interrupt` | driver가 SIGUSR1 수신 후 `client.interrupt()`를 호출한 직후 | `{"iter_at_interrupt": <int>}` |

### `projects` / `locks` — unchanged

변경 없음.

---

## 2. Audit constants (`src/remotask/daemon/audit.py`)

기존 상수 (003-006): `EV_WORKER_SPAWN`, `EV_WORKER_EXIT`, `EV_WORKER_TIMEOUT`, …

**신규 (007)**:

```python
EV_AGENT_TURN: Final = "agent.turn"  # 단일 dispatcher 키 — type 컬럼에는 위 4가지 세부 문자열을 직접 사용한다. EV_AGENT_TURN은 driver가 EVENT 라인을 emit할 때 worker.py가 4종으로 fan-out하는 진입점 상수로 둔다.
```

`worker.py`는 신규 `_EVENT_RE`를 통해 `EVENT <type> <json>`을 파싱하고, type이 `agent.tool_use` / `agent.tool_result` / `agent.stop` / `agent.interrupt` 중 하나면 `audit.record_event(conn, session_id=..., type=type, payload=json)`로 그대로 적재한다. 인식되지 않는 type은 log-only(헌법 §VII 정합 + 입력 검증).

---

## 3. In-memory state (runtime.py)

변경 없음. `_alias_deprecation_warned`(006에서 제거됨)는 그대로 부재. 신규 in-memory state 추가하지 않는다 — driver는 자체 프로세스 안에서 상태를 보유.

---

## 4. Worker driver 내부 상태 (운영 범위 외)

driver 프로세스는 자체 카운터 `iter` (PostToolUse 누적 호출 수)와 throttle map(`tool_name → last_emitted_at`)을 보유한다. 이는 driver 프로세스 메모리에만 존재하며 SQLite·daemon에는 노출되지 않는다.

---

## 5. Validation & invariants

- `session_events.type`은 `audit.py`의 이벤트 상수 셋 또는 `agent.*` 4종 외 다른 값을 받지 않는다.
- `iter` 값은 monotonic increasing within a session.
- driver가 EVENT 라인을 emit한 뒤 daemon이 적재 실패해도 driver는 그대로 진행한다(best-effort). 적재 실패는 daemon-side log에 warning으로 남는다.

---

## 6. Migration

**없음.** `session_events.type` 컬럼은 free-form `TEXT`이며 V0001 그대로다. 새 문자열을 사용하는 데 ALTER TABLE이 필요하지 않다.

추후 (Phase 4 운영 안정화) `type`을 enum 제약으로 강화한다면 그때 별도 마이그레이션을 발행한다.
