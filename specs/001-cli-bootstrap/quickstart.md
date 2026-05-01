# Quickstart: remotask 첫 설치

**Feature**: 001-cli-bootstrap
**Date**: 2026-05-01
**대상 사용자**: 처음 remotask를 설치하는 1인 사용자
**소요 시간 목표**: 5분 (SC-001)

> 본 문서는 spec의 Independent Test 항목을 사용자가 직접 손으로 따라가며 검증할 수 있도록 정리한 절차.
> 자동 테스트(`pytest`)와 1:1로 매핑되어 있어 수동/자동 양쪽으로 동일 흐름을 재현할 수 있다.

---

## 사전 준비

```bash
# 1) Python 3.11+ 확인
python3 --version

# 2) uv 설치 확인
which uv

# 3) claude CLI 로그인 상태 확인 (Pro/Max 구독자)
claude --version
```

`uv`가 없으면: `curl -LsSf https://astral.sh/uv/install.sh | sh`

---

## Step 1 — 패키지 설치 (US1 검증)

```bash
cd ~/Developments/remotask
uv tool install .
```

**확인 (US1):**

```bash
remotask --version            # → 버전 문자열 한 줄
remotask --help               # → 8개 서브커맨드 목록
remotask daemon --help        # → run-foreground/start/stop/status/logs
```

**자동 검증:**

```bash
uv run pytest tests/integration/test_cli_help.py -v
```

기대: 5건 이상 통과, 모두 1초 이내.

---

## Step 2 — 환경 부트스트랩 (US2 검증)

```bash
remotask init
```

**예상 출력:**

```
✓ Created /Users/samuel/.config/remotask/config.toml (mode 0600)
✓ Created /Users/samuel/.local/share/remotask/state.db (schema v1)
✓ Created /Users/samuel/.local/share/remotask/logs/
✓ Generated daemon.auth_token (saved to config.toml)

다음 단계:
  remotask config set telegram.bot_token <YOUR_TOKEN>
  remotask install
```

**확인 (US2):**

```bash
ls -la ~/.config/remotask/
ls -la ~/.local/share/remotask/
sqlite3 ~/.local/share/remotask/state.db ".tables"     # 5개 테이블
stat -f "%Lp" ~/.config/remotask/config.toml           # → 600
```

**멱등성 확인:**

```bash
remotask init                 # → "Already initialized; nothing to do"
```

**자동 검증:**

```bash
uv run pytest tests/integration/test_init_command.py -v
```

---

## Step 3 — 설정 조회·변경 (US3 검증)

```bash
# 기본값 확인
remotask config get agent.max_concurrent
# → 1

# 토큰 마스킹 확인
remotask config get daemon.auth_token
# → ****abcd

# 원문 노출 (필요 시만)
remotask config get daemon.auth_token --reveal

# 잘못된 키 거부
remotask config set foo.bar 1
# → Error: 'foo.bar'는 정의되지 않은 키입니다.
#   사용 가능한 키: agent.max_concurrent, agent.worktree_root, ...

# 잘못된 형식 거부
remotask config set agent.max_concurrent abc
# → Error: agent.max_concurrent는 1~10 사이 정수여야 합니다.
```

**자동 검증:**

```bash
uv run pytest tests/integration/test_config_command.py -v
```

---

## Step 4 — 데몬 라이프사이클 (US4 검증)

**터미널 1:**

```bash
remotask daemon run-foreground
# → 콘솔에 "daemon started, pid=12345" 후 idle 상태
```

**터미널 2:**

```bash
remotask daemon status
# → status: running
#   pid: 12345
#   uptime: 0h 0m 12s

# 단일 인스턴스 락 확인
remotask daemon run-foreground
# → Error: daemon already running (pid 12345)
# → exit code 4

# 정상 종료
remotask daemon stop
# → ✓ daemon stopped (took 0.3s)
```

**터미널 1**의 `run-foreground`도 SIGTERM을 받고 정상 종료된다.

**stale PID 정리 확인:**

```bash
echo "99999" > ~/.local/share/remotask/daemon.pid    # 가짜 PID
remotask daemon status
# → status: not running (stale pid file removed)
```

**자동 검증:**

```bash
uv run pytest tests/integration/test_daemon_lifecycle.py -v
```

---

## Step 5 — launchd 등록 (US5 검증, 선택)

> ⚠ 본 단계는 실제 사용자 launchd에 영향을 준다. 테스트 환경이 아닌 실 노트북에서만 실행.

```bash
remotask install
# → ✓ Wrote ~/Library/LaunchAgents/kr.mission-driven.remotask.plist
# → ✓ launchctl load (waiting up to 5s for daemon health...)
# → ✓ daemon healthy (pid 23456)
```

**확인:**

```bash
launchctl list | grep remotask
# → 23456    0    kr.mission-driven.remotask

remotask daemon status
# → status: running
```

**재부팅 검증 (선택):**

노트북을 재부팅하고 로그인 후:

```bash
remotask daemon status
# → status: running (pid 다른 값)
```

**해제:**

```bash
remotask uninstall
# → ✓ launchctl unload
# → ✓ Removed plist
# → ✓ User data preserved (config.toml, state.db, logs/)
```

**자동 검증 (옵트인):**

```bash
uv run pytest tests/integration/test_install_uninstall.py -m local_only -v
```

---

## 통합 종료 조건 (이 feature 완료 시점)

다음을 모두 만족하면 `001-cli-bootstrap` feature 완료:

- [ ] Step 1~4의 모든 자동 테스트 통과
- [ ] Step 5는 사용자 1회 수동 검증 완료 (재부팅 검증 포함)
- [ ] `pytest --cov=remotask tests/` 커버리지 70% 이상
- [ ] `remotask --help` 응답 1초 이내
- [ ] `remotask init` 응답 3초 이내
- [ ] `remotask daemon stop` 5초 이내 종료
- [ ] config.toml 권한 0600 자동 검증

---

## 트러블슈팅

### "command not found: remotask"
- `uv tool install .` 후 `~/.local/bin`이 PATH에 있는지 확인
- 또는 `uv run remotask ...`로 실행

### "claude not found in PATH" (install 단계)
- `claude` CLI 설치 경로를 PATH에 추가
- 또는 `remotask install`을 호출할 때 사용자 셸이 그 경로를 포함하는지 확인

### launchd 데몬이 부팅 후 실행되지 않음
- `tail -f ~/.local/share/remotask/logs/launchd.err.log`
- PATH·HOME 등 환경변수 누락 가능성 → `remotask uninstall && remotask install`로 재등록
