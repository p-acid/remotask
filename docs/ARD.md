# Architecture Decision Record (ARD)

> The decision history behind **why** the system looks the way it does.
> "What it looks like right now" lives in [`ARCHITECTURE.md`](./ARCHITECTURE.md);
> "rules we never break" live in [`CONSTITUTION.md`](../CONSTITUTION.md).

Every entry is permanent. When a later decision overrides an earlier one we
*do not edit the older entry* — a new entry is appended and the older one is
preserved as historical record.

---

## D1 — Keep Jira as the SoT instead of modelling our own workspace

**Decision**: Do not model an internal task / issue / workspace domain. Our
SQLite holds execution metadata only (sessions / projects / locks / events).

**Rationale**: Avoids the dual-write and synchronisation cost a single-person
self-hosted tool cannot afford. (Equivalent to constitution §I.)

---

## D2 — Telegram as the primary trigger channel

**Decision**: The mobile trigger channel is a Telegram bot.

**Rationale**: Mobile UX immediacy and a good fit for a single-operator
workflow. Forum topics give us multi-session display out of the box. Lower
bot-registration friction than Slack.

---

## D3 — Slack is a Phase 5 option

**Decision**: Slack integration is out of scope for the initial range.

**Rationale**: Multiplexing channels in a single-operator setting only adds
complexity. Adopt when the need is real.

---

## D4 — Adopt the Claude Agent SDK (not the `-p` one-shot mode)

**Decision**: The worker is spawned through `claude-agent-sdk`, not the
`claude` CLI's `-p` one-shot mode.

**Rationale**: Bidirectional interaction and hook events are required for
rich monitoring and control. The one-shot mode is "call once and done", which
gives poor visibility into progress.

---

## D5 — No separate API key (delegate to the CLI's OAuth credential)

**Decision**: Do not provision a separate API key; reuse the `claude` CLI's
OAuth credential as-is.

**Rationale**: Lets the operator's Pro/Max subscription do the work and
shrinks the token-management surface.

---

## D6 — macOS Keychain is allowed but not required

**Decision**: The Telegram bot token is stored as a 0600 file by default.
Keychain integration is optional.

**Rationale**: Single-operator simplicity wins. Forcing a Keychain dependency
would mean rework when porting to another OS.

---

## D7 — Auto-create and push the PR; humans merge from the GitHub app

**Decision**: Automation stops at "Draft PR created and pushed". Merging is
performed by the user on the GitHub mobile app.

**Rationale**: Explicit user request. The merge decision stays with a human
for safety.

---

## D8 — Multi-session isolation via worktree + Telegram forum topic

**Decision**: Every session gets its own worktree and branch. Telegram
display is split per forum topic.

**Rationale**: Natural context separation. Note that since constitution
v1.1.0 (2026-05-02) the Telegram-channel mapping has been moved to the
presentation layer (see D19).

---

## D9 — Local web instead of a desktop app

**Decision**: From Phase 2 the GUI is delivered as a React web app. No
native desktop application.

**Rationale**: The daemon is the full-permission backend, so capability is
equivalent. Mobile browsers can reach it. Development velocity is much
higher.

---

## D10 — Desktop is a Phase 5 option (wrap the same React build with Tauri)

**Decision**: When desktop becomes desirable, wrap the same React build with
Tauri.

**Rationale**: Keeps a horizontal evolution path open. Adopting it up front
is overhead in a single-operator setting.

---

## D11 — Adopt Python

**Decision**: Daemon and CLI both run on a single language: Python 3.11+.

**Rationale**: claude-agent-sdk and the Telegram library are both mature in
Python; the language fits both daemon and CLI surfaces; cognitive load on a
single maintainer stays low.

---

## D12 — Adopt the XDG directory standard

**Decision**: User data is split across `~/.config`, `~/.local/share`, and
`~/.cache`.

**Rationale**: Friendlier to packaging and distribution down the line, and
consistent with other macOS / Linux tooling.

---

## D13 — typer subcommand structure from day one

**Decision**: Even a single command starts with a typer subcommand
structure.

**Rationale**: Avoids a future rewrite when the CLI grows. typer's
boilerplate is light enough that the up-front cost is negligible.

---

## D14 — Unify IPC over HTTP instead of Unix sockets

**Decision**: All daemon ↔ client communication runs through a single
HTTP/WebSocket interface (`127.0.0.1:6789`).

**Rationale**: CLI, web UI, and any future external trigger share the same
API, which collapses an entire abstraction layer. Unix sockets are unusable
from web/mobile, so we'd end up needing HTTP anyway.

