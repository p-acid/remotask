-- V0001 — initial schema for remotask
-- See specs/001-cli-bootstrap/data-model.md for rationale.

CREATE TABLE projects (
  jira_key      TEXT PRIMARY KEY,
  repo_path     TEXT NOT NULL,
  base_branch   TEXT NOT NULL DEFAULT 'main',
  enabled       INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  added_at      INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL
);

CREATE INDEX idx_projects_enabled ON projects(enabled);

CREATE TABLE sessions (
  id              TEXT PRIMARY KEY,
  issue_key       TEXT NOT NULL,
  status          TEXT NOT NULL CHECK (status IN (
                    'enqueued','starting','running',
                    'pr_created','completed','failed','canceled')),
  worktree_path   TEXT,
  branch          TEXT,
  pr_url          TEXT,
  pr_number       INTEGER,
  pid             INTEGER,
  topic_id        INTEGER,
  trigger_user    INTEGER,
  trigger_text    TEXT,
  enqueued_at     INTEGER NOT NULL,
  started_at      INTEGER,
  ended_at        INTEGER,
  error_message   TEXT,
  log_path        TEXT
);

CREATE INDEX idx_sessions_issue ON sessions(issue_key);
CREATE INDEX idx_sessions_status ON sessions(status);

CREATE TABLE session_events (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  type            TEXT NOT NULL,
  payload         TEXT NOT NULL,
  created_at      INTEGER NOT NULL
);

CREATE INDEX idx_events_session ON session_events(session_id, created_at);

CREATE TABLE locks (
  resource        TEXT PRIMARY KEY,
  holder_session  TEXT,
  acquired_at     INTEGER
);
