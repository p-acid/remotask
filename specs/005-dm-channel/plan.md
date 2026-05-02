# Implementation Plan: `/cancel` Rename + `[KEY]` Prefix + Alias Deprecation

**Branch**: `005-dm-channel` (folder name retained from initial draft) | **Date**: 2026-05-02 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/005-dm-channel/spec.md`

## Summary

Rename the operator-stop slash command from `/done` to `/cancel` (canonical), keep the existing 003/004 forum-group + per-session-topic channel model unchanged, add a `[<issue_key>]` prefix to every session-bound progress / final / canceled message via a single chokepoint, and ship a one-release deprecation window for the four legacy alias tokens (`/done`, plain-text `done` / `stop` / `finish`) with a structured-log `WARNING` per first use per (alias, session) pair. The `setMyCommands` curated payload becomes `{run, cancel, status}` (drop `done`). No DB migration. No new config fields. Constitution v1.1.0 (already amended) is the basis.

The initial draft of this feature proposed a transition to a 1:1 DM channel; that scope was reverted after operator review preferred forum-topic visual separation for `max_concurrent ≥ 2`. See spec.md "Scope decision" for the change rationale.

## Technical Context

**Language/Version**: Python 3.11+ (constitution and 001–004).
**Primary Dependencies**: existing — `httpx`, `claude-agent-sdk`, `typer`, `pydantic`, `structlog`, `pytest-asyncio`. **No new runtime dependency.**
**Storage**: existing SQLite at `~/.local/share/remotask/state.db`. **V0001 schema is sufficient — no migration.**
**Testing**: `pytest` + `pytest-asyncio`, existing `tests/fakes/fake_telegram.py`. New / modified tests focus on the `/cancel` slash-command path, alias deprecation hooks, the `format_progress` chokepoint, and the curated-command registry delta.
**Target Platform**: macOS (primary; launchd from 001), Linux (best-effort).
**Project Type**: single-project CLI + long-running daemon. Same layout as 002/003/004.
**Performance Goals**: cancel-to-final under 10 seconds (SC-001 inherited from 003/004).
**Constraints**:
- Backwards-compat is hard-required for 002 plain-text Jira-key triggers (FR-015), 003 plain-text aliases (FR-016, with deprecation WARNING), and 004 `/run` / `/status` (FR-017).
- The 003/004 forum-group channel model is preserved unchanged (FR-019). `Manage Topics` permission requirement stays.
- No DB migration (FR-018).
- One release deprecation window: aliases removed in 006, not 005.
**Scale/Scope**: 1–3 active sessions per day, single concurrent session by default (`max_concurrent=1`); design supports the `max_concurrent ≥ 2` case where the `[KEY]` prefix has the most visual value.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **I. Jira as Single Source of Truth**
  - `issue_key` continues to be the routing token for `/run`, `/status`, and the new `[KEY]` prefix. No change to the SoT.
- [x] **II. Daemon-Centric Architecture**
  - All new logic — `/cancel` handler, alias deprecation hook, `format_progress` chokepoint — lives in the daemon. CLI surface unchanged.
- [x] **III. Strict Session Isolation** (constitution v1.1.0)
  - The amended invariant is `1 issue = 1 worktree = 1 branch`. The forum-topic correspondence is presentation-layer, preserved unchanged from 003/004. The amendment was made for the original DM-scope draft but holds equally well under the narrowed scope: topic mapping remains a presentation choice, not a constitutional invariant.
- [x] **IV. MVP-First, Incremental Hardening**
  - Aliases are time-boxed (removed in 006). No new infrastructure (no chat-type detection, no migration code, no reply-to plumbing — all dropped from rev 1). Each excluded item appears in spec "Scope decision" or Out-of-scope.
- [x] **V. Spec-Driven Development**
  - Plan derives from `specs/005-dm-channel/spec.md` rev 2 with four clarifications recorded. Scope-decision section explicitly documents the rev 1 → rev 2 narrowing.
- [x] **VI. Security by Default**
  - Whitelist gate, topic gate, and forum-group access model are unchanged. No new external bindings, no new secrets.
- [x] **VII. Observability & Auditability**
  - One new event type (`alias_deprecation_used`); `slash_command_rejected.reason` gains `main_chat_cancel`. `slash_command_received.command` gains `cancel`. No `listener.state` schema change.

All seven gates **PASS**. No Complexity Tracking entries needed.

## Project Structure

### Documentation (this feature)

```text
specs/005-dm-channel/
├── plan.md                        # This file
├── research.md                    # Phase 0 output (8 decisions, narrowed scope)
├── data-model.md                  # Phase 1 output (no schema delta; new audit + curated-set delta)
├── contracts/
│   └── cancel-command-protocol.md # Dispatcher decision tree + /cancel grammar + alias hook + format_progress
├── quickstart.md                  # Manual verification (forum-group flow + cancel/alias/prefix)
├── checklists/
│   └── requirements.md            # Spec quality (re-validated after rev 2 rewrite)
└── tasks.md                       # Created later by /speckit-tasks
```

### Source Code (repository root)

```text
src/remotask/
├── core/
│   └── config.py                  # NO CHANGE
├── telegram/
│   ├── client.py                  # NO CHANGE (no get_chat, no reply_to_message_id plumbing)
│   ├── parser.py                  # MODIFIED: add /cancel to recognised slash commands; match_termination_command unchanged
│   └── commands.py                # MODIFIED: CURATED_COMMANDS becomes (run, cancel, status); drop done
├── daemon/
│   ├── runtime.py                 # MODIFIED: + alias_deprecation_warned in-memory set, + clear-on-terminal hook
│   ├── dispatcher.py              # MODIFIED: + /cancel branch, + /done deprecation WARNING wrapper, + plain-text alias deprecation WARNING wrapper, + main_chat_cancel reason
│   ├── worker.py                  # MODIFIED: route session-bound posts through topic.format_progress (the chokepoint)
│   ├── topic.py                   # MODIFIED: + format_progress(issue_key, body) helper. create_topic_for_session unchanged.
│   ├── audit.py                   # MODIFIED: + EV_ALIAS_DEPRECATION_USED, + main_chat_cancel reason value
│   ├── listener_state.py          # NO CHANGE
│   └── ...                        # listener / sessions unchanged
├── commands/
│   └── telegram.py                # NO CHANGE
└── ...