---

## D15 — Run daemon and GUI as separate processes

**Decision**: The GUI is a separate process from the daemon.

**Rationale**: Closing the GUI must not stop trigger handling. launchd only
manages the daemon.

---

## D16 — Defer concurrency to Phase 3 (Phase 1 ships single-slot)

**Decision**: The MVP runs `max_concurrent = 1`. Multi-session arrives in
Phase 3.

**Rationale**: Validate queueing, locking, and isolation thoroughly first.
For a single-operator value proof, one slot is enough.

---

## D17 — No web GUI in the MVP

**Decision**: Validate the core value (remote trigger) first. CLI plus
Telegram is enough monitoring for now.

**Rationale**: Aligns with constitution §IV (MVP-First, Incremental
Hardening). Don't pre-invest infrastructure into unvalidated value.

---

## D18 — Adopt spec-kit and a `/speckit-*`-driven flow (later relaxed in D23)

**Decision**: Standardise around the PRD → spec → plan → tasks → implement
flow, starting from `/speckit-specify`.

**Rationale**: AI-collaboration friendly. In an unattended-execution setting,
traceability between intent and implementation is a precondition for
safety. (Equivalent to constitution §V.)

**Superseded by**: D23 — the `/speckit-*` 7-file pattern was retired in
2026-05-03 in favour of a single-file spec + append-only `CHANGELOG.md`. The
underlying principle (spec-driven, traceable) is preserved; only the form
was relaxed.

---

## D19 — Relax constitution §III "Strict Session Isolation" (v1.0.0 → v1.1.0, 2026-05-02)

**Decision**: Soften the 1:1:1:1 mapping in constitution §III to 1:1:1.
- Before: `1 Jira issue = 1 git worktree = 1 git branch = 1 Telegram forum topic`
- After: `1 Jira issue = 1 git worktree = 1 git branch` (Telegram-channel
  mapping is now a presentation-layer decision)

**Rationale**: 005 keeps the forum-topic model in place but guarantees
multi-session readability through a separate mechanism — the `[<issue_key>]`
prefix and the canonical `/cancel`. That made it unnecessary to encode the
channel mapping into the constitutional isolation model. Future presentation
forms (1:1 DM, web UI, …) can now be introduced via spec rather than
constitutional amendment.

