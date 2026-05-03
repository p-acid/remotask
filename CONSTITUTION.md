<!--
SYNC IMPACT REPORT
==================
Version change: 1.1.0 → 1.2.0
Bump rationale: Principle V ("Spec-Driven Development") relaxed so that the
  single-file spec form (`specs/NNN-<name>.md` derived from
  `docs/templates/SPEC.md`) is also acceptable, in addition to the earlier
  multi-file form. The constraint is on the *artefacts* (motivation + behaviour
  + acceptance tests + tasks), not the file count. MINOR per the project's
  amendment policy because no principle is removed and the change is purely
  additive (the relaxation *expands* the set of valid spec shapes rather than
  narrowing it).

  This bump also accompanies two non-semantic refactors that landed in the
  same change:
  - File moved from `.specify/memory/constitution.md` to root `CONSTITUTION.md`
    (rename detected by git).
  - Body fully translated to English (was Korean prose around English headings).

Modified principles:
  - V. Spec-Driven Development: form requirement softened. Both the
    single-file spec at `specs/NNN-<name>.md` and the multi-file
    spec/plan/research/contracts/quickstart/tasks layout are accepted. The
    "30-min, ≤1 file trivial fix" exemption is unchanged. Spec-kit-specific
    slash command names (`/speckit-*`) removed from the workflow text — the
    project no longer ships those skills (see ARD D23).

Added sections:
  - None.

Removed sections:
  - None.

