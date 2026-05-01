# Implementation Plan: Telegram Trigger

**Branch**: `002-telegram-trigger` | **Date**: 2026-05-01 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/002-telegram-trigger/spec.md`

## Summary

Add a Telegram-driven trigger to the existing daemon: an authorized operator posts a Jira issue key in a Telegram forum group, the daemon resolves the issue's prefix to a registered project, spawns an isolated worker (git worktree + dedicated branch) running the Claude Agent SDK, and streams progress to a per-session forum topic until a draft pull request URL can be posted. Whitelist auth, fail-closed defaults, and per-session audit trails make the trigger safe to run unattended on a personal machine.

The 001-cli-bootstrap feature shipped a stub daemon (`daemon/stub_runtime.py`) that holds a PID lock and waits for SIGTERM. This feature replaces that stub with a real runtime that drives three coupled subsystems — a Telegram long-poll listener, a session/dispatch coordinator, and a worker pool — all sharing the existing SQLite schema (`projects`, `sessions`, `session_events`) which already includes the `topic_id` and `trigger_user` columns provisioned in V0001.

## Technical Context

**Language/Version**: Python 3.11+ (constraint inherited from constitution and 001-cli-bootstrap)
**Primary Dependencies**:
- `httpx` (async HTTP client for Telegram Bot API long-poll) — NEW
- `claude-agent-sdk` (worker execution; OAuth via local `claude` CLI, no API key) — NEW
- existing: `typer`, `pydantic`, `structlog`, `jinja2`
- standard library: `sqlite3`, `subprocess`, `asyncio`, `signal`, `threading`
**Storage**: existing SQLite at `~/.local/share/remotask/state.db`. V0001 schema already covers this feature; **no migration is required for MVP**. A V0002 migration is planned only if dispatch needs (e.g., per-issue cooldown timestamp) cannot be served by the existing columns — to be confirmed in Phase 0 research.
**Testing**: `pytest` + `pytest-asyncio` (NEW for async listener tests), subprocess coverage instrumentation already in place (`tests/sitecustomize.py`).
**Target Platform**: macOS (primary; launchd integration from 001), Linux (best-effort; no systemd unit yet).
**Project Type**: single-project CLI + long-running daemon. Layout follows the existing `src/remotask/` tree.
**Performance Goals**: trigger-to-acknowledgement under 5 seconds (SC-001); the listener's poll loop is naturally idle-bound by Telegram's `getUpdates` long-poll (default 25 seconds), so absolute throughput is not a constraint at this scale.
**Constraints**:
- Single-host, single-user deployment.
- `max_concurrent` defaults to 1 (constitution Principle IV — multi-session is P3 / opt-in).
- All HTTP listeners (if any) bind `127.0.0.1` only; no external exposure.
- Bot token + whitelist live in the existing `config.toml` under `[telegram]` (already provisioned in `core/config.py`).
**Scale/Scope**: 1–3 active sessions per day at peak in normal personal use; ≤ 5 registered projects; whitelist of 1–3 user ids. Listener uptime target ≥ 99% over a 7-day window (SC-004).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **I. Jira as Single Source of Truth**
  - The trigger uses the issue key as a routing token only; no Jira fields (title, status, comments) are persisted. The worker fetches Jira context at runtime via the existing `/work-start` flow.
  - The `projects` table maps prefix → repo path; this is *execution metadata*, not Jira state duplication.
- [x] **II. Daemon-Centric Architecture** — see Complexity Tracking entry below
  - The Telegram listener, dispatcher, and worker pool all live inside the daemon process.
  - `remotask telegram start/stop/status` CLI subcommands send signals or read state files; **the formal HTTP API mandated by Principle II is deferred to a follow-up feature** (003-daemon-http-api). This is a documented MVP simplification under Principle IV.
- [x] **III. Strict Session Isolation**
  - 1:1:1:1 mapping (issue / worktree / branch / topic) is enforced by FR-009, FR-010, FR-015.
  - Concurrent same-issue triggers are rejected (FR-010); per-issue advisory lock via the existing `locks` table.
  - `max_concurrent=1` default keeps MVP serialized; bumping it is opt-in.
- [x] **IV. MVP-First, Incremental Hardening**
  - Out-of-MVP items listed in spec Assumptions: hot-reload, multi-chat, multi-bot, voice/image input, in-topic two-way conversation, remote workers.
  - US6 (concurrency) is P3 and tracked but not required for the first cut.
- [x] **V. Spec-Driven Development**
  - This plan derives from `specs/002-telegram-trigger/spec.md` (committed `be91e17`).
- [x] **VI. Security by Default**
  - Whitelist mandatory; empty whitelist → daemon rejects all messages (FR-003 fail-closed).
  - Bot token stored at 0600; `secrets` module already redacts known-secret keys.
  - No new external bindings; all sockets remain `127.0.0.1`.
  - Constitution's destructive-command denylist applies inside the worker (Claude Agent SDK permission_mode=`acceptEdits`, force-push/reset/clean already deny-listed at the agent level).
- [x] **VII. Observability & Auditability**
  - Every accept/reject path emits a structured log line and (for state-changing accepts) a `session_events` row.
  - Audit log gains five new event types (see spec Key Entities).
  - Health endpoint requirement (Principle VII) is bundled with the deferred HTTP API and tracked under the same follow-up feature; in the meantime, `remotask telegram status` reads listener heartbeat from a state file.

## Project Structure

### Documentation (this feature)

```text
specs/002-telegram-trigger/
├── plan.md                 # This file
├── research.md             # Phase 0 output
├── data-model.md           # Phase 1 output (schema delta + state machine)
├── contracts/
│   ├── cli-commands.md     # remotask telegram start/stop/status surface
│   ├── config.schema.md    # [telegram] section deltas (already provisioned)
│   └── telegram-protocol.md# message → action contract (parsing + reply shape)
├── quickstart.md           # Manual end-to-end verification
├── checklists/
│   └── requirements.md     # Spec quality (already passing)
└── tasks.md                # Created later by /speckit-tasks
```

### Source Code (repository root)

```text
src/remotask/
├── cli.py                          # add: telegram subcommand registration
├── commands/
│   ├── telegram.py                 # NEW: start/stop/status CLI
│   ├── ...existing commands
├── core/
│   ├── config.py                   # existing TelegramConfig already in place
│   ├── db.py                       # existing — add helpers for session/topic lookups
│   ├── projects.py                 # existing — add by_prefix() lookup
│   └── ...
├── daemon/
│   ├── runtime.py                  # NEW: real daemon orchestrator (replaces stub)
│   ├── stub_runtime.py             # KEPT temporarily for fallback / will be removed in cleanup task
│   ├── listener.py                 # NEW: Telegram long-poll loop
│   ├── dispatcher.py               # NEW: message → session decision
│   ├── worker.py                   # NEW: subprocess wrapper around claude-agent-sdk
│   ├── topic.py                    # NEW: forum topic create/post helpers
│   └── audit.py                    # NEW: structured audit-log writer
├── telegram/
│   ├── __init__.py
│   ├── client.py                   # NEW: thin httpx wrapper (sendMessage, createForumTopic, getUpdates)
│   └── parser.py                   # NEW: pure issue-key extraction
└── ...

