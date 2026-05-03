# 008 — Task source adapters (Jira retrofit + GitHub Issue)

> Single-file spec. Lives at `specs/008-task-source-adapters.md`. After merge,
> the file need not be retained — git history and `CHANGELOG.md` carry the
> durable record.

> **Test-first.** The *Acceptance tests* section below is the concrete contract;
> the tests that codify it are written **before** any implementation. Tasks are
> ordered red → green → manual smoke.

**Status**: draft
**PR**: #NN (filled in after merge)
**Related ARD**: D24 (introduced in this PR alongside the ARCHITECTURE.md
update, per the "ARD and ARCHITECTURE move together" rule). Specialises D1.
Touches D5 / D7 by analogy (delegate-down credential posture). References
D19 (§III scope), D22 (007 worker shape).

## Motivation

`PRD §6` (v0.4) made the task source-of-truth a per-install configurable axis
alongside the messenger and the agent, but the daemon today still hard-codes a
single shape: `telegram/parser.py:15` carries a Jira-flavoured `_ISSUE_KEY_RE`
(`[A-Z][A-Z0-9_]{1,9}-\d{1,6}`), `core/projects.py` keys the `projects` table
on `jira_key`, and `daemon/dispatcher.py` calls `split_prefix(key)` to look up
the repo. This is fine while Jira is the only consumer — and was the right
shape until now per `PRD §6`'s "extract on the second concrete consumer" rule.

The second consumer has now arrived. The author intends to dogfood remotask
development on remotask itself, where the source-of-truth is GitHub Issue, not
Jira. That makes 008 the textbook moment to do the abstraction: bundle (a) an
interface extraction, (b) a retrofit of the existing Jira path as the first
implementation, and (c) the GitHub Issue adapter as the second implementation,
all in one spec. Doing the abstraction during the first implementation alone
would have locked the interface in before the second consumer's actual shape
was known — exactly the over-engineering trap PRD §6 calls out for the
messenger axis.

The abstraction stays minimal because Constitution v1.2.0 (D23) already lifted
§I and §III to platform-neutral wording: §I now reads "the current external
tracker is Jira; the principle does not bind us to Jira specifically", and
§III now reads `1 task = 1 git worktree = 1 git branch` (with operator-channel
mapping carved out as a presentation-layer concern). The substance is
preserved by D24; no constitutional amendment is required.

## Behavior

From the operator's perspective:

**Picking a task source per install.** A new config field
`agent.task_source` (enum `"jira"` | `"github_issue"`) selects the active
provider. Exactly one provider is active per install — no multi-provider
routing, no `gh:` / `jira:` prefix grammar in the trigger surface. The field
is **required** — no default; the daemon refuses to start if it is missing
or empty. There is no production install whose existing config would
silently flip behaviour (single-operator pre-release dogfood), so an
explicit declaration costs one config line and removes a class of "why did
it pick Jira?" surprises.

**Trigger surface.** For a `"jira"` install, every observable behaviour from
002 / 004 / 005 / 007 is unchanged: an inbound message containing
`ZXTL-1234` is accepted; `/run ZXTL-1234` is accepted; the topic header reads
`[ZXTL-1234] ...`; the back-link from the agent's PR points at the Jira
issue. For a `"github_issue"` install, the same flow is driven by the GitHub
Issue adapter's key pattern and URL formatter; the operator sees the same
shape of behaviour with a GitHub-Issue identifier in place of the Jira key.

**Project mapping CLI.** `remotask projects add <identifier> <repo-path>`
accepts the active adapter's identifier shape. For Jira, that is the existing
2–10-uppercase prefix (`ZXTL`); for GitHub Issue, it is the canonical
`owner/repo` form (e.g., `p-acid/remotask`). One entry per `owner/repo` keeps
symmetry with Jira's "many prefixes per install" model — the "one active
provider per install" constraint binds the *provider*, not the *number of
repos under it*.

**Issue-key textual safety in fs / git.** Today's Jira keys (`ZXTL-1234`)
land directly in branch names (`agent/ZXTL-1234`), worktree paths
(`<root>/ZXTL-1234`), topic prefixes (`[ZXTL-1234] ...`), and DB columns. The
GitHub-Issue identifier shape contains characters that are not fs- or git-ref
safe (`/`, `#`), so the GitHub adapter normalises its key up front: the
adapter accepts `owner/repo#N` (or `#N` shorthand against the active project
mapping) on input from Telegram, then exposes a single fs/git-safe canonical
key (e.g., `gh-<repo>-<n>`) that flows verbatim through branch names,
worktree paths, topic prefixes, DB columns, and the 007 stdout protocol. The
operator pastes the natural GitHub form; the daemon's single-string
identity model (D24) stays intact.

