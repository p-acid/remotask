# Quickstart — 007 Agent SDK Integration

운영자 머신에서 007 구현을 end-to-end로 검증하는 절차. 003-006 quickstart를 이미 한 번 통과했음을 가정한다.

---

## 0. 사전 조건

```bash
# 1) claude CLI OAuth credential이 있어야 한다 (Pro 또는 Max 구독).
claude --version
ls -la ~/.claude/                   # credential 파일이 보여야 함

# 2) 운영자 본인의 슬래시 스킬이 personal config에 있어야 한다.
ls -la ~/.claude/skills/work-start.md ~/.claude/skills/work-done.md

# 3) 본 레포의 daemon이 잡히지 않았다면 install 후 띄운다.
remotask daemon status
remotask install     # 처음이라면
remotask daemon start
```

`/work-start` 스킬 안에 PR 생성 호출을 넣어두는 것이 권장 흐름이다. 가장 단순한 형태:

```markdown
# ~/.claude/skills/work-start.md
이 슬래시는 한 번 실행되면 다음을 한다:
1. 환경변수 REMOTASK_ISSUE_KEY (또는 인자로 받은 키)에 해당하는 Jira 이슈를 읽는다.
2. 작업을 수행한다.
3. 첫 commit이 생기면 즉시:
       gh pr create --draft --title "[$ISSUE_KEY] WIP" --body "..." --json url --jq '"PR_URL=" + .url'
   결과 라인 ("PR_URL=https://github.com/.../pull/N")을 한 번 stdout으로 출력한다.
4. 작업이 끝나면 /work-done을 호출한다.
```

PR URL을 출력하는 방식은 위 한 줄이 최소 계약이다 (정규식 `PR_URL=(\S+)` 매치).

---

## 1. 작은 작업 트리거 — US1 검증

```bash
# Telegram 운영자 채팅에서:
/run ZXTL-9999
```

기대 결과:
- 같은 forum group에 새 forum topic이 생성된다.
- 토픽에 `[ZXTL-9999] Status: starting` → `[ZXTL-9999] Status: running` 두 메시지가 게시된다.
- 에이전트가 작업을 진행하면서 `[ZXTL-9999] Edited foo.py`, `[ZXTL-9999] Ran: pytest -q` 같은 STEP 라인이 게시된다.
- 첫 commit + push가 일어나면 `[ZXTL-9999] Draft PR opened: https://github.com/.../pull/N` 라인이 게시된다.
- `/work-done` 호출 후 `[ZXTL-9999] Status: pr_created` → `[ZXTL-9999] Status: completed` 종료 라인이 게시된다.

검증 SQL:

```bash
sqlite3 ~/.local/share/remotask/state.db <<'SQL'
SELECT id, issue_key, status, pr_url FROM sessions WHERE issue_key = 'ZXTL-9999';
SELECT type, COUNT(*) FROM session_events
  WHERE session_id = (SELECT id FROM sessions WHERE issue_key = 'ZXTL-9999')
  GROUP BY type;
SQL
```

기대:
- `status = completed`, `pr_url`이 채워져 있어야 함.
- `agent.tool_use`, `agent.tool_result`, `agent.stop` row가 각각 ≥ 1.

---

## 2. 진행 가시성 — US2 검증

US1 검증 도중 토픽을 모바일에서 관찰:
- 도구 1개 호출당 최대 1개의 STEP 라인이 게시되는지(같은 카테고리 1초 throttle 적용 — R9).
- LLM 응답 대기 구간에 false-positive "stuck" 메시지가 발생하지 않는지.
- 모든 STEP 라인이 `[ZXTL-9999]` prefix를 가지는지 (005 chokepoint 보존).

---

## 3. Cooperative cancel — US3 검증

길게 도는 작업을 트리거하고 즉시 같은 토픽에서 `/cancel`을 보낸다.

```bash
# Telegram:
/run ZXTL-9998
# (대기) ... STEP 라인 몇 개 도착
/cancel
```

기대 결과:
- 토픽에 cancellation 안내 게시.
- driver가 `EVENT agent.interrupt {...}` + `FINAL <i> operator_stop` 라인을 emit한 뒤 exit 0.
- daemon이 `running → canceled` 전이 + `Status: canceled` 토픽 회신.
- worktree에 이미 만들어진 commit은 디스크에 남는다 (`git -C <worktree> log --oneline`).

검증 SQL:

```bash
sqlite3 ~/.local/share/remotask/state.db \
  "SELECT status, error_message FROM sessions WHERE issue_key = 'ZXTL-9998';"
```

기대: `status = canceled`, `error_message = operator_stop`.

---

## 4. Deny-list 회귀 — 헌법 §VI 보존

직접 시도하기 어렵지만 자동 테스트로 커버한다 (`tests/integration/test_sdk_worker_denylist.py`).

수동 sanity: 운영자가 `/work-start` 스킬 안에서 의도적으로 `git push --force`를 실행하도록 임시 변경하고 트리거. 기대:
- driver의 `PreToolUse` 훅이 deny → SDK가 도구 호출을 거부.
- `EVENT agent.tool_result {is_error: true}` 적재.
- 세션은 그 이후 자체 종료 또는 다른 도구로 우회 시도.

확인 후 `/work-start`에서 임시 변경을 되돌린다.

---

## 5. Pro/Max 한도 초과 (수동 시뮬레이션)

(선택) 한도 초과 시 SDK가 반환하는 error 메시지가 `failed` 전이로 그대로 흘러가는지 확인. 본 feature 범위에서는 backoff 없이 fail-fast가 정상.

---

## 6. 정리

```bash
remotask sessions list             # 활성 세션 없어야 함
ls ~/.local/share/remotask/logs/sessions/   # 세션별 로그 파일 보존
```

---

## 7. Troubleshooting

| 증상 | 원인 후보 | 조치 |
|---|---|---|
| 토픽에 PR URL이 안 뜸 | `/work-start` 스킬이 `PR_URL=<url>` 라인을 출력하지 않음 | 스킬 마지막 단계에서 `--jq '"PR_URL=" + .url'` 형식 출력 추가 |
| `Status: failed: gh: command not found` | agent의 도구 환경에 `gh` CLI 없음 | `brew install gh && gh auth login` |
| `/cancel` 후에도 worker 살아있음 | driver가 SIGUSR1을 받지 못함 (process group 분리 이슈 등) | daemon 로그에서 `worker.timeout.sigterm` / `worker.timeout.sigkill` 순서 확인. 003 ladder가 결국 처리. |
| STEP 라인이 너무 많음 | 같은 도구를 다른 카테고리로 인식 | R9 throttle 단위(`tool_name`)와 실제 SDK가 보고하는 tool name 비교 |
| `agent.tool_use` row만 있고 `agent.tool_result`가 비어있음 | driver가 tool result를 받기 전에 SIGKILL됨 | 정상. canceled/failed 전이 분류는 in-flight 플래그가 결정. |
