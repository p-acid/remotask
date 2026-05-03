# Remote Task — PRD

> Remote-trigger platform for a local AI agent invoked from a phone.
> Receives a Jira issue, runs the implementation, opens a Draft PR, and is
> later monitored via a local web GUI.

- **Owner**: p-acid (qkrtkstjd@gmail.com)
- **Status**: Draft v0.4
- **Created**: 2026-05-01
- **Last updated**: 2026-05-03
- **Reference**: [multica-ai/multica](https://github.com/multica-ai/multica)

> This document is the source of truth for the **product layer**.
> "Non-negotiable principles" → [`CONSTITUTION.md`](../CONSTITUTION.md);
> "current shape of the system" → [`ARCHITECTURE.md`](./ARCHITECTURE.md);
> "why this shape was chosen" → [`ARD.md`](./ARD.md);
> "spec for each change" → the corresponding `../specs/<feature>.md`.

---

## 1. Background (Why)

### Today

- The team manages tasks in Jira. Bug reports and fix requests land as Jira
  issues.
- The author can only work through Claude Code while at the desk.
- Simple, repetitive work piles up while the desk is unattended.

### Problem

- Jira issues that arrive while away cannot be processed immediately.
- Start time is delayed until the author returns to the machine.
- Even simple bug fixes whose context is self-evident incur the same delay.

### Why not Multica

- The team's single source of truth is already pinned to Jira.
- Adopting Multica would create dual-management / sync cost between a Multica
  workspace and Jira.
- What we actually need is **remote trigger + monitoring**, not yet another
  workspace / board.

### Direction

- Keep the **task source-of-truth external** (Jira for this team today;
  GitHub Issue / Linear / … selectable per install) and build a thin
  self-hosted tool that lets the **local Claude Code session be triggered
  from a phone**.
- The trigger channel is Telegram; the monitoring GUI will eventually be a
  local web app.
- Work output is a GitHub PR; the human performs the final merge from the
  GitHub mobile app.

---

## 2. Goals / Non-goals

### In-scope

- Trigger a local Claude Code session remotely by referencing a task
  (Jira issue / GitHub Issue / …) via a Telegram message.
- Read the task context (title, description, comments) from the active
  task source automatically and act on it.
- Auto-open a Draft PR when the agent produces output and post the link to
  Telegram.
- Run multiple sessions safely in parallel (worktree-based isolation).
- Local web GUI for active / completed sessions, logs, project mappings, and
  skill settings.
- Run as a daemon that auto-starts at boot (launchd).
- Install / start / status all reachable from a single CLI invocation.

### Out-of-scope

- Replacing or supplementing Jira as a workspace.
- Multi-user / team-level permission models or org management.
- Cloud-hosted / SaaS distribution (single-user self-host is the assumption).
- Auto-merging code (the user merges from the GitHub app).
- Native desktop app (optional, considered for a later phase).
- iOS / Android native clients (Telegram + a mobile browser is enough).

### MVP scope (★)

**The MVP does not include the web GUI.** Telegram trigger + daemon + Agent
SDK + Draft-PR creation is the MVP. Inclusion details:

| Area | In MVP |
|------|--------|
| Telegram bot (long-poll, forum topic, allowlist) | ✅ MVP |
| Session lifecycle (single concurrent session) | ✅ MVP |
| Claude Agent SDK execution | ✅ MVP |
| `git worktree` isolation + auto Draft-PR creation | ✅ MVP |
| typer CLI (`init`, `install`, `daemon`, `sessions`, `projects`) | ✅ MVP |
| launchd registration / boot auto-start | ✅ MVP |
| Project mapping (config seed + DB) | ✅ MVP (CLI-only CRUD) |
| FastAPI HTTP API + WebSocket | ⛔ Post-MVP (Phase 2) |
| React web GUI (Dashboard / Session Detail / Projects / Skills / Settings) | ⛔ Post-MVP (Phase 2) |
| Multiple concurrent sessions (`max_concurrent ≥ 2`) | ⛔ Post-MVP (Phase 3) |
| Bidirectional interaction (Telegram → SDK stdin) | ⛔ Post-MVP (Phase 3) |
| Tailscale / external exposure | ⛔ Post-MVP (Phase 4) |
| Tauri desktop shell | ⛔ Post-MVP (Phase 5) |

---

## 3. Users / scenarios

### Primary persona

- **Samuel** — single-user self-host. Claude Code Pro / Max subscriber, on
  macOS. Already uses Jira / GitHub / Telegram daily. Picks **one task
  source per install** (Jira for the day-job repos, GitHub Issue for
  personal / OSS repos including remotask itself).

### Core scenarios

**[S1] Trigger a bug fix while away from the desk**

1. Receives a bug report via Slack at a café.
2. Creates a Jira issue (`ZXTL-1234`).
3. Sends `/run ZXTL-1234` in the Telegram bot chat.
4. The bot creates a worktree, gathers context, implements, runs tests.
5. On the first commit it opens a Draft PR and replies in Telegram with the
   link.
6. Reviews the diff in the GitHub mobile app and merges.

**[S2] Monitor progress**

1. Returns to the laptop and opens the browser.
2. (Phase 2) Opens the daemon's web UI.
3. Sees active session cards, queued sessions, and today's completed
   sessions.
4. Clicks into a session for turn-by-turn logs.
5. Work that ran while away is sitting at the PR stage.

**[S3] Register a new project**

1. Clones a new git repo locally.
2. (Phase 2) Hits Add in the Projects screen, or runs
   `remotask projects add ABC <repo-path>` in the CLI.
3. Registers the Jira project key (`ABC`) and the repo path.
4. Future `ABC-***` issues are automatically routed to that repo.

**[S4] Run multiple sessions concurrently**

1. Triggers two issues back-to-back on the morning commute (`ZXTL-1234`,
   `ABC-89`).
2. The bot runs them in parallel within the `max_concurrent` limit.
3. Each session is isolated to its own worktree and branch (Constitution
   §III).
4. Both arrive as Draft PRs around lunchtime.

**[S5] Stop a session in flight**

1. Spots a wrong direction in the PR preview.
2. Sends `/cancel` in the topic for that session.
3. The bot sends a cooperative stop signal; force-kills if the worker doesn't
   respond.
4. The worktree and branch are kept for post-mortem; the session is left in
   `canceled`.

---

## 4. Phased roadmap

> Detailed task breakdown per Phase lives in the per-feature spec.
> This section only names product-level milestones.

### Phase 0 — Infrastructure setup ✅ done

- Directory + `pyproject.toml` skeleton, typer CLI entrypoint
- XDG paths, SQLite V0001 schema, daemon shell, launchd registration
- Spec-driven development workflow adopted
- Driver feature: `001-cli-bootstrap` (see `CHANGELOG.md`)

### Phase 1 — Telegram trigger + Agent SDK execution ✅ done (MVP)

- Telegram bot long-poll, allowlist authentication, forum-topic
  auto-creation
- Plain-text message → issue-key extraction → session start
- Slash-command surface (`/run`, `/cancel`, `/status`) + `setMyCommands`
- Cooperative SIGUSR1 → grace → SIGTERM / SIGKILL termination ladder
- `[<issue_key>]` prefix for multi-session readability
- Auto Draft-PR creation, PR link posted back to Telegram
- Single concurrent session to start
- **🎯 MVP complete.** Subsequent Phases are gated on MVP value validation.
- Driver features: `002-telegram-trigger` … `007-agent-sdk-integration`
  (see `CHANGELOG.md`).

### Phase 2 — Web GUI ⛔ planned

- FastAPI HTTP / WebSocket server embedded in the daemon
- React + Vite project
- Dashboard / Session Detail / Projects / Skills / Settings
- The daemon serves the built React app statically.

### Phase 3 — Multi-session + bidirectional interaction ⛔ planned

- Increase `max_concurrent` (2–3)
- Advisory locks (lockfile, DB migrations, …)
- Forward agent's user-facing questions to Telegram and inject answers
  back into stdin
- Recovery policy after session restart

### Phase 4 — Operational hardening ⛔ optional

- macOS Keychain integration, log rotation / metrics, Tailscale guidance,
  refined `init` wizard

### Phase 5 — Optional expansion ⛔ when the need arises

- Homebrew tap, Tauri desktop shell, Slack channel, team mode, etc.

---

## 5. Open questions / risks

### Open questions

- **Q1**: Can the Agent SDK execute Korean-language slash skills (e.g.,
  `/work-start`) as-is? → under verification.
- **Q2**: Does launchd inherit the `claude` CLI's PATH / env correctly? →
  the `install` command auto-detects and writes them into the plist.
- **Q3**: Does the user have to grant the bot supergroup-manager permissions
  by hand? → yes; the `init` wizard walks through this.
- **Q4**: How often do concurrent sessions race for the same lockfile? →
  measured before introducing advisory locks (Phase 3).

### Risks

- **R1**: A Pro / Max usage-cap hit may trigger an infinite retry loop in the
  daemon → exponential backoff + cap-hit notification.
- **R2**: launchd churn (kill / respawn) leaves orphan worktrees / branches
  → startup-time stale-session sweeper.
- **R3**: Telegram bot-token leakage → 0600 file + optional Keychain
  (Constitution §VI).
- **R4**: Token theft after exposing the daemon (Tailscale, etc.) → token
  rotation command provided.
- **R5**: Insufficient Jira context lets the agent run in the wrong direction
  → the operator can send extra context in Telegram inside the same topic.

---

## 6. Extensibility direction — task source / messenger / agent swap

> This section is intentional about **what we are NOT building right now**.
> The actual adapter / plug-in infrastructure lands via a spec when a
> concrete second consumer (a different task source, a different messenger,
> or a different agent) appears. Aligned with Constitution §IV (MVP-First).

### Pipeline shape (today)

```text
   ┌──────────────────┐
   │   Task source    │  ← read by the agent for issue context
   │   Jira (today)   │      (GitHub Issue next — landing in 008)
   └────────┬─────────┘
            │
            ▼
[ Messenger service ] ──▶ [ remotask daemon ] ──▶ [ AI agent subprocess ]
   Telegram                                          claude-agent-sdk
   (Slack later)                                     (Codex etc. later)
```

The four stages are separated by design. From 003 onward, the worker is an
isolated subprocess speaking a small stdout protocol (5 line shapes today),
which is agent-agnostic. Constitution v1.1.0 (ARD D19) explicitly
delegated Telegram-channel mapping to the presentation layer. The
task-source provider is consulted inside the agent's worktree (read-only
context fetch + later PR back-link), so the daemon stays oblivious to
which provider supplied the issue.