**PR back-link.** When the agent emits `PR_URL=...`, the topic post that
quotes the source issue link uses `adapter.format_issue_url(key)` so the
back-link target shifts with the active provider.

**Daemon credential posture.** The daemon process holds no task-source
credential. `adapter.fetch_context(key)` runs in the worker subprocess (where
the agent already has access to its CLI tools and OAuth, per D5 / D7's
delegate-down posture) — not in the daemon. The GitHub Issue adapter reuses
the same `gh` CLI authentication that 007 already established for Draft-PR
creation: `gh issue view <key>` against the operator's host-level `gh auth
status`. Adding a separate PAT just for issue reads would only enlarge the
credential surface — a read-scoped PAT is strictly weaker than the existing
`gh` token, which already covers the PR-write path.

**Agent bootstrap prompt.** The daemon's worker driver composes a single
bootstrap prompt that carries the canonical key — and *only* the canonical
key — to the agent subprocess (the literal string today lives at
`agent/sdk_worker.py:398-401`). The prompt does **not** encode the active
provider's identity, name a specific operator-side automation, or branch
on `agent.task_source`. Any provider-aware behaviour (issue-context fetch,
PR back-link, status transition) is the responsibility of the agent-side
bootstrap, treated by this spec as an opaque operator-supplied script that
consumes a canonical key and resolves it through the `TaskSourceAdapter`
interface. This keeps the daemon spec operator-portable (different
operators may wire different bootstrap scripts) and preserves PRD §6's
invariant that the daemon is oblivious to which provider supplied the
issue. The stdout protocol (007 super-set) is unchanged.

**Schema (V0001 amended in place).** The project is in single-operator
pre-release state with no other users, so we edit `V0001__init.sql`
directly rather than ship a V0002 migration with backfill logic. Two tables
move:

- `projects`: `jira_key` is renamed to `source_identifier`; a `source` TEXT
  column is added; the primary key becomes the composite `(source,
  source_identifier)`. `core/projects.py` accessors switch to a `(source,
  identifier)` API in lockstep.
- `sessions`: two columns are added — `source` TEXT and `project_identifier`
  TEXT — that record which provider and which project produced the session.
  The existing `issue_key` column continues to hold the canonical
  fs/git-safe key (`ZXTL-1234` / `gh-remotask-42`) used for branch /
  worktree / topic / stdout, but `source` + `project_identifier` give the
  CLI / future web GUI a structured handle for grouping and filtering. The
  intent is that an operator can see — in one mixed view — "the first task
  is GitHub-Issue against project A, the second is Jira against project B"
  without parsing the canonical key string by hand.

Existing local `state.db` files are recreated from the amended V0001 on
daemon startup; manual cleanup (`rm ~/.local/share/remotask/state.db`) is a
one-line smoke step, not an automated migration path.

**What is invariant.** The dispatcher's accept-path shape, the
`sessions.transition` state machine, the topic chokepoint
(`format_progress`), the SIGUSR1 → grace → SIGTERM ladder, the 007 stdout
super-set, and the §III isolation invariant (`1 task = 1 worktree =
1 branch`) all hold unchanged across the swap. The daemon never *branches*
on which provider supplied the issue — it records the `(source,
project_identifier)` pair the adapter produced into the `sessions` row and
otherwise treats the canonical key as opaque. Provider-specific behaviour
lives behind the adapter interface (PRD §6 invariant).

## Acceptance tests

Each item is written as a failing-now / passing-when-done assertion. AT1–AT3
codify the Jira retrofit (behavioural parity with 002 / 004 / 007); AT4–AT7
codify the new GitHub-Issue surface; AT8–AT11 codify the abstraction-level
invariants (provider-tagged session rows, narrowed cross-provider
regression, audit event, adapter Protocol consistency).

- [ ] AT1 — Given `agent.task_source = "jira"` and a registered project
      `ZXTL → /tmp/repo`, when the dispatcher receives an inbound message with
      text `ZXTL-1234 fix the bug`, then the dispatcher accepts via the Jira
      adapter (extracted issue key = `ZXTL-1234`), inserts a session row, and
      creates the forum topic — i.e., 002's existing accept-path test passes
      unchanged after the retrofit.
- [ ] AT2 — Given `agent.task_source = "jira"` and **no** Jira-style project
      registered, when the dispatcher receives an inbound message with text
      `owner/repo#42`, then the dispatcher does not accept (the active Jira
      adapter's key pattern does not match), proving that the active adapter —
      not a hard-coded regex — owns the trigger gate.
