# Changelog

Per-feature history. **Append-only**, chronological ascending (oldest → newest).
New entries are appended to the **bottom** of the file. Each section stays
within 5–15 lines: motivation → key outcome → PR / ARD references. For deeper
detail, see the relevant ARD entry or the code itself.

> Introduced when `specs/`'s 7-file pattern was retired in favour of the
> single-file spec + history-stack model (process overhaul, merging
> 2026-05-03). Pre-overhaul spec material is recoverable via git history
> (the merge commit and the entry below).

## Contents

- [001 — CLI bootstrap](#v001)
- [002 — Telegram trigger](#v002)
- [003 — End-to-end demo workflow + operator-stop ladder](#v003)
- [004 — Telegram slash-command surface](#v004)
- [005 — `/cancel` canonical + `[KEY]` prefix chokepoint](#v005)
- [006 — Remove deprecated termination aliases](#v006)
- [007 — Agent SDK integration (placeholder → real claude-agent-sdk)](#v007)
- [Process overhaul (2026-05-03)](#v-process-overhaul)

---

<a id="v001"></a>

## 001 — CLI bootstrap

**Commit**: `bf2557d`

typer subcommand skeleton (`init / install / daemon / config / login /
sessions / projects`), XDG paths (`~/.config`, `~/.local/share`, `~/.cache`),
schema V0001, daemon shell, macOS launchd plist registration. Started with a
subcommand structure even for a single command so we wouldn't have to rewrite
later (D13).

<a id="v002"></a>

## 002 — Telegram trigger

**Commit**: `d861225` · later folded into PR #1

Plain-text issue-key extraction (US1), whitelist-fail rejection via audit log
(US2), active-session rejection (US3), forum-topic auto-creation + topic
isolation (US4). Established SQLite V0001 schema (`sessions / session_events
/ projects / locks`) and the audit dual-store pattern (session-bound → DB,
rejection / auth failure → JSON lines). Worker scaffolding only — the actual
workload arrived in 003.

<a id="v003"></a>

## 003 — End-to-end demo workflow + operator-stop ladder

**PR**: [#1](https://github.com/p-acid/remotask/pull/1)

Introduced the placeholder `demo_worker` — a deterministic workload that emits
the PROGRESS / FINAL stdout protocol — so the daemon-side end-to-end flow
(worktree creation, state transitions, topic posting, termination) could be
exercised without a real LLM. Defined the cooperative operator-stop ladder:
SIGUSR1 → grace → SIGTERM → 5 s → SIGKILL. The 003 stdout protocol
(`PR_URL=`, `PROGRESS i/N ts`, `FINAL i reason`) was preserved as a strict
super-set in 005 / 007.

<a id="v004"></a>

## 004 — Telegram slash-command surface

**PR**: [#2](https://github.com/p-acid/remotask/pull/2)

Exposed a curated set via `setMyCommands` for BotFather UI autocompletion
(`{run, done, status}` — `done` was renamed to `cancel` in 005). The
dispatcher now branches on `bot_command` entities first (slash commands), then
falls back to plain-text issue-key extraction, then rejection. `/run` accepts
either a Jira-key or free-text argument; `/status` has two modes — main-chat
summary and per-topic detail.

<a id="v005"></a>

## 005 — `/cancel` canonical + `[KEY]` prefix chokepoint

**PR**: [#3](https://github.com/p-acid/remotask/pull/3) · **ARD**: D19
(constitution §III relaxed v1.0.0 → v1.1.0), D20

Canonicalised the operator's session-termination command as `/cancel` so the
slash and the resulting DB terminal status (`canceled`) line up. All
session-bound outbound messages now flow through
`topic.format_progress(issue_key, body)` so they consistently carry the
`[<issue_key>]` prefix (multi-session readability). Constitution §III's
1:1:1:1 mapping was relaxed to 1:1:1 — Telegram-channel mapping moves to the
presentation layer. `/done` and the plain-text terminators were kept as
deprecated aliases for one release before being removed in 006.

<a id="v006"></a>

## 006 — Remove deprecated termination aliases

**PR**: [#4](https://github.com/p-acid/remotask/pull/4) · **ARD**: D21

Removed the four termination aliases that 005 had time-boxed for one release
(`/done` slash + plain-text `done` / `stop` / `finish`). `/cancel` is now the
sole termination command. Dispatcher branches, the runtime in-memory set, the
worker callback, and the audit constants were all retired at once.

<a id="v007"></a>

## 007 — Agent SDK integration (placeholder → real claude-agent-sdk)

**PR**: [#6](https://github.com/p-acid/remotask/pull/6) · **ARD**: D22

Replaced the 003 placeholder `demo_worker` with a real `claude-agent-sdk`
driver (`remotask.agent.sdk_worker`). One `/run <Jira-key>` from the operator
now drives an end-to-end flow that produces real code edits and surfaces a
Draft PR link in the topic. Permission policy is `bypassPermissions`, with
the constitution §VI deny-list re-enforced at a driver-side `PreToolUse` hook
using token-based `shlex` analysis (catches flag permutations and chained
commands). The 003 stdout protocol was extended as a strict super-set
(`STEP <body>` and `EVENT <type> <json>` added) so the existing `fake_agent`
regression suite continued to pass unchanged. Draft PR creation is
agent-side (the operator's own slash skills run `gh pr create --draft`); the
daemon holds no GitHub credential and only relays the URL. Four rounds of
CodeRabbit feedback were folded in (env allowlist, explicit `session_id`,
FINAL-emit race guard, deny-list hardening, and so on).

<a id="v-process-overhaul"></a>

## Process overhaul (2026-05-03)

**Branch**: `chore/process-overhaul` · **ARD**: D23 (pending)

Retired `specs/`'s 7-file pattern in favour of the single-file spec +
append-only `CHANGELOG.md` model. Moved the constitution from
`.specify/memory/constitution.md` to the root as `CONSTITUTION.md`. Removed
`.specify/` and `.claude/skills/speckit-*` entirely. `CLAUDE.md` was
rewritten as Karpathy-style behavioural principles (§1–§4, verbatim) plus a
§5 of project conventions. All durable docs were unified to English.