**Spec ref**: [`CHANGELOG.md#v005`](../CHANGELOG.md#v005)

**Why MINOR bump**: This is invariant relaxation, not principle removal —
strictly additive (more implementation shapes are now allowed).

---

## D20 — `/cancel` as the canonical operator termination command (005)

**Decision**: The operator's slash command for ending an active session is
unified as `/cancel`. The curated `setMyCommands` set is `{run, cancel,
status}`.

**Rationale**:
- The DB's terminal status is `canceled`, so the slash word and the
  resulting state line up semantically.
- The Telegram BotFather autocomplete UI immediately conveys "this really
  cancels".
- The plain-text `done` grammar briefly used in 003 could collide with
  ordinary chat in a topic, so the control verb was promoted to an
  explicit slash.

**Spec ref**: [`CHANGELOG.md#v005`](../CHANGELOG.md#v005)

**Time-box**: The legacy `/done` slash plus plain-text `done` / `stop` /
`finish` were retained as deprecated aliases for one release and then
removed in the next (006) — see D21.

---

## D21 — Remove the four termination aliases (006)

**Decision**: Remove the four aliases that 005 had time-boxed for one
release (`/done` slash plus plain-text `done` / `stop` / `finish`).
`/cancel` is the sole termination command going forward.

**Rationale**:
- Honour 005's deprecation time-box.
- Plain-text `done` / `stop` / `finish` can occur incidentally in normal
  topic chat — separating control verbs from free-form text is safer.
- Dispatcher branches, the runtime in-memory set, and the worker callback
  are all retired together, shrinking the code surface.

**Spec ref**: [`CHANGELOG.md#v006`](../CHANGELOG.md#v006)

**Audit impact**:
- The `EV_ALIAS_DEPRECATION_USED` event and `REASON_MAIN_CHAT_DONE` reason
  constants are removed.
- Past audit-log lines containing those two strings are preserved per the
  append-only policy.

---

## D22 — Adopt real claude-agent-sdk integration (007)

**Decision**: Replace the placeholder `demo_worker` introduced in 003 with
a real `claude-agent-sdk`-based driver (`remotask.agent.sdk_worker`). When
the operator sends `/run <key>` the daemon creates a worktree and spawns
the driver subprocess inside it. The driver opens the session via the
operator's `/work-start <key>` slash skill and closes it via `/work-done`.
The permission policy is `permission_mode="bypassPermissions"`, and the
constitution §VI deny-list is enforced at a driver-level `PreToolUse` hook
(banned commands are blocked regardless of any per-tool prompt bypass).
Cooperative cancel preserves the 003 ladder via SIGUSR1 → asyncio Event →
`client.interrupt()`. Draft-PR creation is **agent-side** (the operator's
slash skill runs `gh pr create --draft` etc.); the driver scrapes
`PR_URL=(\S+)` from the assistant's message text and emits it back through
stdout. The daemon holds no GitHub credential.

The stdout protocol preserves 003's `PR_URL=` / `PROGRESS` / `FINAL` and
adds two line shapes (`STEP <body>`, `EVENT <type> <json>`) as a strict
super-set. `fake_agent` is kept as the 003–006 regression stand-in so the
regression surface stays minimal.

**Rationale**:
- Keeps the daemon thin (constitution §II): the SDK call is isolated in a
  worker subprocess; the daemon still owns only the stdout-line parser,
  state transitions, and the topic chokepoint.
- Preserves the constitution §VI deny-list invariant: the banned-command
  block that `bypassPermissions` would otherwise neutralise is re-enforced
  at the driver-level hook.
- Keeping Draft-PR creation agent-side avoids adding GitHub-PAT custody to
  the daemon, and leaves the PR template/metadata to the operator's slash
  skill design.
- The strict super-set extension of the 003 stdout protocol means none of
  the 003–006 integration tests need to change (the `fake_agent` stand-in
  emits no new shapes).

**Spec ref**: [`CHANGELOG.md#v007`](../CHANGELOG.md#v007)

**Constitution impact**: Constitution v1.1.0 unchanged. No waiver. The
plan's Constitution Check passes 7/7.

---

## D23 — Process overhaul: single-file spec + append-only CHANGELOG

**Decision**: Retire the spec-kit-driven 7-file spec pattern (`specs/<feature>/`
with `spec.md` + `plan.md` + `research.md` + `contracts/` + `quickstart.md` +
`tasks.md` + `checklists/`) in favour of a single-file spec at
`specs/NNN-<name>.md`, derived from [`docs/templates/SPEC.md`](./templates/SPEC.md).
Per-feature merge history moves to a single append-only `CHANGELOG.md` at
the repo root, with one 5–15-line section per feature in chronological
ascending order. The constitution is promoted from
`.specify/memory/constitution.md` to root `CONSTITUTION.md`. The `.specify/`
directory and the 14 `.claude/skills/speckit-*` packages are removed
entirely. Documentation root layout unifies under: `CONSTITUTION.md`,
`CLAUDE.md`, `CHANGELOG.md`, `README.md` at root; `PRD.md`,
`ARCHITECTURE.md`, `ARD.md`, `templates/SPEC.md` under `docs/`.

`CLAUDE.md` is rewritten as a Karpathy-style behavioural guide
(`forrestchang/andrej-karpathy-skills` §1–§4 verbatim) plus a §5 of
remotask-specific conventions. All durable docs converge on English.

**Rationale**:
- The 7-file pattern was heavy relative to the change size of recent
  features (006 was the clearest case — a 4-line behavioural change
  spawned a full folder). The durable value lived in the four top layers
  (CONSTITUTION / PRD / ARCHITECTURE / ARD); per-feature folders carried
  little long-term signal once a PR merged.
- A single short section per feature in `CHANGELOG.md` is enough to record
  motivation + key outcome + PR / ARD anchors. Anything deeper survives in
  the relevant ARD entry or the code itself.
- Removing spec-kit closes a maintenance surface (14 skill packages, the
  `.specify/` toolchain) that was no longer pulling its weight for a
  single-operator project.

**Constitution impact**: Two additive relaxations land together as
constitution v1.1.0 → v1.2.0 (MINOR — invariants are *expanded*, not
removed):
- **§V "Spec-Driven Development"**: form requirement softened. The
  single-file spec form is now the default; the multi-file form remains
  acceptable. The artefact constraint (motivation + behaviour + acceptance
  tests + tasks) is unchanged. The "<30-min, ≤1 file trivial fix"
  exemption is unchanged. `/speckit-*` slash command names removed from
  the workflow text.
- **§I "External Source of Truth"** (renamed from "Jira as Single Source
  of Truth") and **§III "Strict Session Isolation"**: lifted from
  platform-specific to platform-neutral wording. Jira is acknowledged as
  the *current* tracker rather than embedded in the principle. `1 Jira
  issue = ...` becomes `1 task = ...`. The §III presentation-layer
  carve-out is renamed "Operator channel mapping" with broader examples
  (Slack thread, web UI, …). Substance preserved: remotask remains a
  remote-execution pipeline with no internal workspace, and concurrent
  sessions remain 1:1:1 in filesystem and git state. Future tracker /
  channel swaps become spec-level decisions instead of constitutional
  amendments.

No waiver required.

**Spec ref**: [`CHANGELOG.md#v-process-overhaul`](../CHANGELOG.md#v-process-overhaul)

**Supersedes**: D18 (spec-kit + `/speckit-*` flow). The underlying
principle of D18 (spec-driven, traceable) is preserved in §V; only the
form was relaxed.

---

## D24 — Introduce `TaskSourceAdapter`; add GitHub Issue as the second task source (008)

**Decision**: Promote the task source-of-truth (today: Jira; next:
GitHub Issue) from a hard-pinned assumption to a per-install configurable
axis. Land the abstraction in feature 008 by bundling three things in one
spec: (a) extract a `TaskSourceAdapter` interface — five methods
(`matches` / `to_canonical` / `extract_project_identifier` /
`fetch_context` / `format_issue_url`) — (b) retrofit Jira as the first
concrete implementation, (c) add the GitHub Issue adapter. Exactly one
provider is active per install (`agent.task_source` config flag); no
provider-prefix routing logic is introduced.

**Rationale**: PRD §6's "trigger when a concrete second consumer appears"
rule is now satisfied — Samuel intends to dogfood remotask development on
GitHub Issue. Doing the abstraction during the first implementation alone
would have locked the interface in before the second consumer's actual
shape was known (the same over-engineering trap §6 calls out for
messengers); landing both consumers together is the textbook moment to
extract the interface. Single active provider per install keeps the
abstraction minimal: dispatcher-side key extraction stays a single
delegation chain (`adapter.matches → to_canonical →
extract_project_identifier`), no `gh:` / `jira:` prefix grammar leaks
into the trigger surface, and the "one ingest channel per Telegram chat"
mental model is preserved. Linear and others stay deferred until a third
concrete user need appears, per §IV (MVP-First).

**Relation to D1**: D1 ("keep the SoT external; do not model an internal
workspace") is unchanged. D24 specialises D1 by clarifying that the *which*
external SoT is configurable — Jira was incidental to the team's actual
usage in v0.1–v0.3, not a constitutional choice. The "no dual-write, no
internal workspace" property of D1 holds: each adapter is a thin read /
URL-format wrapper around an external API.

**Invariants preserved**:
- Constitution §III (`1 task = 1 worktree = 1 branch`) — task identity
  remains a single string per session, regardless of which provider
  produced it. The GitHub adapter normalises `owner/repo#N` (or `#N`
  shorthand) into a fs/git-safe canonical key
  `gh-<owner>-<repo>-<n>` up front so the daemon's single-string
  identity model holds verbatim.
- The daemon never holds task-source credentials. Same delegate-down
  posture as D5 / D7 for GitHub PR creation: the adapter runs on the
  worker subprocess (Python in-process for the dispatcher's pattern
  matching, but `gh issue view` shells out from the worker for actual
  fetches); the daemon stays oblivious.
- The 007 stdout protocol is unchanged. Worker bootstrap prompt carries
  only the canonical key.

**Schema impact**: V0001 amended in place (no V0002) — the project is in
single-operator pre-release state, so a formal migration would have run
against zero existing rows. `projects` keys on composite `(source,
source_identifier)`; `sessions` adds `source` + `project_identifier`
columns so a future GUI can render mixed-provider task families.

**New audit event**: `EV_TASK_SOURCE_RESOLVED` (payload `{adapter,
source_identifier, canonical_key}`), emitted from
`dispatcher._accept_trigger`.

**Spec ref**: `CHANGELOG.md#v008` (when 008 ships).

**Supersedes / Superseded by**: none. Specialises D1; does not supersede.

---

## How to add a new entry

New ARD entry shape:

```markdown
## DNN — Short decision title

**Decision**: One or two sentences.

**Rationale**: The core trade-off.

**Spec ref**: [`CHANGELOG.md#vNNN`](../CHANGELOG.md#vNNN) (when applicable).

**Supersedes / Superseded by**: D??? (when applicable — never overwrite an
earlier entry; add a pointer here instead).
```

Numbers increase monotonically. Check the last entry and use `+1` so the
same number is never reused by accident.
