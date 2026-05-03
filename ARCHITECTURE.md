# Architecture

> Current-state system definition. This document answers
> "what does the system look like right now."
> "Why these decisions were made" → [`ARD.md`](./ARD.md).
> "What we are building" → [`PRD.md`](./PRD.md).
> "Which principles are non-negotiable" → [`CONSTITUTION.md`](./CONSTITUTION.md).

---

## 1. System overview

remotask is a **single daemon process managed by macOS launchd**. The daemon
holds all business logic and system privileges; every other surface (CLI,
Telegram bot, future web UI) acts purely as a daemon client.

```
                       ┌──────────────────┐
                       │   Telegram        │
                       │   (mobile / desk) │
                       └────────┬──────────┘
                                │ Bot API long-poll (HTTPS)
                                ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                  remotask daemon (launchd)                   │
   │                                                              │
   │   ┌──────────────┐    ┌──────────────────┐                  │
   │   │  Listener    │───▶│   Dispatcher      │                 │
   │   │  (asyncio)   │    │  (slash + plain)  │                 │
   │   └──────────────┘    └────────┬──────────┘                 │
   │                                │                             │
   │                                ▼                             │
   │   ┌──────────────────────────────────────────┐              │
   │   │  Session lifecycle (sessions.py)          │              │
   │   │   enqueued → starting → running           │              │
   │   │     → {pr_created, completed, canceled,   │              │
   │   │        failed}                             │              │
   │   └────────┬─────────────────────────────────┘              │
   │            │                                                  │
   │            ▼                                                  │
   │   ┌──────────────────────────────────────────┐              │
   │   │  Worker (asyncio.create_subprocess_exec) │              │
   │   │   - git worktree                           │              │
   │   │   - claude-agent-sdk subprocess            │              │
   │   │   - PROGRESS / FINAL stdout protocol       │              │
   │   │   - SIGUSR1 → grace → SIGTERM/SIGKILL     │              │
   │   └────────┬─────────────────────────────────┘              │
   │            │                                                  │
   │            ▼                                                  │
   │   ┌──────────────────────────────────────────┐              │
   │   │  Topic poster (sessions.py / topic.py)    │              │
   │   │   - format_progress(issue_key, body)      │              │
   │   │     ⇒ "[<issue_key>] <body>"              │              │
   │   └──────────────────────────────────────────┘              │
   │                                                              │
   │   ┌──────────────────────────────────────────┐              │
   │   │  SQLite (V0001):                          │              │
   │   │   sessions / session_events /             │              │
   │   │   projects / locks                        │              │
   │   └──────────────────────────────────────────┘              │
   │                                                              │
   │   ┌──────────────────────────────────────────┐              │
   │   │  audit.log (append-only JSON lines)       │              │
   │   └──────────────────────────────────────────┘              │
   └─────────────────────────────────────────────────────────────┘
                       ▲
                       │ (Phase 2: HTTP API on 127.0.0.1:6789)
                  ┌────┴─────┐
                  │ remotask │
                  │   CLI    │
                  └──────────┘
```

The Phase 2 HTTP / WebSocket API and React web GUI sit on top of the daemon
in this diagram and are not yet implemented (Phase 1 today). See PRD §2 for
the MVP scope table.

## 2. Component responsibilities

| Module | Location | Responsibility |
|--------|----------|----------------|
| **CLI** | `src/remotask/cli.py`, `src/remotask/commands/` | User-facing typer subcommands. Daemon start / stop / status, configuration, project mappings. |
| **Listener** | `src/remotask/daemon/listener.py` | Telegram Bot API long-poll. Hands inbound messages to the dispatcher. |
| **Dispatcher** | `src/remotask/daemon/dispatcher.py` | Message → intent routing. Allowlist gate, slash-command branch (`/run` / `/cancel` / `/status`), plain-text issue-key trigger branch, audit of rejected paths. |
| **Session lifecycle** | `src/remotask/daemon/sessions.py` | State transitions, topic-id binding, lock acquisition / release, the chokepoint for posting topic messages. |
| **Worker** | `src/remotask/daemon/worker.py` | Creates the git worktree, spawns the agent subprocess, parses PROGRESS / FINAL / STEP / EVENT stdout, runs the SIGUSR1 grace ladder, applies the terminal transition. |
| **SDK driver** | `src/remotask/agent/sdk_worker.py` | Wraps the claude-agent-sdk call (007). Sends the initial `/work-start <key>` prompt, translates PostToolUse / Stop hooks into STEP / EVENT lines, enforces the §VI deny-list at a `PreToolUse` hook, and turns SIGUSR1 into a cooperative `client.interrupt()`. |
| **Topic formatter** | `src/remotask/daemon/topic.py` | Single chokepoint `format_progress(issue_key, body)` that adds the `[<issue_key>]` prefix to every session-bound outbound message + canonical templates. |
| **Telegram client / parser / commands** | `src/remotask/telegram/` | Bot API calls, message parsing (`extract_first_issue_key`, `match_slash_command`), the curated `setMyCommands` set. |
| **Audit** | `src/remotask/daemon/audit.py` | Session-bound events go to the `session_events` table; unbound events (rejection, auth failure) go to `audit.log`. |
| **Runtime** | `src/remotask/daemon/runtime.py` | Listener thread, asyncio loop, signal handlers, in-memory state (`operator_stop_in_flight` set, `worker_pid_by_session` map). |
| **Core libs** | `src/remotask/core/` | Config schema (pydantic), XDG paths, SQLite connection / migration, structlog setup. |

