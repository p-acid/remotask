# Data Model: CLI Bootstrap

**Feature**: 001-cli-bootstrap
**Date**: 2026-05-01

> 본 feature는 SQLite 스키마와 그 마이그레이션 정책만 정의한다.
> 비즈니스 로직(세션 실행·텔레그램 라우팅)은 후속 feature에서 같은 테이블을 사용한다.

---

## 1. 마이그레이션 정책

- 디렉토리: `src/remotask/migrations/`
- 파일명: `V<seq>__<slug>.sql` (4자리 zero-pad)
- 적용 시점: `core/db.py::connect()` 호출 시 자동
- 트랜잭션: 각 파일은 단일 트랜잭션으로 적용
- 다운그레이드: 미지원 (전진 전용)
- 추적 테이블: `schema_version`

```sql
CREATE TABLE IF NOT EXISTS schema_version (
  version     INTEGER PRIMARY KEY,
  slug        TEXT NOT NULL,
  applied_at  INTEGER NOT NULL          -- unix epoch seconds
);
```

---

## 2. V0001__init.sql — 초기 스키마

본 feature가 적용하는 단 하나의 마이그레이션. 모든 비즈니스 테이블의 골격을 미리 만들어두며, 후속 feature는 이 위에 컬럼을 추가하거나 데이터를 채워 넣는다.

### 2.1 projects — Jira project ↔ git repo 매핑

```sql
CREATE TABLE projects (
  jira_key      TEXT PRIMARY KEY,        -- e.g. "ZXTL"
  repo_path     TEXT NOT NULL,           -- 절대 경로
  base_branch   TEXT NOT NULL DEFAULT 'main',
  enabled       INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  added_at      INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL
);

CREATE INDEX idx_projects_enabled ON projects(enabled);
```

| 컬럼 | 의미 | 검증 |
|---|---|---|
| jira_key | 대문자 영문(2~10) + `-` 없는 prefix | 정규식 `^[A-Z]{2,10}$` |
| repo_path | 절대 경로 (`/`로 시작) | `os.path.isdir(repo_path) and (repo_path / ".git").exists()` |
| base_branch | git 브랜치 이름 | 비어있지 않음 |
| enabled | 1=활성, 0=비활성 | CHECK 제약 |

본 feature에서는 행이 채워지지 않을 수 있다(사용자가 `projects add`를 호출해야 채워짐). 다만 마이그레이션은 적용되어 후속 feature가 즉시 사용 가능.

### 2.2 sessions — 실행 인스턴스 메타데이터

```sql
CREATE TABLE sessions (
  id              TEXT PRIMARY KEY,       -- uuid4
  issue_key       TEXT NOT NULL,          -- e.g. "ZXTL-1234"
  status          TEXT NOT NULL CHECK (status IN (
                    'enqueued','starting','running',
                    'pr_created','completed','failed','canceled')),
  worktree_path   TEXT,
  branch          TEXT,
  pr_url          TEXT,
  pr_number       INTEGER,
  pid             INTEGER,
  topic_id        INTEGER,                -- Telegram forum topic
  trigger_user    INTEGER,                -- Telegram user id
  trigger_text    TEXT,
  enqueued_at     INTEGER NOT NULL,
  started_at      INTEGER,
  ended_at        INTEGER,
  error_message   TEXT,
  log_path        TEXT
);

CREATE INDEX idx_sessions_issue ON sessions(issue_key);
CREATE INDEX idx_sessions_status ON sessions(status);
```

본 feature에서는 행이 비어있다. CLI가 표시할 때 "no sessions yet"으로 응답해야 한다(spec FR로 추가).

### 2.3 session_events — 세션 이벤트 타임라인

```sql
CREATE TABLE session_events (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  type            TEXT NOT NULL,          -- 'log' | 'tool_use' | 'turn' | 'pr_created' | ...
  payload         TEXT NOT NULL,          -- JSON
  created_at      INTEGER NOT NULL
);

CREATE INDEX idx_events_session ON session_events(session_id, created_at);
```

본 feature에서는 행이 비어있다.

### 2.4 locks — advisory lock

```sql
CREATE TABLE locks (
  resource        TEXT PRIMARY KEY,       -- e.g. 'lockfile', 'db-migration'
  holder_session  TEXT,
  acquired_at     INTEGER
);
```

본 feature에서는 행이 비어있다(Phase 3에서 다중 세션 도입 시 사용).

---

## 3. 상태 머신 (참고)

`sessions.status`는 다음 전이만 허용된다(본 feature는 검증 함수의 자리만 마련):

```
enqueued ──▶ starting ──▶ running ──▶ pr_created ──▶ completed
                              │              │
                              ▼              ▼
                           failed         failed
                              ▲              ▲
                              └─── canceled ─┘
```

전이 검증 함수(`core/sessions.py::validate_transition`)는 후속 feature에서 구현한다.

---

## 4. 외부 인터페이스에 노출되는 엔티티 — config.toml

DB는 아니지만 사용자가 직접 편집·CLI를 통해 조작하는 데이터이므로 함께 명세한다. 상세 키 정의는 [contracts/config.schema.md](./contracts/config.schema.md) 참조.

---

## 5. 마이그레이션 적용 시 동작 계약

1. `connect()` 호출.
2. `schema_version` 테이블이 없으면 생성.
3. `migrations/` 디렉토리를 `V*.sql` 파일명으로 정렬.
4. 각 파일에서 `version = int(prefix[1:])` 추출.
5. `schema_version`에 미등록인 `version`만 트랜잭션으로 실행.
6. 실행 성공 시 `INSERT INTO schema_version (version, slug, applied_at) VALUES (...)`.
7. 실패 시 트랜잭션 롤백 + 사용자에게 안내 + 0이 아닌 종료 코드.

---

## 6. 본 feature가 만드는 데이터 변화 요약

- ✅ schema_version 테이블 생성 + V0001 마이그레이션 등록
- ✅ projects, sessions, session_events, locks 테이블 생성 (모두 빈 상태)
- ❌ 비즈니스 데이터 적재 없음

---

## 7. 검증 (테스트 항목)

- `test_db_migrations.py::test_v0001_creates_all_tables` — `sqlite_master`에서 5개 테이블 존재 확인
- `test_db_migrations.py::test_v0001_idempotent` — 재실행 시 변경 없음
- `test_db_migrations.py::test_session_status_check_constraint` — 잘못된 status 삽입 시 IntegrityError
- `test_db_migrations.py::test_projects_jira_key_unique` — 중복 jira_key 삽입 시 IntegrityError
- `test_db_migrations.py::test_session_events_cascade_delete` — sessions 삭제 시 events도 삭제
