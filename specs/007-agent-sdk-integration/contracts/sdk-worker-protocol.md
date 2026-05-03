# Contract: SDK Worker Stdout Protocol (007 extension to 003)

**Feature**: 007-agent-sdk-integration
**Status**: Phase 1 design
**Supersedes**: nothing — extends `specs/003-e2e-demo/contracts/worker-stdout-protocol.md` as a strict super-set.

본 contract는 daemon-side `worker.py`가 worker subprocess의 stdout으로부터 인식하는 라인 셰이프를 정의한다. **003의 셰이프 3종 (`PR_URL=`, `PROGRESS i/N ts`, `FINAL i reason`)은 그대로 유지**되며, 007에서 두 셰이프 (`STEP`, `EVENT`)를 추가한다.

`fake_agent`는 003 셰이프만 emit해도 003-006 회귀 테스트가 통과한다. `sdk_worker`(007 신규 driver)는 새 셰이프 + `PR_URL=` + `FINAL`을 사용한다. 두 워커 모두 동일 daemon 파서로 처리된다.

---

## 1. Line shapes

| Pattern (`re.match` against trimmed line) | Origin | Daemon action |
|---|---|---|
| `^PR_URL=(\S+)\s*$` | 002+ | URL을 `sessions.pr_url`에 세팅 후 `Draft PR opened: <url>` 토픽 회신 (`format_progress` chokepoint 통과). |
| `^PROGRESS (\d+)/(\d+) (\S+)\s*$` | 003 | `Status: iteration i/N @ ts` 토픽 회신. **fake_agent 호환을 위해 유지.** |
| `^FINAL (\d+) (\S+)\s*$` | 003 | reason ∈ {`natural`, `operator_stop`}. `Status: final iteration i (reason)` 토픽 회신. terminal 전이 분기에 사용. |
| `^STEP (.+)$` | **007 신규** | body(최대 500자, 줄바꿈 없음). `format_progress(issue_key, body)`로 토픽 회신. |
| `^EVENT (\S+) (.+)$` | **007 신규** | type ∈ {`agent.tool_use`, `agent.tool_result`, `agent.stop`, `agent.interrupt`}. JSON payload 파싱 실패 또는 unknown type은 log-only. |
| _(other)_ | — | 세션 로그파일에만 기록. |

---

## 2. Formal grammar (additions)

```text
STEP_LINE   := "STEP" SP <body>
EVENT_LINE  := "EVENT" SP <type> SP <json>

body        := UTF-8 string, no '\n', length 1..500
type        := /[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*/   (예: agent.tool_use)
json        := single-line JSON object (no embedded newlines)
```

`STEP body`의 length-cap(500자)은 daemon이 enforce — 초과 라인은 log-only로 강등.
`EVENT json` parse 실패 시 daemon은 warning 로그만 남기고 계속.

---

## 3. SDK driver-side responsibilities

`src/remotask/agent/sdk_worker.py`는:

1. 시작 시 `os.environ["REMOTASK_ISSUE_KEY"]`를 읽고 첫 user 메시지로 `/work-start <issue_key>`를 SDK에 보낸다.
2. `ClaudeAgentOptions`를 다음으로 구성:
   - `permission_mode = "bypassPermissions"`
   - `hooks` ⊃ `{"PreToolUse": [HookMatcher(matcher="Bash", hooks=[deny_list_guard])]}`, `{"PostToolUse": [HookMatcher(hooks=[step_emitter, event_emitter])]}`, `{"Stop": [HookMatcher(hooks=[stop_emitter])]}`
3. `SIGUSR1` 핸들러를 등록하고, 핸들러는 asyncio Event(`_interrupt_requested`)를 set한다. main task가 그 Event를 보면 `await client.interrupt()` 호출 후 `EVENT agent.interrupt {...}` + `FINAL <i> operator_stop`를 emit하고 exit 0.
4. assistant 메시지(`Message` 스트림 중 type="assistant")의 텍스트에서 `PR_URL=(\S+)`를 매치하면 그 URL을 stdout에 `PR_URL=<url>` 라인으로 그대로 emit한다.
5. PostToolUse 훅마다 STEP 라인 1개 (`R9` throttle 적용) + EVENT 라인 1개를 emit. iter 카운터는 PostToolUse 발화마다 +1.
6. Stop 훅 발화 시 `EVENT agent.stop {...}` + `FINAL <iter> natural` 라인 emit 후 exit 0.

---

## 4. Daemon-side responsibilities (worker.py changes)

기존 `_PR_URL_RE`, `_PROGRESS_RE`, `_FINAL_RE`에 **추가**:

```python
_STEP_RE: Final = re.compile(r"^STEP (.{1,500})$")
_EVENT_RE: Final = re.compile(r"^EVENT ([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*) (.+)$")
```

`_stream_subprocess_output`은 매치 우선순위를 다음 순서로 적용:

1. `PR_URL=` (003)
2. `PROGRESS` (003)
3. `FINAL` (003)
4. `STEP` (007) — `format_progress(issue_key, body)`를 그대로 토픽 전송
5. `EVENT` (007) — `_handle_event(type, json)` 호출 → known type이면 `audit.record_event(...)`, unknown이면 warning log
6. log-only

worker.py의 신규 코드 표면은 두 정규식 추가 + STEP 핸들러 + EVENT 핸들러 두 개로 한정된다 (50라인 이내 예상).

---

## 5. Backward compatibility

- 003-006 회귀 테스트가 사용하는 `fake_agent.py`는 STEP/EVENT를 emit하지 않으므로 daemon 측 추가 분기는 매치되지 않고 기존 흐름 그대로 통과한다.
- 신규 sdk_worker는 PROGRESS는 emit하지 않고 STEP만 emit하므로 003 PROGRESS 핸들러는 dead path가 되지만 fake_agent를 위해 유지된다(향후 fake_agent를 STEP 기반으로 갈아탈 때 003 PROGRESS는 제거 가능 — 별도 feature).

---

## 6. Out-of-band channels

stdout 외 통신 채널은 없다. stderr는 003 그대로 세션 로그파일에 `[stderr] ` 프리픽스로 기록되고 마지막 2KB는 `failed` 전이 시 토픽 reason으로 사용된다.

DB 직접 접근, file-watching, named pipe 등 **모두 사용하지 않는다.**

---

## 7. Failure modes

| 상황 | daemon 처리 |
|---|---|
| driver가 STEP 라인을 emit하기 전에 timeout → SIGKILL | `failed` 전이, error_message는 stderr tail의 마지막 라인 |
| driver가 FINAL을 emit하기 전에 클라이언트 interrupt 후 쓰기 race로 라인이 잘림 | 003 fallback path (`final_marker is None` + `in_flight=True` → operator_stop_forced로 분류) |
| driver가 PR_URL을 emit했지만 `gh pr create`가 실제로 실패해서 잘못된 URL | spec edge case 그대로 — daemon은 PR URL 게시만 책임짐. PR 페이지가 404면 운영자가 인지함 (Phase 4 hardening 대상). |
| driver가 EVENT JSON parsing에 실패 | daemon warning log + log-only — 세션은 계속 진행 |