- [ ] AT3 — Given the active provider is Jira and the worker emits
      `PR_URL=https://github.com/.../pull/7`, when the topic posts the
      session-bound back-link, then the formatted source-issue URL is the Jira
      adapter's `format_issue_url(key)` result (e.g.,
      `https://<jira-host>/browse/ZXTL-1234`).
- [ ] AT4 — Given `agent.task_source = "github_issue"` and a registered
      `p-acid/remotask` project mapping, when the dispatcher receives an
      inbound message containing `p-acid/remotask#42` (or `#42` shorthand
      against the single configured project), then the GitHub Issue adapter
      normalises the input to the canonical `gh-remotask-42` key, the
      dispatcher accepts, and the session goes through the same lifecycle as
      the Jira path — `enqueued → starting → running` transitions, lock
      acquisition, topic creation.
- [ ] AT5 — Given the active provider is GitHub Issue and the worker emits
      `PR_URL=...`, when the topic posts the session-bound back-link, then the
      formatted source-issue URL is the GitHub Issue adapter's
      `format_issue_url(key)` result (e.g.,
      `https://github.com/<owner>/<repo>/issues/<n>`).
- [ ] AT6 — Given a sanitisation policy is in force (per the *Behavior*
      clarification), when a session starts for a GitHub-Issue identifier
      whose textual form contains `/` or `#`, then the resulting branch name
      is a valid git ref (`git check-ref-format` returns 0) and the worktree
      directory exists at the expected sanitised path.
- [ ] AT7 — Given the daemon is running with the GitHub-Issue provider
      active, when a session is dispatched and the worker invokes
      `adapter.fetch_context(key)`, then the `os.getpid()` recorded inside
      the adapter equals the worker subprocess's PID and not the daemon's
      PID — proving the credential read crosses the process boundary, per
      D5 / D7's delegate-down posture.
- [ ] AT8 — Given two persisted sessions in `state.db` — one accepted by
      the Jira adapter against project `ZXTL` (issue_key=`ZXTL-1234`) and
      one accepted by the GitHub-Issue adapter against project
      `p-acid/remotask` (issue_key=`gh-remotask-42`) — when the CLI lists
      sessions, then each row exposes `source` and `project_identifier` as
      discrete columns so a future GUI can render the two task families
      mixed in one view or filtered to a single `(source, project)` pair.
- [ ] AT9 — Given a running GitHub-Issue session and an inbound `/cancel`
      slash command on its topic, when the dispatcher routes the cancel,
      then the SIGUSR1 → grace → SIGTERM ladder fires identically to a
      Jira session (003 / 005 timing intact) and the `[gh-remotask-42] ...`
      topic prefix is rendered through the same `topic.format_progress`
      chokepoint as `[ZXTL-1234] ...` — the operator-stop and topic-prefix
      surfaces are provider-agnostic.
- [ ] AT10 — Given a session is accepted under the active provider, when
      the dispatcher inserts the `sessions` row, then a single
      `EV_TASK_SOURCE_RESOLVED` event is appended to `session_events`
      carrying `{adapter: "<name>", source_identifier: "<id>",
      canonical_key: "<key>"}` and no other audit shape changes.
- [ ] AT11 — Given both `JiraAdapter` and `GitHubIssueAdapter` instances,
      when each is exercised against the `TaskSourceAdapter` Protocol
      surface (issue-key pattern matching, `fetch_context` shape,
      `format_issue_url` shape), then both return values matching the
      Protocol's documented types — verified at runtime by a parametrised
      test that runs the same assertions against each adapter.

## Tasks

Default ordering for behavioural changes is test-first.

- [ ] T1 — Write tests for AT1–AT11 against the desired post-state (new
      `tests/task_sources/test_jira_adapter.py`,
      `tests/task_sources/test_github_issue_adapter.py`,
      `tests/task_sources/test_protocol_consistency.py` (parametrised over
      both adapters for AT11), `tests/daemon/test_dispatcher_with_adapter.py`,
      `tests/daemon/test_sessions_provider_columns.py` (AT8 / AT10),
      `tests/daemon/test_cancel_provider_agnostic.py` (AT9)). Run the
      suite: confirm each new test fails for the expected reason (red).
