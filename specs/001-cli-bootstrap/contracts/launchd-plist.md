# Contract: launchd plist

**Feature**: 001-cli-bootstrap
**Date**: 2026-05-01

> macOS launchd가 데몬을 띄우는 데 사용하는 plist의 계약.
> `install` 명령이 사용자 환경을 기반으로 동적 생성한다.

## 0. 위치 / Label

- 위치: `~/Library/LaunchAgents/<label>.plist`
- 기본 Label: `kr.mission-driven.remote-task` (역방향 도메인 표기)
- Label은 `--label` 옵션으로 override 가능

## 1. plist 키 / 값

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>kr.mission-driven.remote-task</string>

  <key>ProgramArguments</key>
  <array>
    <string>{{ remote_task_path }}</string>
    <string>daemon</string>
    <string>run-foreground</string>
  </array>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
    <key>Crashed</key>
    <true/>
  </dict>

  <key>ThrottleInterval</key>
  <integer>10</integer>

  <key>WorkingDirectory</key>
  <string>{{ home }}</string>

  <key>StandardOutPath</key>
  <string>{{ data_dir }}/logs/launchd.out.log</string>

  <key>StandardErrorPath</key>
  <string>{{ data_dir }}/logs/launchd.err.log</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>{{ path }}</string>
    <key>HOME</key>
    <string>{{ home }}</string>
    <key>LANG</key>
    <string>{{ lang }}</string>
    <key>XDG_CONFIG_HOME</key>
    <string>{{ xdg_config_home }}</string>
    <key>XDG_DATA_HOME</key>
    <string>{{ xdg_data_home }}</string>
    <key>XDG_CACHE_HOME</key>
    <string>{{ xdg_cache_home }}</string>
  </dict>

  <key>ProcessType</key>
  <string>Background</string>

  <key>LowPriorityIO</key>
  <true/>
</dict>
</plist>
```

## 2. 템플릿 변수 (install 명령이 채움)

| 변수 | 값 결정 방법 |
|---|---|
| `remote_task_path` | `shutil.which("remote-task")` 또는 `--interpreter` 명시 |
| `home` | `os.path.expanduser("~")` |
| `path` | 현재 셸 `$PATH`. 단, `claude` CLI가 발견되는 디렉토리는 항상 포함 |
| `lang` | 현재 환경 `$LANG` (없으면 `en_US.UTF-8`) |
| `xdg_*_home` | 현재 환경값. 비어있으면 표준 기본값 |
| `data_dir` | `$XDG_DATA_HOME/remote-task` |

## 3. 주요 동작 의미

### RunAtLoad / KeepAlive

- `RunAtLoad=true`: launchctl load 직후 즉시 시작
- `KeepAlive.SuccessfulExit=false`: 정상 종료 시 재시작 안 함 (`daemon stop`과 충돌 방지)
- `KeepAlive.Crashed=true`: 크래시·비정상 종료 시 재시작
- `ThrottleInterval=10`: 재시작 간 최소 10초 간격 (무한 재시작 방지)

### Logging 통합

- launchd가 stdout/stderr를 캡처해 별도 파일로 쓴다 (`launchd.out.log`, `launchd.err.log`).
- 데몬 자체의 structlog 출력은 `daemon.log`에 별도 기록.
- 두 로그가 분리되어 있어 launchd 차원의 spawn 실패와 데몬 차원의 로직 실패를 구분 가능.

### ProcessType / LowPriorityIO

- `Background` 타입은 다른 사용자 작업을 방해하지 않는 우선순위로 스케줄링.
- `LowPriorityIO`로 디스크 I/O도 양보.

## 4. 환경변수 처리 규칙

`install` 명령은 다음 우선순위로 환경변수를 결정한다:

1. `--env KEY=VALUE` 옵션으로 명시된 값 (현재 미정 — 향후 추가 가능)
2. 현재 셸의 환경값
3. 표준 기본값 (`PATH`는 `/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin`)

`claude` CLI가 PATH에 없으면 install이 거부되며 사용자에게 PATH 확인을 안내한다.

## 5. 멱등성

- 동일 Label로 plist가 이미 존재하면 사용자 확인 prompt → `--force`로 생략 가능
- `launchctl unload`(기존) → 파일 갱신 → `launchctl load`(새것) 순서로 안전 갱신
- 갱신 도중 실패하면 이전 plist를 백업(`<plist>.bak`)에서 복구

## 6. 보안 고려

- plist 파일 자체에는 시크릿이 들어가지 않는다 (토큰은 config.toml).
- plist 권한: 사용자 LaunchAgents 디렉토리 기본값(`0644`) 그대로 (시크릿 없으므로 안전).
- `EnvironmentVariables`에 토큰을 넣지 않는다.

## 7. 검증 (테스트)

- `test_macos_launchd.py::test_render_basic` — 템플릿 렌더링 결과를 `plistlib`로 파싱 후 키 존재 검증
- `test_macos_launchd.py::test_render_path_includes_claude_dir` — claude CLI 위치가 PATH에 포함됨
- `test_macos_launchd.py::test_render_keep_alive_dict` — KeepAlive가 dict 형태이며 SuccessfulExit=false
- `test_macos_launchd.py::test_label_validation` — 잘못된 label(공백·역도메인 아님) 거부
- `test_install_uninstall.py::test_install_creates_plist` — install 후 파일 존재 + 내용 일치 (local_only)
- `test_install_uninstall.py::test_install_loads_with_launchctl` — `launchctl list`에 노출 (local_only)
- `test_install_uninstall.py::test_uninstall_removes_plist` — uninstall 후 파일 삭제 (local_only)