Templates requiring updates:
  - ✅ CONSTITUTION.md                          (this file, amended + relocated + translated)
  - ✅ docs/templates/SPEC.md                   (already TDD-explicit single-file form, aligned)
  - ✅ docs/PRD.md / docs/ARCHITECTURE.md /
       docs/ARD.md / README.md / CLAUDE.md      (already point to ./CONSTITUTION.md or ../CONSTITUTION.md)
  - ⚠ .specify/templates/*                     (slated for removal in T9 — no fix needed)
  - ⚠ .claude/skills/speckit-*                 (slated for removal in T10 — no fix needed)

Follow-up TODOs:
  - None.
-->

# Remotask Constitution

## Core Principles

### I. Jira as Single Source of Truth (NON-NEGOTIABLE)

Jira is the single source of truth for every task and issue.

- We do not model an internal task / issue / workspace domain.
- Work context (title, description, comments, status) is always fetched from
  Jira and never permanently mirrored locally.
- Our SQLite stores **execution metadata only** (sessions, projects, locks,
  events).
- When Jira and our system disagree, Jira wins.

**Rationale**: This is the very reason we did not build our own workspace.
Dual-write and synchronisation cost is not affordable for a single-operator
self-hosted tool.

### II. Daemon-Centric Architecture

Business logic and system privileges live in the daemon.

- The CLI, the web UI (Phase 2+), and the Telegram bot are all **clients of
  the daemon's HTTP API**.
- The daemon is an independent process managed by launchd, and it runs
  regardless of which client is alive.
- Filesystem, git, and external calls are made by the daemon only. Clients
  only command and display.
- Authentication is enforced at a single entry point on the daemon (Bearer
  token plus the Telegram whitelist).

**Rationale**: Closing the GUI must not stop Telegram trigger handling, and
forcing every execution path through the same abstraction is what makes
consistency and auditing possible.

### III. Strict Session Isolation (NON-NEGOTIABLE)

Session isolation enforces a **1:1:1 mapping** (presentation channel is a
separate layer).

- **1 Jira issue = 1 git worktree = 1 git branch.**
- Concurrent sessions are fully isolated in filesystem and git context.
- Operations that touch shared resources (lockfile, DB migrations, package
  installs) are serialised through advisory locks.
- Re-triggering the same issue while a session is active is rejected, or
  must be an explicit takeover.
- **Telegram channel mapping** (1:1 DM thread, group forum topic, future
  web UI, …) is a presentation-layer decision and is not part of the
  constitutional isolation model. The chosen mapping must, however, be
  declared in the feature spec and remain auditable.

**Rationale**: In an unattended-execution setting, context bleed and lost
work erode trust immediately. The essence of isolation is filesystem and
git state; the Telegram channel mapping is a UX decision and must be free
to evolve separately (e.g., 005 keeps the forum-topic model but
canonicalises `/done` into `/cancel` and adds the `[<issue_key>]` prefix
for multi-session readability — those are presentation-layer changes).
Even when only one session can run at a time, worktree and branch isolation
must be enforced from day one.

### IV. MVP-First, Incremental Hardening

Each Phase has explicit entry and exit criteria, and we do not pre-invest
infrastructure into unvalidated value.

- The shortest path to validating the core value (remote trigger) is the
  definition of MVP.
- Until Phase 1 (MVP) is complete, the following are not introduced:
  - Multiple concurrent sessions (`max_concurrent ≥ 2`)
  - Web GUI / monitoring dashboard
  - External exposure (Tailscale, Cloudflare Tunnel)
  - Desktop apps (Tauri etc.)
  - Alternative channels such as Slack
- Entering a new Phase requires the previous Phase's value to be validated.
- "What if we need it later" is, on its own, sufficient grounds for refusal.

**Rationale**: In a single-operator tool, infrastructure built in advance
becomes maintenance cost. Aligns with PRD §12 roadmap and decision D17.

### V. Spec-Driven Development

Every meaningful change is driven by a written spec — motivation,
behaviour, acceptance tests, and tasks are recorded *before* implementation
lands.

- The default form is a single-file spec at `specs/NNN-<name>.md`, derived
  from [`docs/templates/SPEC.md`](docs/templates/SPEC.md). The template is
  TDD-explicit: acceptance tests are listed as failing-now / passing-when-done
  assertions, and the task ordering puts the test-writing task first.
- The earlier multi-file form (`spec.md` plus `plan.md` / `research.md` /
  `contracts/` / `quickstart.md` / `tasks.md` under a per-feature folder) is
  also acceptable. The constraint is on the *artefacts* (motivation +
  behaviour + acceptance tests + tasks), not on the file count.
- Off-spec implementation is forbidden. Only trivial bug fixes (under
  30 minutes and touching ≤1 file) are exempt.
- Spec and implementation are reviewed in the same PR.
- No spec, no review or merge.
- Every non-trivial action an AI agent runs autonomously must have a spec.

**Rationale**: In an unattended-execution setting, traceability between
intent and implementation is a precondition for safety. Aligned with PRD §13
and ARD D18 / D23.

### VI. Security by Default

The default is the safest setting; risk is enabled only through the user's
explicit action.

- The daemon's HTTP listener binds to `127.0.0.1` only by default. External
  exposure requires explicit user opt-in.
- All tokens and secrets are stored either in 0600 files or in the macOS
  Keychain.
- The Telegram user-ID whitelist is mandatory; an empty whitelist makes the
  daemon refuse all triggers.
- The following commands are denied by default:
  - `git push --force` (force-with-lease is a separate option)
  - `git reset --hard`, `git clean -fd`
  - `rm -rf <absolute path>`, `sudo *`
- Bypassing the deny list is allowed only after the user confirms on the
  phone, and only one-shot.
- Tokens must be rotatable (`config regenerate-token`).

**Rationale**: Unattended automatic execution plus an external trigger
surface means the blast radius of a security incident is large. No
exemption for single-operator setups.

### VII. Observability & Auditability

Automatic execution runs without human supervision, so post-hoc traceability
must be guaranteed.

- All logs are structured (JSON lines), stored under
  `~/.local/share/remotask/logs/`.
- Every session start, end, and failure is recorded into SQLite `sessions` +
  `session_events`.
- The following actions are written to a separate audit log:
  - External network calls
  - git destructive commands
  - Deny-list bypass approvals
  - Token issuance and rotation
- The daemon health endpoint (`GET /api/health`) must always be available.
- Log rotation follows a fixed policy (10 MB × 5).

**Rationale**: If we cannot trace "what was done autonomously yesterday",
trust collapses and the system itself becomes unusable.

## Architecture & Technology Constraints

### Language and runtime
- The daemon and the CLI are a single language: Python 3.11+.
- No separate API key — Claude Code's OAuth credential is used via
  `claude-agent-sdk`.
- The package manager is uv. User installation is `uv tool install .`.

### Directory standard
- User data follows the XDG Base Directory specification:
  - Configuration: `~/.config/remotask/`
  - State (DB / logs / sockets): `~/.local/share/remotask/`
  - Cache: `~/.cache/remotask/`
- No per-user state inside the project tree.

### IPC
- All daemon ↔ client communication runs through a single HTTP/WebSocket
  interface (`127.0.0.1:6789`).
- No additional IPC mechanism (Unix socket, named pipe, …) is introduced (D14).

### Dependency policy
- Adding a new external dependency requires explicit justification in the
  spec.
- "Convenience" alone is not sufficient justification.
- If the standard library or an already-adopted library can do the job,
  prefer it.

## Development Workflow

### Change flow
1. Define the change intent in the PRD or in an issue.
2. Write a feature spec at `specs/NNN-<name>.md`, derived from
   [`docs/templates/SPEC.md`](docs/templates/SPEC.md). The template enforces
   motivation → behaviour → acceptance tests (failing-now / passing-when-done)
   → tasks (test-first by default) → out-of-scope → constitution check.
3. Resolve any open ambiguity in the spec (clarify questions inline; do not
   leave `[NEEDS CLARIFICATION]` markers in the merged version).
4. Run the **Constitution Check** inline in the spec — every one of the
   seven principles must be addressed (PASS / waiver with justification).
5. Implement test-first per the task ordering. Each acceptance test must
   start red and end green.
6. Open a PR containing both the spec and the implementation.
7. After merge, add a 5–15-line section to `CHANGELOG.md`.

### Constitution Check gate
- Every spec explicitly evaluates fit against each of the seven principles.
- A waiver requires the spec to record:
  - Which principle is being violated
  - Why the waiver is necessary
  - Why simpler alternatives were rejected

### Review and merge
- Spec and implementation are reviewed in the same PR.
- Auto-generated PRs (created by the daemon) still require human merge
  approval — auto-merge is forbidden.
- A principle violation that is not recorded as a waiver is a merge blocker.

### Branching
- All work is performed in an issue-scoped worktree and branch.
- Direct push to main is forbidden. Force-push is on the deny list.

## Governance

### Precedence
This constitution outranks every other document and convention, including
the PRD. When the PRD conflicts with the constitution, the constitution
wins.

### Amendment procedure
1. The proposer captures the change rationale and impact in a spec.
2. The constitution file is updated.
3. The Sync Impact Report is refreshed and dependent documents are updated
   in lockstep.
4. The version number is bumped per the following rules:
   - **MAJOR**: Removing a principle or making an incompatible governance
     change.
   - **MINOR**: Adding a new principle or section, or materially expanding
     existing guidance.
   - **PATCH**: Wording, typos, non-semantic clean-up.
5. The constitution change lands as a standalone commit
   (`docs: amend constitution to vX.Y.Z`).

### Compliance review
- Every PR reviewer is responsible for confirming the change conforms to
  the constitution.
- Auto-PRs (created by the daemon) are held to the same standard.
- A principle violation that lacks a recorded waiver is a merge blocker.

### Runtime guides
- [`CONSTITUTION.md`](./CONSTITUTION.md) (this file) — principles
- [`docs/PRD.md`](./docs/PRD.md) — product definition and decision log
- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) — current system shape
- [`docs/ARD.md`](./docs/ARD.md) — decision history (D1, D2, …)
- [`CLAUDE.md`](./CLAUDE.md) — AI-agent runtime behaviour guide
- Precedence on conflict: this constitution > `docs/PRD.md` >
  `docs/ARCHITECTURE.md` > `docs/ARD.md` > everything else.

**Version**: 1.2.0 | **Ratified**: 2026-05-01 | **Last Amended**: 2026-05-03