- [ ] T2 — Define `TaskSourceAdapter` Protocol in
      `src/remotask/task_sources/__init__.py` with the three responsibilities
      (issue-key pattern / `fetch_context` / `format_issue_url`). No
      implementation yet — just the interface plus a `get_active_adapter(cfg)`
      factory.
- [ ] T3 — Implement `JiraAdapter` in `src/remotask/task_sources/jira.py`
      that wraps the existing 002 regex and the existing Jira URL convention.
      Make AT1 / AT2 / AT3 green. Delete `_ISSUE_KEY_RE` from
      `telegram/parser.py:15` (or have it delegate to the active adapter).
- [ ] T4 — Add `agent.task_source` config field to
      `src/remotask/core/config.py` as a **required** enum (no default; the
      pydantic validator rejects empty / missing). Wire the dispatcher's
      `extract_first_issue_key` call site to consult `get_active_adapter(cfg)`
      instead of the bare regex.
- [ ] T5 — Amend `src/remotask/migrations/V0001__init.sql` in place
      (no V0002): rename `projects.jira_key` → `projects.source_identifier`,
      add `projects.source` TEXT, switch the PK to composite `(source,
      source_identifier)`; add `sessions.source` TEXT and
      `sessions.project_identifier` TEXT. Update `core/projects.py`
      accessors to take a `source` argument and the session-insert site
      (`daemon/sessions.py` / `daemon/dispatcher.py:_accept_trigger`) to
      populate the new pair from the resolved adapter. Document
      `rm ~/.local/share/remotask/state.db` as the one-line refresh smoke
      step. Make AT8 green.
- [ ] T6 — Implement `GitHubIssueAdapter` in
      `src/remotask/task_sources/github_issue.py` per the chosen authentication
      mode. Make AT4 / AT5 / AT7 green.
- [ ] T7 — Implement the sanitisation layer (boundary or up-front, per the
      chosen *Behavior* policy). Make AT6 green.
- [ ] T8 — Confirm `agent/sdk_worker.py:398-401` composes the bootstrap
      prompt from the canonical key alone (no provider name, no
      `agent.task_source` value, no operator-script identifier baked in).
      Wire `EV_TASK_SOURCE_RESOLVED` emission in the dispatcher's accept
      path. Confirm AT9 / AT10 green. The operator-side bootstrap
      automation itself is out of scope per *Out-of-scope*.
- [ ] T9 — Update `docs/ARCHITECTURE.md` with the new `task_sources/` module
      row in §2 component table, the `agent.task_source` config field in §7,
      and a feature row in §8. Append D24 to `docs/ARD.md` (text recoverable
      from `git show 72a2beb -- docs/ARD.md`).
- [ ] T10 — Run the full suite + a manual smoke (one Jira-mode session and
      one GitHub-Issue-mode session against a real repo). All acceptance
      tests green; no regression on 003 / 005 / 007 paths.

## Out-of-scope

- Linear, an internal-API task source, or any third concrete provider.
  Deferred per PRD §6 until a third concrete consumer appears.
- Multi-provider routing within a single install (`gh:` / `jira:` prefix
  grammar in the trigger surface). Explicitly rejected: one active provider
  per install. Multi-*project* under the active provider is in-scope (Jira:
  many prefixes; GitHub: many `owner/repo` entries).
- Webhook-driven inbound triggers (the trigger surface remains Telegram-only
  per D2 / D3).
- Migrating any 002–007 contracts to use a non-string task identity.
- The actual mixed-provider list-view UI in the CLI / web GUI. 008 only
  ensures the schema (`sessions.source` + `sessions.project_identifier`)
  carries the structured data that view will need; the rendering is a
  separate spec.
- The operator-side bootstrap automation that resolves the canonical key
  into per-provider context (today: a Claude Code slash skill at
  `~/.claude/skills/<name>/`; could equally be a shell script, a CLI
  wrapper, or any other operator-supplied artefact). 008 specifies only
  the daemon-side prompt shape and the `TaskSourceAdapter` Protocol;
  concrete bootstrap automations live outside this PR and are not subject
  to its review.

## Constitution check

All seven principles evaluated. No waiver required.