tests/
├── unit/
│   ├── test_telegram_parser.py     # NEW
│   ├── test_dispatcher.py          # NEW
│   ├── test_audit.py               # NEW
│   └── ... existing
├── integration/
│   ├── test_listener_loop.py       # NEW (asyncio + httpx mock transport)
│   ├── test_worker_lifecycle.py    # NEW (real subprocess; SDK stubbed)
│   ├── test_runtime_end_to_end.py  # NEW (whole daemon, fake Telegram server)
│   └── ... existing
└── fakes/
    ├── fake_telegram.py            # NEW: in-process Telegram Bot API stand-in
    └── fake_agent.py               # NEW: stand-in for claude-agent-sdk worker
```

**Structure Decision**: Single project, mirroring 001-cli-bootstrap's `src/remotask/` layout. New `daemon/` submodules are added rather than introducing a separate package, because the daemon orchestration is tightly coupled to existing `core/` (config, db, paths, lifecycle). A new `telegram/` package isolates the protocol-level code (HTTP shape, parsing) so the daemon can mock it cleanly in integration tests.

## Phase 0: Outline & Research

(see `research.md`)

Key research items:
1. **Telegram long-poll vs webhook** — long-poll wins for home-network use (no inbound port).
2. **`claude-agent-sdk` worker invocation** — subprocess vs in-process; subprocess wins for crash isolation.
3. **Forum topic creation API contract** — `createForumTopic` returns `message_thread_id`; that is the value stored in `sessions.topic_id`.
4. **Async vs threaded listener** — async (asyncio + httpx) chosen; runs alongside the existing signal-driven daemon main thread via a dedicated event loop.
5. **State-file location for `telegram status`** — `~/.local/share/remotask/listener.state` (JSON), single-writer (the daemon).
6. **Schema deltas** — none in V0001 satisfies all FRs; V0002 deferred unless research surfaces a need.
7. **Same-issue-in-flight detection** — query `sessions WHERE issue_key=? AND status NOT IN ('completed','failed','canceled','pr_created')`. (Whether `pr_created` should count as still-active is decided in research.)
8. **Backoff strategy for `getUpdates` failures** — exponential with jitter, cap; documented in research.
9. **Worker timeout enforcement** — process-group kill via `os.killpg` after configurable per-session timeout.
10. **Daemon-restart recovery** — on startup, mark non-terminal sessions `failed` with reason `daemon_restart`; post a notice to their topic if `topic_id` is set.

## Phase 1: Design & Contracts

(see `data-model.md`, `contracts/`, `quickstart.md`)

1. **Data model**: documents the session state machine (enqueued → starting → running → pr_created/completed/failed/canceled), the binding between `sessions.topic_id` and Telegram forum topics, and the `session_events` taxonomy used by audit.
2. **Contracts**:
   - `cli-commands.md` — exact flags, exit codes, output shape for `remotask telegram start/stop/status`.
   - `config.schema.md` — `[telegram]` section semantics (already in `core/config.py`), validation rules, secret redaction list addition.
   - `telegram-protocol.md` — the trigger-message grammar, accepted prefixes pattern, reply shapes for each rejection case.
3. **Agent context update**: replace the active-feature pointer in `CLAUDE.md` to point at this plan.

## Phase 2 (deferred to /speckit-tasks)

Task decomposition is produced by the next command. This plan stops here per template instructions.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Principle II partial — no formal daemon HTTP API in MVP | The 001-cli-bootstrap shipped a stub daemon; building a full HTTP API alongside the Telegram listener would double the surface area of this feature. CLI uses signals/state files in MVP. | A full HTTP API today would block trigger validation behind unrelated auth/transport plumbing. Deferring it isolates the risk: the trigger flow can be exercised end-to-end without the API, and the API arrives in a focused follow-up (003-daemon-http-api) whose only job is to lift CLI ↔ daemon onto the HTTP transport. The signals/state-file approach is reversible — replacing them with HTTP calls later is a localized refactor in `commands/telegram.py`. |
| New external dep `httpx` | Async HTTP client is required for Telegram long-poll; standard library `http.client` is synchronous-only and would need a thread per call. | `urllib`/`http.client` would force either threading or pure blocking, fighting the asyncio listener model. `httpx` is widely audited and offers a trivial mock transport for tests. |
| New external dep `claude-agent-sdk` | The worker is the entire reason for this feature; no in-house substitute is reasonable. | Not an alternative — wrapping the `claude` CLI by hand would re-implement the SDK badly. |
| New external dep `pytest-asyncio` | Required to test the asyncio listener cleanly. | Not an alternative — driving an event loop manually in tests is fragile. |
