# Implementation Plan: Telegram Slash-Command Surface

**Branch**: `004-slash-commands` | **Date**: 2026-05-02 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/004-slash-commands/spec.md`

## Summary

Add a curated slash-command surface to the existing Telegram listener so the operator can discover and invoke `/run`, `/done`, `/status` from Telegram's autocomplete menu (BotFather-style) without remembering the Jira-key regex from 003. The daemon registers the command set on its own bot via `setMyCommands` at listener startup; the dispatcher gains one new branch that detects `bot_command` message entities and routes them. The 003 plain-text Jira-key triggers and the `done`/`stop`/`finish` synonyms continue to work unchanged. `/run` accepts free-text args — when they begin with a Jira key (`PREFIX-NNN`) the existing 002 routing applies; otherwise the daemon falls back to a configured `agent.default_project_jira_key` and synthesises a topic name `run-<YYYY-MM-DD-HH-MM>-<slug>-<6-hex>`. Per-user-bot model unchanged: each operator's daemon registers commands on their own bot using their own token.

## Technical Context

**Language/Version**: Python 3.11+ (constitution / 001 / 002 / 003).
**Primary Dependencies**: existing — `httpx`, `claude-agent-sdk`, `typer`, `pydantic`, `structlog`, `pytest-asyncio`. **No new runtime dependency.** standard library: `re`, `secrets` (for the 6-char hex suffix).
**Storage**: existing SQLite at `~/.local/share/remotask/state.db`. **V0001 schema is sufficient — no migration.** All new behaviour fits existing columns; the synthetic `issue_key` from `/run` (free-text) reuses the column with a `run-…` shape.
**Testing**: `pytest` + `pytest-asyncio`, `tests/fakes/fake_telegram.py` extended with `setMyCommands` recording + a way to inject `bot_command` entities into pushed updates.
**Target Platform**: macOS (primary; launchd from 001), Linux (best-effort).
**Project Type**: single-project CLI + long-running daemon. Same layout as 002 / 003.
**Performance Goals**: autocomplete menu visible within 1 s after the operator types `/` (SC-001 — Telegram-client local). Slash-command dispatch latency budget identical to 003 (≤ 5 s trigger-to-acknowledgement on a typical home network).
**Constraints**:
- Per-user-bot model is the architectural constraint: registration is per-operator, on their own bot, with their own token. No shared infra.
- `setMyCommands` registration MUST be best-effort (FR-002): network failure cannot block listener startup.
- The dispatcher's existing whitelist + group-id gates (002) remain authoritative; slash commands do not bypass them.
- Backwards compatibility is hard requirement (SC-005): every 003 integration test must pass unchanged.
**Scale/Scope**: 3 commands, 1–3 sessions per day per operator, single concurrent session by default (002 `max_concurrent=1`). `/status` reply capped at 10 lines.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **I. Jira as Single Source of Truth**
  - `/run` with a Jira-key prefix routes through 002's prefix → repo lookup. `/run` with free-text args still hits a *registered* project (the configured default); we do not invent a Jira issue, we just allow a default routing target. No new task/issue/workspace domain introduced.
- [x] **II. Daemon-Centric Architecture**
  - All new logic — `setMyCommands` invocation, slash-command parsing, dispatcher branch, status reply formatting — lives in the daemon. CLI surface is unchanged. Clients (Telegram users) interact only with the bot.
- [x] **III. Strict Session Isolation**
  - The 1:1:1:1 mapping (issue / worktree / branch / topic) from 002 is preserved. Synthetic topic names from `/run` still produce a unique `issue_key` per session; the same-issue concurrency rule (002 FR-010) continues to apply.
- [x] **IV. MVP-First, Incremental Hardening**
  - Curated 3-command set, no per-user customisation, no LLM intent parsing. Each excluded item is named in the spec's Out-of-Scope or Assumptions.
- [x] **V. Spec-Driven Development**
  - This plan derives from `specs/004-slash-commands/spec.md` with five clarifications recorded in the spec's Clarifications section.
- [x] **VI. Security by Default**
  - Whitelist + group-id gates apply identically to slash commands. No new external bindings, no new tokens. setMyCommands uses the same outbound httpx client and bot token already in use.
- [x] **VII. Observability & Auditability**
  - Three new event types (`slash_command_received`, `slash_command_rejected`, `commands_registered`/`commands_registration_failed`); `listener.state` gains two new fields (`commands_registered`, `commands_registered_at`).

All seven gates **PASS**. No Complexity Tracking entries needed.

## Project Structure

### Documentation (this feature)

```text
specs/004-slash-commands/
├── plan.md                 # This file
├── research.md             # Phase 0 output
├── data-model.md           # Phase 1 output (no schema delta)
├── contracts/
│   ├── slash-command-protocol.md   # message grammar + dispatch decision tree
│   └── set-my-commands.md          # registered command set + Bot API call shape
├── quickstart.md           # Manual verification (autocomplete + /run + /done + /status)
├── checklists/
│   └── requirements.md     # Spec quality (already passing)
└── tasks.md                # Created later by /speckit-tasks
```

### Source Code (repository root)

```text
src/remotask/
├── telegram/
│   ├── client.py              # MODIFIED: add set_my_commands() method
│   ├── parser.py              # MODIFIED: add match_slash_command() returning a parsed record
│   └── commands.py            # NEW: curated command registry (single source of truth)
├── daemon/
│   ├── dispatcher.py          # MODIFIED: add slash-command branch ahead of issue-key path
│   ├── runtime.py             # MODIFIED: invoke setMyCommands at listener startup
│   ├── listener_state.py      # MODIFIED: add commands_registered + commands_registered_at fields
│   ├── audit.py               # MODIFIED: add 4 new event constants
│   ├── topic.py               # MODIFIED: add new outbound templates (status replies, /run usage hint)
│   └── ...                    # listener / worker / sessions unchanged
├── core/
│   └── config.py              # MODIFIED: AgentConfig.default_project_jira_key (optional, default empty)
└── ...