## 3. Process & data layout

**Processes**

- A single daemon process. launchd manages the PID.
- The listener runs on its own thread; the asyncio loop lives inside that
  thread.
- The worker is a child process spawned by the daemon (separate PID, separate
  process group).

**Data** (XDG)

- `~/.config/remotask/config.toml` — configuration (0600).
- `~/.local/share/remotask/state.db` — SQLite (WAL).
- `~/.local/share/remotask/logs/audit.log` — append-only audit log.
- `~/.local/share/remotask/logs/session-<id>.log` — per-session stdout / stderr.
- `~/.local/share/remotask/daemon.pid` — flock-backed single-instance guard.
- `<worktree_root>/<issue_key>` — per-session isolated worktree
  (configured under `agent.worktree_root`).

## 4. Concurrency & isolation model

**Isolation unit (Constitution §III, since v1.1.0)**

- `1 Jira issue = 1 git worktree = 1 git branch.` Filesystem and git state
  are isolated.
- Telegram-channel mapping (forum topics) is a presentation-layer decision
  and is not part of the constitutional isolation model. The current
  implementation keeps the forum-topic model.

**Concurrency guards**

- `max_concurrent_sessions` (config, default 1) — additional triggers are
  rejected.
- Same-issue retrigger — rejected with a notice while a session for the
  issue is active.
- `locks` table — advisory locks for shared resources (lockfile, DB
  migration, …).
- `_operator_stop_in_flight` set (in-memory) — guarantees at-most-once
  semantics for `/cancel`.

## 5. Operator control plane (Telegram)

**Curated slash set** (exposed in BotFather UI via `setMyCommands`):

- `/run <issue-key | free-text>` — start a session
- `/cancel` — stop the active session (within a topic)
- `/status` — list active sessions (main chat) or topic detail (in a topic)

**Message processing priority** (dispatcher):

1. Allowlist gate
2. Slash command — handler if in the curated set; otherwise
   `slash_command_rejected reason=unknown_command`
3. Plain-text issue-key trigger — accept-trigger flow on regex match
4. Anything else — ignored as ordinary chat (no control behaviour)

**Termination ladder** (`/cancel` or worker timeout):

1. SIGUSR1 (cooperative)
2. Wait for `operator_stop_grace_seconds`
3. SIGTERM (process group)
4. SIGKILL after 5 seconds

**Message format**

- Every session-bound outbound message flows through
  `topic.format_progress(issue_key, body)` and is rendered as
  `[<issue_key>] <body>` (005 / FR-011).

## 6. State machine — `sessions.status`

```
   enqueued ──▶ starting ──▶ running ──┬─▶ pr_created ──▶ completed
                                        ├─▶ completed
                                        ├─▶ canceled
                                        └─▶ failed
```

All transitions go through `sessions.transition(...)` and are recorded as
`state_transition` rows in `session_events`.

## 7. Tech stack (current)

- **Language / runtime**: Python 3.11+, the uv package manager
- **CLI**: typer
- **HTTP**: httpx (Telegram client)
- **Agent**: claude-agent-sdk (delegates to the `claude` CLI's OAuth
  credential, no separate API key). From 007 onward the production path
  drives the SDK directly via `remotask.agent.sdk_worker`; the 003
  `demo_worker` lives on as a placeholder for legacy regression tests.
- **Data**: SQLite (V0001 schema), WAL mode
- **Logging**: structlog (JSON lines)
- **Daemon management**: launchd (macOS)
- **Tests**: pytest, pytest-asyncio, pytest-cov

To be introduced in Phase 2: FastAPI + uvicorn (HTTP / WebSocket), React 19
+ Vite + Tailwind.

## 8. Feature evolution

The system evolves feature by feature. Per-feature history (motivation +
core outcome + PR / ARD references) lives in
[`CHANGELOG.md`](./CHANGELOG.md). The current feature stack:

| Feature | Core deliverable |
|---------|------------------|
| `001-cli-bootstrap` | typer CLI, XDG paths, V0001 schema, daemon shell, launchd registration |
| `002-telegram-trigger` | Listener, dispatcher, topic creation, audit, worker scaffolding |
| `003-e2e-demo` | Placeholder worker, operator-stop ladder, FINAL line protocol |
| `004-slash-commands` | `setMyCommands`, `/run` grammar, `/status`, slash-command dispatch |
| `005-dm-channel` | `/cancel` canonical, `[<issue_key>]` prefix chokepoint, alias deprecation |
| `006-remove-termination-aliases` | Deprecation aliases removed |
| `007-agent-sdk-integration` | Placeholder `demo_worker` → real claude-agent-sdk driver, STEP / EVENT protocol, deny-list hook, agent-side Draft-PR creation |

## 9. Where each thing lives

| Looking for | Read |
|-------------|------|
| Non-negotiable principles | `CONSTITUTION.md` |
| Product identity / MVP scope / scenarios | `PRD.md` |
| **Current shape of the system (this document)** | `ARCHITECTURE.md` |
| **Why this shape (D1, D2, …)** | `ARD.md` |
| Per-feature history (PR + ARD references) | `CHANGELOG.md` |
| Spec for a specific change | `specs/<feature>.md` (single-file) |
| Onboarding | `README.md` |
| The code itself | `src/remotask/` |
