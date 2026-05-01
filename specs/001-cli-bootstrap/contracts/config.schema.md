# Contract: config.toml Schema

**Feature**: 001-cli-bootstrap
**Date**: 2026-05-01

`config.toml`은 사용자가 직접 편집하거나 `remote-task config` 명령으로 조작하는 외부 인터페이스다.

## 0. 위치·권한

- 경로: `$XDG_CONFIG_HOME/remote-task/config.toml` (기본 `~/.config/remote-task/config.toml`)
- 권한: `0600` 강제 (init 시 검증, 매 read 시 경고)
- 인코딩: UTF-8

## 1. 키 트리

```toml
# === 에이전트 동작 ===
[agent]
max_concurrent       = 1                       # int, 1~10, 본 feature에서는 1로 고정
worktree_root        = "~/Developments/wt"     # str, 절대/상대 경로 (~ 확장)
default_base_branch  = "main"                  # str
permission_mode      = "acceptEdits"           # str, enum: ["default","acceptEdits","plan","bypassPermissions"]

# === 데몬 ===
[daemon]
auth_token           = "<자동 생성>"           # SECRET, secrets.token_urlsafe(32)
http_host            = "127.0.0.1"             # str, MVP에서는 사용 안 하지만 자리만 마련
http_port            = 6789                    # int

# === 텔레그램 ===
[telegram]
bot_token            = ""                      # SECRET, login으로 채움 (002-telegram-trigger)
group_chat_id        = 0                       # int (forum group)
allowed_user_ids     = []                      # list[int]

# === 로깅 ===
[logging]
level                = "INFO"                  # str, enum: ["DEBUG","INFO","WARNING","ERROR"]
rotate_max_mb        = 10                      # int, 1~100
rotate_backups       = 5                       # int, 1~50

# === 경로 override (선택) ===
[paths]
config_dir           = ""                      # str, 비어있으면 XDG 기본값
data_dir             = ""                      # str
cache_dir            = ""                      # str
```

## 2. 시크릿 분류

`SECRET`으로 표시된 키는 다음 동작을 따른다:

- `config get`: 기본 마스킹 `****<last4>` 표시
- `config get --reveal`: 원문 노출 + audit 로그 남김
- `config list`: 마스킹 표시 (전체 트리에서)
- 로그 출력 시 자동 마스킹

분류:

```python
SECRET_KEYS = {
    "daemon.auth_token",
    "telegram.bot_token",
}
```

## 3. 검증 규칙 (pydantic 모델)

```python
class AgentConfig(BaseModel):
    max_concurrent: int = Field(ge=1, le=10, default=1)
    worktree_root: str = "~/Developments/wt"
    default_base_branch: str = "main"
    permission_mode: Literal["default","acceptEdits","plan","bypassPermissions"] = "acceptEdits"

class DaemonConfig(BaseModel):
    auth_token: str = Field(min_length=32)
    http_host: str = "127.0.0.1"
    http_port: int = Field(ge=1024, le=65535, default=6789)

class TelegramConfig(BaseModel):
    bot_token: str = ""                   # 빈 문자열 허용 (login 전 상태)
    group_chat_id: int = 0
    allowed_user_ids: list[int] = []

class LoggingConfig(BaseModel):
    level: Literal["DEBUG","INFO","WARNING","ERROR"] = "INFO"
    rotate_max_mb: int = Field(ge=1, le=100, default=10)
    rotate_backups: int = Field(ge=1, le=50, default=5)

class PathsConfig(BaseModel):
    config_dir: str = ""
    data_dir: str = ""
    cache_dir: str = ""

class ConfigSchema(BaseModel):
    agent: AgentConfig = AgentConfig()
    daemon: DaemonConfig
    telegram: TelegramConfig = TelegramConfig()
    logging: LoggingConfig = LoggingConfig()
    paths: PathsConfig = PathsConfig()
```

## 4. dotted-path 키 표현

CLI는 dotted-path로 키를 표현한다:

| 표현 | 내부 매핑 |
|---|---|
| `agent.max_concurrent` | `config.agent.max_concurrent` |
| `telegram.bot_token` | `config.telegram.bot_token` |
| `telegram.allowed_user_ids` | list 전체 (set 시 JSON 배열 또는 `,` 분리) |

list 타입 `set` UX:

```
$ remote-task config set telegram.allowed_user_ids 12345,67890
✓ telegram.allowed_user_ids = [12345, 67890]
```

## 5. Keychain Referencing (예약 자리)

후속 단계에서 시크릿을 macOS Keychain으로 옮길 수 있도록 reader가 다음 패턴을 인식한다:

```toml
bot_token = "@keychain:remote-task.bot_token"
```

본 feature에서는 reader에 자리만 만들고 실제 Keychain 호출은 Phase 4. 인식되었으나 Keychain 미통합 상태에서 호출되면 명확한 오류로 응답한다.

## 6. 마이그레이션 (config 자체)

키 추가·삭제 시:

1. 새로운 키는 기본값 자동 적용 (사용자 파일에 추가하지 않음 — pydantic이 기본값 채워줌)
2. 더 이상 사용하지 않는 키는 무시 (경고 로그). 다음 `config set` 시 자동 제거
3. 호환되지 않는 변경은 `config-migration` 명령(미래)에서 처리

본 feature는 v1 스키마만 정의한다.

## 7. 검증 (테스트)

- `test_config.py::test_default_load_after_init` — init 직후 ConfigSchema가 생성된다
- `test_config.py::test_get_dotted_path` — `get("agent.max_concurrent")`가 1을 반환
- `test_config.py::test_set_validates_type` — `set("agent.max_concurrent", "abc")` 거부
- `test_config.py::test_set_validates_unknown_key` — `set("foo.bar", 1)` 거부
- `test_config.py::test_set_validates_range` — `max_concurrent=99` 거부 (le=10)
- `test_config.py::test_secret_masking` — `get("daemon.auth_token")`가 `****` 형식
- `test_config.py::test_reveal_flag` — `--reveal`이 원문 반환
- `test_config.py::test_file_permission_0600` — init 후 파일 권한 검증