### Asymmetric swap costs

- **Task-source swap — cheap (with one config flag).** A
  `TaskSourceAdapter` that declares (a) issue-key pattern, (b)
  `fetch_context(key)`, (c) `format_issue_url(key)` is enough; one active
  provider per install. The dispatcher delegates `extract_first_issue_key`
  to the adapter; the agent skill consults the same interface for context.
  No messenger-layer change.
- **AI agent swap — cheap.** Drop in
  `src/remotask/agent/<name>_worker.py` that emits the same stdout
  protocol (`PR_URL=` / `PROGRESS` / `FINAL` / `STEP` / `EVENT`); virtually
  no daemon-side change. A single config flag flips the
  `_default_worker_argv()` branch. No new abstraction needed.
- **Messenger swap — expensive.** Telegram concepts (forum topic,
  `message_thread_id`, Bot API, `setMyCommands`, the `bot_command` entity)
  are baked directly into `dispatcher.py` / `listener.py` / `topic.py` /
  `runtime.py`. To plug in Slack you would have to extract a
  `MessengerAdapter` interface (`receive_inbound`, `send_outbound`,
  `create_session_channel`, `parse_command`, `format_session_label`) and
  invert the dispatcher's dependency to that abstraction.

### Adoption triggers (when, not now)

- **New task source**: trigger now (008). Samuel is dogfooding remotask
  development on GitHub Issue, satisfying the "concrete second consumer"
  rule. The 008 feature bundles three things: (a) extract
  `TaskSourceAdapter`, (b) retrofit Jira as the first implementation,
  (c) add the GitHub Issue adapter. Linear and others stay deferred until
  another concrete user need appears.