tests/
├── unit/
│   ├── test_telegram_parser.py    # MODIFIED: add slash-command parser cases
│   ├── test_dispatcher.py         # MODIFIED: add slash-command dispatch cases
│   └── test_commands_registry.py  # NEW: pin the curated command set
├── fakes/
│   └── fake_telegram.py           # MODIFIED: record setMyCommands calls; allow injecting bot_command entities
└── integration/
    ├── test_slash_run.py             # NEW: /run happy path (Jira-key + free-text)
    ├── test_slash_done.py            # NEW: /done graceful + topic-only
    ├── test_slash_status.py          # NEW: /status main-chat list + topic-detail
    ├── test_set_my_commands.py       # NEW: setMyCommands invoked at startup; survives 5xx (SC-006)
    └── test_backwards_compat.py      # NEW: 003 plain-text triggers still pass alongside slash commands
```

**Structure Decision**: Add a single new module `src/remotask/telegram/commands.py` to hold the curated command registry as the single source of truth — the dispatcher and the setMyCommands caller both import it, so the registered menu can never drift from what the dispatcher actually handles. Everything else is incremental modification of files 002 / 003 already touched. No new package; no schema migration.

## Phase 0: Outline & Research

(see `research.md`)

Key research items (all resolved before Phase 1):

1. **Where does setMyCommands belong in the runtime lifecycle?** — Decision: in `Runtime._async_main()` *after* the listener has performed at least one successful `getUpdates` call (proves token + network), but *before* the listener starts dispatching messages. This sequencing makes "commands registered" line up with "listener live" in the operator's mental model.
2. **bot_command entity offset semantics** — Telegram puts every slash command in the message's `entities` array as `{type: "bot_command", offset: <int>, length: <int>}`. Decision: only the entity at `offset == 0` qualifies as the message's command — anything later is treated as part of args. This matches the BotFather convention and avoids `/cancel` mid-sentence accidentally cancelling a session.
3. **`@<botname>` suffix handling** — In groups, Telegram clients append `@<botname>` to slash commands when the bot is one of multiple bots in the chat. Decision: strip the suffix during normalisation; the bot identity is already established by the token in use.
4. **Synthetic topic naming + collision handling** — Decision: `run-<YYYY-MM-DD-HH-MM>-<slug>-<6 hex>` (clarification Q3). Slug = first ≤ 20 chars lowercased, alnum + dash. The 6-char hex from `secrets.token_hex(3)` makes accidental same-minute same-slug collisions ~ 1/16M per pair.
5. **`/status` snapshot atomicity** — Decision: take a single SQL `SELECT` over `sessions WHERE status IN NON_TERMINAL_STATES ORDER BY enqueued_at DESC LIMIT 11` (10 + 1 to detect overflow). Single-query snapshot avoids partial views and is trivially small at our scale.
6. **`/run` argument parsing** — Decision: split args by leading `\s+` once. If the first token matches the issue-key regex (002), treat as Jira-key trigger and store the rest as `trigger_text`. Otherwise treat the whole args string as free-text and fall back to `agent.default_project_jira_key`.
7. **setMyCommands failure recovery** — Decision: log a warning, set `commands_registered=false` in `listener.state`, do **not** retry inside `_async_main` (we'd just hang the listener). Next listener restart re-attempts. Documented in spec Edge Cases.
8. **Privacy Mode interaction (SC-005 backwards compat)** — Decision: spec's recommended posture is OFF (clarification Q1), but the dispatcher must not assume either way. Slash commands work regardless; plain-text triggers depend on Privacy Mode being OFF. We test both postures explicitly in `test_backwards_compat.py`.
9. **Audit-event taxonomy positioning** — Decision: `slash_command_received` is *session-bound* (FK to the affected session), `slash_command_rejected` is unbound (audit.log only, V0001's NOT NULL FK), `commands_registered` / `commands_registration_failed` are unbound. Mirrors the 003 pattern.
10. **Curated command registry as source of truth** — Decision: a single module `telegram/commands.py` exports a typed list of `Command(name, description, handler_attr)`. setMyCommands serialises name+description; the dispatcher uses `handler_attr` to dispatch; tests pin the list.

## Phase 1: Design & Contracts

(see `data-model.md`, `contracts/`, `quickstart.md`)

1. **Data model** (`data-model.md`):
   - No schema delta. V0001 stays.
   - Documents the synthetic `issue_key` shape for free-text `/run` (`run-<YYYY-MM-DD-HH-MM>-<slug>-<hex>`) and the rule that it must be unique within the active set (the 6-hex suffix guarantees this).
   - Documents the four new `session_events.type` / `audit.log` event types and their payloads.
   - Documents the two new `listener.state` fields (`commands_registered`, `commands_registered_at`).
   - Documents the new `agent.default_project_jira_key` config field and validation.

2. **Contracts**:
   - `slash-command-protocol.md`: the inbound `bot_command` entity grammar, the dispatcher decision tree (whitelist → slash branch → 003 issue-key branch → silent ignore), the four reject reasons, the topic-vs-main-chat reply rules, the `/run` argument-routing decision tree.
   - `set-my-commands.md`: the curated command set (name + description + handler), the `setMyCommands` Bot API call shape (default scope), the registration lifecycle (success / failure / retry).

3. **Quickstart** (`quickstart.md`): manual operator flow on a real Telegram group — register commands, observe `/` autocomplete, `/run ZXTL-1234`, `/run free text`, `/done`, `/status`, plus the negative cases (Privacy Mode ON to confirm slash-only still works, non-whitelisted sender, main-chat `/done`).

4. **Agent context update**: switch the active feature pointer in `CLAUDE.md` to `specs/004-slash-commands/plan.md`. 003 stays referenced as the foundational predecessor.

## Phase 2 (deferred to /speckit-tasks)

Task decomposition is produced by the next command. This plan stops here per template instructions.

## Complexity Tracking

> No violations. Section intentionally empty.