tests/
├── unit/
│   ├── test_telegram_parser.py    # MODIFIED: + /cancel slash-command parser cases
│   ├── test_dispatcher.py         # MODIFIED: + /cancel happy path, + main_chat_cancel reject, + alias deprecation WARNING coverage
│   ├── test_commands_registry.py  # MODIFIED: pin {run, cancel, status} (drop done)
│   ├── test_topic_format.py       # NEW: format_progress prefix cases (prefixed vs key-bearing templates)
│   └── test_runtime_alias_warned.py  # NEW: idempotency of alias_deprecation_warned set
├── fakes/
│   └── fake_telegram.py           # NO CHANGE
└── integration/
    ├── test_cancel_canonical.py   # NEW: /cancel happy path (replaces 004's /done test in spirit)
    ├── test_alias_deprecation.py  # NEW: /done + plain-text done/stop/finish still cancel + WARNING logged + idempotent
    ├── test_key_prefix.py         # NEW: progress lines carry [KEY], Session-starting templates do not
    └── test_backwards_compat.py   # NEW: 002 plain-text trigger + 003 plain-text aliases + 004 /run /status all unchanged
```

**Structure Decision**: 005's narrowed scope keeps the layout 1:1 with 004. The two new helpers (`format_progress` in topic.py, `alias_deprecation_warned` set on Runtime) live in modules that already existed; the modifications are surgical. No file is renamed or removed.

## Phase 0: Outline & Research

(see `research.md`)

8 research items resolved:

1. **`/cancel` slash-command grammar** — arg-less, topic-context resolution (mirror of 004's `/done`).
2. **Deprecation-warning idempotency** — per-(alias, session) tuple set on Runtime, cleared on terminal transition.
3. **`[KEY]` prefix chokepoint** — `topic.format_progress(issue_key, body)`; key-bearing templates skip it.
4. **Curated command registry delta** — `(run, done, status)` → `(run, cancel, status)`; setMyCommands idempotent overwrite.
5. **Distinguishing `/cancel` vs `/done` audit reasons** — gain `main_chat_cancel`, retain `main_chat_done` for the alias path.
6. **Plain-text alias scope** — 003's matcher unchanged; do not add bare `cancel`.
7. **`topic.py` rename** — keep the name; no functional gain in renaming.
8. **`[KEY]` prefix forward-compatibility** — helper is channel-agnostic; future single-channel surfaces inherit it for free.

## Phase 1: Design & Contracts

(see `data-model.md`, `contracts/`, `quickstart.md`)

1. **Data model** (`data-model.md`):
   - **No schema delta.** V0001 stays.
   - Documents Runtime's in-memory `alias_deprecation_warned` set (lifecycle, cleanup).
   - Documents the new audit event type `alias_deprecation_used` + the `main_chat_cancel` reason addition + the `command="cancel"` value.
   - Documents the curated-command registry delta and the outbound message catalogue (which messages get prefixed and which don't).

2. **Contracts**:
   - `cancel-command-protocol.md`: the dispatcher decision tree adapted to include `/cancel` (canonical) and `/done` (alias) branches, the plain-text alias deprecation hook, and the `format_progress` chokepoint usage.

3. **Quickstart** (`quickstart.md`): manual operator flow on the existing 003/004 forum-group setup — happy `/cancel`, `[KEY]` prefix verification, alias paths (`/done`, plain-text `stop`), audit-log inspection, autocomplete-menu inspection.

4. **Agent context update**: `CLAUDE.md` already points at `specs/005-dm-channel/plan.md` (set in rev 1; no change in rev 2). Rev 2 keeps the active-feature pointer; the spec's narrowed scope flows transparently from the new spec.md content.

## Phase 2 (deferred to /speckit-tasks)

Task decomposition is produced by the next command. This plan stops here per template instructions.

## Complexity Tracking

> No violations. Section intentionally empty.

## Scope decision history

| Rev | Date       | Decision                                              | Trigger |
|-----|------------|-------------------------------------------------------|---------|
| 1   | 2026-05-02 | Switch to 1:1 DM channel; remove forum topics         | Initial spec ("DM 모드로 전환…") |
| 2   | 2026-05-02 | Revert channel transition; keep forum topics; narrow 005 to /cancel rename + [KEY] prefix + alias deprecation | Operator review concluded that topic-based visual separation outweighs DM simplicity for `max_concurrent ≥ 2` |

The dropped rev 1 items (channel transition, chat-type detection, migration notice, dm_chat_id config rename, reply-to threading, getChat plumbing) are not deferred to a future feature — they are simply removed. If a future feature needs any of them, that feature can re-derive the design without inheriting rev 1's plumbing.