- **New agent**: trigger when a second agent (e.g., Codex CLI) is going to
  be used daily for at least a week. One short feature: add the driver +
  config flag. No adapter needed.
- **New messenger**: trigger when a second messenger (e.g., Slack) is
  actually going to be used in the same way, or upon entering Phase 5 per
  ARD D3. At that point a single feature should bundle three things:
  (a) extract the `MessengerAdapter`, (b) retrofit Telegram as the first
  implementation, (c) add the second adapter. Doing the abstraction during
  the first implementation alone would lock the interface in before the
  second consumer's actual requirements are known — a textbook
  over-engineering trap.

### Invariants before / after

- Constitution §III (`1 task = 1 worktree = 1 branch`) is invariant under
  any task-source / messenger / agent swap.
- The stdout protocol (007 super-set) is agent-agnostic; only grows, never
  shrinks.
- The daemon never holds GitHub-API credentials (D5 / D7); the agent-side
  creates the PR and the daemon simply relays the URL. The same
  delegate-down posture applies to task-source credentials — the daemon
  never holds Jira / GitHub Issue tokens.

---

## 7. References

- Multica: https://github.com/multica-ai/multica
- Claude Agent SDK (Python): `claude-agent-sdk`
- Telegram Bot API — Forum topics: https://core.telegram.org/bots/api#forum-topic-actions
- XDG Base Directory: https://specifications.freedesktop.org/basedir-spec/

---

## 8. Change log

| Version | Date | Author | Notes |
|---|---|---|---|
| 0.1 | 2026-05-01 | Samuel | Initial draft |
| 0.2 | 2026-05-02 | Samuel | Five-layer doc split: architecture moved to `ARCHITECTURE.md`, decision log to `ARD.md`. Functional-requirement detail / SQLite schema / HTTP-API specs delegated to spec / code; PRD slimmed to product-layer trunk. |
| 0.3 | 2026-05-03 | Samuel | §6 "Extensibility direction" added — messenger / agent swap cost asymmetry and adoption triggers spelled out. Adapter infrastructure deferred until a concrete second consumer appears. |
| 0.4 | 2026-05-03 | p-acid | Task source generalised: §1 Direction, §2 In-scope, §3 persona, and §6 updated to treat the source-of-truth (Jira / GitHub Issue / Linear) as a per-install configurable axis alongside messenger / agent. GitHub Issue is the second concrete provider, landing in 008 (the matching ARD entry is added in that PR alongside the ARCHITECTURE update, per the "ARD and ARCHITECTURE move together" rule). Owner field updated to p-acid. |