- **I. External Source of Truth** — PASS. D24 specialises D1 by making
  *which* external SoT configurable while preserving the no-internal-workspace
  posture (each adapter is a thin read-and-URL-format wrapper around an
  external API). Constitution v1.2.0 already declares §I platform-neutral
  ("the current external tracker is Jira; the principle does not bind us to
  Jira specifically", `CONSTITUTION.md` L82–84) — no amendment needed.
- **II. Daemon-Centric Architecture** — PASS. The adapter modules live under
  `src/remotask/task_sources/`. The daemon-side change is thin: the
  dispatcher delegates `extract_first_issue_key` to the active adapter, and
  the topic chokepoint switches URL formatter. Business logic still flows
  through the same daemon process; clients still command-and-display.
- **III. Strict Session Isolation** — PASS. The §III invariant (`1 task =
  1 git worktree = 1 git branch`, `CONSTITUTION.md` L115) is preserved by
  D24's "task identity remains a single string per session, regardless of
  which provider produced it" clause. AT6 is the explicit gate — sanitisation
  must produce a valid git ref. D19 already moved the operator-channel
  mapping to the presentation layer, so no new constitutional surface is
  involved.
- **IV. MVP-First, Incremental Hardening** — PASS. PRD §6's "concrete second
  consumer" rule is now satisfied (Samuel dogfooding on GitHub Issue). Linear
  and others stay deferred until a third concrete consumer appears, per §IV.
  No infrastructure is introduced ahead of validated value (D17).
- **V. Spec-Driven Development** — PASS. This file is the artefact; the AT
  list maps 1:1 to test functions; T1 is test-first.
- **VI. Security by Default** — PASS. Daemon never holds task-source
  credentials — same delegate-down posture as D5 (no separate API key) and
  D7 (daemon does not hold GitHub PR credential). AT7 is the explicit gate.
  Tokens stored 0600 / Keychain on the worker / agent side per §VI.
- **VII. Observability & Auditability** — PASS, strengthened. Provider /
  project information is exposed in two places: (a) the `sessions` row
  itself carries `source` + `project_identifier` as discrete columns
  (AT8) — structured data the CLI / future web GUI can group on without
  parsing the canonical key; (b) one new event type
  `EV_TASK_SOURCE_RESOLVED` is appended to `session_events` per accept
  (AT10). No change to log rotation policy, audit-log format, or
  `audit.log` path.

## Notes

- This change introduces **D24** (`Introduce TaskSourceAdapter; add GitHub
  Issue as the second task source (008)`). The full draft text of D24 is
  preserved in git history at commit `72a2beb -- docs/ARD.md`; recover it
  with `git show 72a2beb -- docs/ARD.md` and re-paste into `docs/ARD.md` as
  part of T9 (per the "ARD ↔ ARCHITECTURE move together" rule, this is the
  PR where it lands).
- This change updates `docs/ARCHITECTURE.md` in the same PR: §2 component
  table gains a `TaskSourceAdapter` row pointing at
  `src/remotask/task_sources/`; §7 mentions the new `agent.task_source`
  config field; §8 gains an `008-task-source-adapters` feature row.
- `docs/PRD.md` v0.4 already references 008 in §6 ("trigger now (008)") and
  §3 ("GitHub Issue for personal / OSS repos including remotask itself"); no
  PRD update is required by this spec.
- `CHANGELOG.md` gets a 5–15-line `## 008 — ...` section appended on merge,
  with the PR link and `D24` reference.
- The legacy `_ISSUE_KEY_RE` constant on `telegram/parser.py:15` is removed
  in T3; any test that imported it directly is migrated to call
  `JiraAdapter().matches(text)`.
- V0001 is amended *in place* (T5) instead of shipping a V0002 migration.
  This is sound because there is no other user — the project is in
  single-operator pre-release state. A formal V0002 with backfill logic
  would have run against zero existing rows; the simpler choice aligns with
  CLAUDE.md §2 ("Simplicity First — no abstractions for single-use code").
- ARD D22 (007) records `/work-start` as the current operator's
  bootstrap realisation. 008's spec body intentionally avoids hard-coding
  that name so future operators can wire their own bootstrap (different
  skill name, plain shell script, etc.) without re-spec'ing the daemon.
  The contract is: daemon emits `<bootstrap-prompt> <canonical-key>`; the
  bootstrap consumes the key and uses `TaskSourceAdapter` for any
  provider-specific work.
- Forward-looking (out of 008's scope per *Out-of-scope*): once the CLI /
  web GUI exposes `sessions.source` + `sessions.project_identifier` as
  filter / group-by columns, an operator can render a mixed view such as
  "task #1 — GitHub-Issue, project A" / "task #2 — Jira, project B"
  without parsing the canonical key string. 008's schema unlocks that view
  without committing to its rendering shape now (PRD §6 — actually
  shipping that view is its own concrete consumer).
