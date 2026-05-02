# Feature Specification: Telegram Slash-Command Surface

**Feature Branch**: `004-slash-commands`
**Created**: 2026-05-02
**Status**: Draft
**Input**: User description: "Telegram slash-command trigger surface that registers a fixed command set on the user's own bot via the Bot API setMyCommands method (BotFather-style autocomplete). Keeps the existing per-user-bot model intact: each operator runs their own remotask daemon with their own bot token; setMyCommands is invoked from the daemon at startup using whatever bot_token sits in that operator's config.toml — no shared infrastructure, no central server. Adds a curated command set: /run (start a new session, takes free-text args after the command — used to drive a default project mapping or carry an explicit prefix), /done (graceful operator stop in the current topic, equivalent to 003's plain-text `done`), /status (list active sessions in the main chat or report current-topic session state). The dispatcher gains a new branch that recognises message entities of type bot_command and routes accordingly; the 003 plain-text Jira-key triggers and `done`/`stop`/`finish` keep working for backwards compatibility. New worker spawn path for /run with no issue-key suffix (synthesises a session id-based topic name and uses a configurable default project from config.toml). Audit trail extends with new event types for slash-command receipt and rejection. Scope explicitly excludes: per-user command set customisation, slash commands beyond run/done/status, LLM-driven free-text intent parsing, multi-bot per user. The goal is for an operator to be able to type "/" in any chat with their bot and see the same usable menu BotFather shows for itself, without having to remember Jira-key syntax."

## Clarifications

### Session 2026-05-02

- Q: Recommended Privacy Mode posture for documented setup? → A: **OFF** (cooperative). With Privacy Mode OFF, both surfaces co-exist: the slash-command menu is fully usable AND 003's plain-text Jira-key triggers continue to fire. Quickstart documents OFF as the recommended steady state; ON is allowed but degrades to slash-only.
- Q: Behaviour of `/done` posted in the main chat (no topic context)? → A: **Silent ignore** — same as 003's plain-text `done` in the main chat. No reply, no audit-bound event. Rationale: a single global "done" with multiple active sessions is ambiguous; the operator must use it inside a specific topic. Audit log captures the rejection at unbound level for diagnostics.
- Q: Synthetic topic name collision strategy when two `/run` invocations share the same minute + slug? → A: **Append a 6-char random hex suffix** (`run-2026-05-02-14-fix-the-cache-a3f9b1`). Collision probability becomes negligible without leaning on a sub-second timestamp that would be harder to read in a Telegram topic title.
- Q: setMyCommands scope on registration? → A: **Default scope (all chats)** — the menu is visible in 1:1 DMs with the bot AND in the configured group, mirroring BotFather's UX. The 003 group_chat_id gate still rejects non-group invocations at dispatch time, so the broader menu visibility is purely a discovery convenience.
- Q: Maximum lines in the main-chat `/status` reply? → A: **10 lines (most-recent-first)**, with a trailing "+ N more" hint when truncated. Telegram messages stay readable; pagination is explicitly out of scope.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Discover and use commands via "/" autocomplete (Priority: P1)

An operator opens the configured Telegram forum group and types `/` in the input box. The Telegram client shows a popup of three commands — `/run`, `/done`, `/status` — exactly the way it does in any conversation with [@BotFather](https://t.me/BotFather). The operator selects `/run`, types a short request after it, presses send, and a new session starts on their host with progress streaming back to the topic, identical to the 003 flow except that the trigger came from the menu instead of a remembered Jira key.

**Why this priority**: Without this, every operator has to memorise the Jira-key regex (`PREFIX-NNN`) before they can do anything. That is friction at the moment of greatest value (kicking off work). The autocomplete menu turns the bot into a discoverable interface, which is the single biggest UX win this surface buys.

**Independent Test**: With one whitelisted operator, one configured bot, and a daemon that has run at least once after this feature lands, type `/` in any private or group chat the bot is a member of. Confirm: (a) three entries appear (`/run — Start a new session`, `/done — End current session`, `/status — Show active sessions`), (b) tapping `/run` followed by free-text and send produces a new session in the configured group, (c) the session reaches a terminal state via the existing 003 worker pipeline.

**Acceptance Scenarios**:

1. **Given** an authorized operator and a daemon that has performed setMyCommands at least once, **When** the operator types `/` in the configured group's main chat, **Then** the Telegram client shows the three configured commands with their human-readable descriptions.
2. **Given** the autocomplete menu is open, **When** the operator selects `/run` and types a short prompt after it, **Then** a session row is inserted, a forum topic is created, and progress messages start streaming — same end-state as a 003 Jira-key trigger.
3. **Given** the bot has an existing chat with the operator, **When** the operator types `/` in that 1:1 chat, **Then** the same three commands appear (the menu is not gated to the configured group).

---

### User Story 2 - Stop a session via /done (Priority: P1)

While a session is running, the operator opens the bound topic, types `/done`, sends. The dispatcher recognises the bot_command entity, resolves the topic to its session, signals the worker exactly as 003's plain-text `done` does, the worker flushes a final-status line and exits, and the session lands on `canceled` / `operator_stop`.

**Why this priority**: The 003 plain-text `done` already works, but only if the operator remembers the literal word. With `/done` in the autocomplete menu, the stop control becomes discoverable without docs. Pairs naturally with `/run` — together they form the minimum viable command surface.

**Independent Test**: Trigger any session (via `/run` or via a 003 Jira-key), wait until the first progress message lands in its topic, then post `/done` inside that topic from a whitelisted account. Confirm within 10 seconds: the topic shows the operator-stop final message, the session row reads `status=canceled, error_message=operator_stop`. A non-whitelisted user posting `/done` in the same topic is silently ignored and audit-logged.

**Acceptance Scenarios**:

1. **Given** a session is running with progress streaming, **When** the whitelisted operator posts `/done` in the bound topic, **Then** within 10 seconds the worker exits gracefully and the session reaches `canceled` with `error_message=operator_stop` — identical to 003's plain-text `done`.
2. **Given** a session is running, **When** a non-whitelisted user posts `/done`, **Then** the command is silently ignored and an audit entry records the rejection.
3. **Given** a session is running and the bot's `/done` autocomplete is shown alongside the plain-text `done` synonym, **When** either form is sent, **Then** the daemon honours both equivalently — slash-command surface does not deprecate the plain-text path.

---

### User Story 3 - Inspect active sessions via /status (Priority: P2)

The operator wants to see which sessions are currently running on their PC without opening a terminal or the database. They send `/status` either (a) in the main chat — receives a summary of all active sessions, or (b) inside a topic — receives the state of that topic's session.

**Why this priority**: P2 because triggers + stops (US1, US2) are the loop the operator most often runs. Status is a "where do I stand" check that is genuinely useful but secondary. Keeping it in scope here is cheap because the dispatcher branch and command-rejection paths are already required for US1/US2.

**Independent Test**: With one running session and one terminal session in the database, post `/status` in the main chat and verify a reply listing only the active session with its issue key (or synthetic session id), iteration progress, and bound topic link. Then post `/status` inside that active session's topic and verify a reply with that single session's detailed state.

**Acceptance Scenarios**:

1. **Given** N sessions are currently in a non-terminal state, **When** the operator posts `/status` in the main chat, **Then** the bot replies in the main chat with a one-line-per-session summary (issue key, current iteration / phase, age).
2. **Given** the operator posts `/status` in a session-bound topic, **When** the dispatcher resolves the topic, **Then** the bot replies in that topic with the session's detailed state (status, current iteration, started_at).
3. **Given** no session is running, **When** the operator posts `/status` in the main chat, **Then** the reply confirms zero active sessions in plain language.

---

### User Story 4 - Free-text args for `/run` map to a default project (Priority: P2)

The operator types `/run fix the cache layer please` — no Jira-key shape, just a description. The dispatcher recognises that the args do not match the issue-key regex and falls back to a configured **default project** (`agent.default_project_jira_key` in `config.toml`). The daemon synthesises a topic name from a short timestamp + first words of the args, opens a topic, and runs the same worker pipeline as 003 against the default project's repo. The free-text args themselves are recorded in the session row for audit / future LLM use.

**Why this priority**: This is the "self-driving" use case — the operator has zero Jira project context but still wants to kick off work. P2 because operators who already use Jira can use the explicit `/run ZXTL-1234` form (which threads through the existing 003 routing) and aren't blocked by US4. P2 also because it requires a new config field and a topic-naming policy.

**Independent Test**: With `agent.default_project_jira_key=ZXTL` set and the `ZXTL` project registered, post `/run fix the cache layer` from a whitelisted account. Confirm: a new topic is created with a deterministic synthetic name (e.g. `run-2026-05-02-14-fix-the-cache`), a session row is inserted with the default project's repo as `worktree_path` source and the free-text args stored verbatim, and the worker runs to completion.

**Acceptance Scenarios**:

1. **Given** `agent.default_project_jira_key` is configured and that project is registered, **When** an operator posts `/run <free text>` (where `<free text>` does not start with a Jira key), **Then** a session is created against the default project with a synthesised topic name and the free-text args stored.
2. **Given** an operator posts `/run ZXTL-1234 also please add tests`, **When** the args begin with a Jira-key shape, **Then** the leading key is used for routing exactly as the 003 plain-text trigger does, and the rest of the text is stored as the session's free-text args.
3. **Given** `agent.default_project_jira_key` is **not** configured, **When** an operator posts `/run` with non-Jira-key args, **Then** the bot replies in the chat the command came from with a clear message ("set agent.default_project_jira_key in config.toml or use /run <PREFIX>-<NUM>") and no session is created.

---

### Edge Cases

- **Slash-command sent before the daemon ever called setMyCommands**: The Bot API still receives the message (Telegram doesn't pre-validate command names against the registered list), so the dispatcher must handle the entity regardless of whether the autocomplete menu is in sync. setMyCommands is best-effort and idempotent; failure to register does not block command processing.
- **Operator sends an unregistered slash command** (e.g. `/cancel`): The dispatcher silently ignores it (no Telegram reply, no audit noise) — the same posture as a casual non-trigger plain-text message.
- **Slash command sent in main chat that requires a topic context** (`/done`, `/status` topic-detail form): For `/done`, the daemon silently ignores it — same scoping rule as 003's plain-text `done` — and writes an audit-only `slash_command_rejected` entry with `reason=main_chat_done`. For `/status` the main-chat form lists *all* active sessions (capped at 10 lines, most-recent-first), so it is well-defined.
- **Slash command arrives with a `@bot_username` suffix in a group** (Telegram's group-disambiguation form, e.g. `/run@curious_claude_notification_bot foo`): The dispatcher strips the `@<botname>` segment when normalising the command — works the same as bare `/run`.
- **`/run` with no args at all**: The bot replies once in-chat with a usage hint ("/run <prefix>-<num>" or "/run <free text>") and creates no session.
- **`setMyCommands` API call fails at daemon startup** (network blip, Telegram outage): The daemon logs a warning, sets a `commands_registered=false` flag in `listener.state`, retries on each subsequent listener restart. Command processing on inbound messages continues to work — the only user-visible effect is that the autocomplete menu may be stale until the next successful registration.
- **Privacy Mode (BotFather setting) is back ON for the bot**: With Privacy Mode on, the bot still receives slash commands directed at it, so `/run`, `/done`, `/status` continue to function. The 003 plain-text Jira-key triggers, however, become invisible to the bot — the slash-command surface is then the only way to drive sessions. This is documented in quickstart but otherwise allowed.
- **Operator types `/run` from a 1:1 chat with the bot** (not the configured group): The trigger is rejected (003's `group_chat_id` filter still applies). Audit entry records the rejection so the operator can see why nothing happened. A future feature may broaden this; out of scope here.

## Requirements *(mandatory)*

### Functional Requirements

#### Slash command registration

- **FR-001**: On daemon startup (after the trigger pipeline is healthy), the system MUST call the Bot API `setMyCommands` method with the curated set `{run, done, status}` and short human-readable descriptions, using the bot token already configured for the listener.
- **FR-002**: `setMyCommands` registration MUST be best-effort: a failure (network error, Telegram 5xx) MUST log a warning and MUST NOT block listener startup. The daemon MUST retry registration on the next listener restart.
- **FR-003**: The system MUST expose the registration outcome (`commands_registered: true|false`, `registered_at: <ts>`) in the persisted `listener.state` so `remotask telegram status` can surface it.

#### Command parsing and routing

- **FR-004**: The dispatcher MUST recognise inbound text messages whose `entities` array contains a `bot_command` entity at offset 0. When that holds, the message is treated as a slash-command invocation, regardless of the rest of the text.
- **FR-005**: The system MUST normalise commands by stripping a trailing `@<botname>` (e.g. `/run@curious_claude_notification_bot` → `/run`), case-folding the command name to lowercase, and splitting the remaining text into the args portion.
- **FR-006**: For each curated command, the dispatcher MUST route to a dedicated handler:
  - `/run <args>` → start a new session (per FR-008..FR-011)
  - `/done` → graceful operator stop on the topic-bound session (same downstream behaviour as 003 plain-text `done`)
  - `/status` → session-state report (per FR-012..FR-013)
- **FR-007**: Unrecognised slash commands (anything not in the curated set) MUST be silently ignored — no Telegram reply, no audit row beyond the standard inbound-message DEBUG log.

#### `/run` semantics

- **FR-008**: When `/run` is followed by a token matching the issue-key regex (`PREFIX-NNN`), the system MUST route the session through the existing 003 trigger pipeline using that prefix → repo mapping. The remainder of the args (if any) MUST be persisted as free-text on the session row.
- **FR-009**: When `/run` is followed by free-text NOT matching the issue-key regex, the system MUST resolve the project mapping via a new optional config field `agent.default_project_jira_key`. If that field is unset or names an unregistered project, the system MUST reply once in the chat the command came from with a clear setup hint and create no session.
- **FR-010**: When `/run` is followed by no args at all, the system MUST reply once in-chat with a usage hint and create no session.
- **FR-011**: For accepted `/run` invocations without a Jira-key prefix in args, the system MUST synthesise a topic name of the form `run-<YYYY-MM-DD-HH-MM>-<slug>-<6 hex chars>` (slug = first ≤20 chars of args, lowercased, alnum + dash). The 6-char random hex suffix prevents collisions when two `/run` invocations share the same minute and slug. The synthetic name MUST also be stored as the session's `issue_key` so existing 003 / 002 columns continue to make sense.

#### `/done` and `/status` semantics

- **FR-012**: `/done` MUST behave identically to 003's plain-text `done` — same whitelist gate, same topic-only scoping, same SIGUSR1 / grace / SIGTERM ladder, same terminal status (`canceled` / `operator_stop` or `operator_stop_forced`).
- **FR-013**: `/status` posted in the main chat MUST reply with a one-line-per-session summary (issue key or synthetic id, current status, current iteration if known, age), most-recent-first, capped at **10 lines** with a trailing "+ N more" hint when truncated. `/status` posted inside a session-bound topic MUST reply with that single session's detailed state in that same topic. If no sessions are active, the main-chat form MUST reply with "no active sessions" in plain language.

#### Backwards compatibility

- **FR-014**: The 003 plain-text Jira-key trigger and the plain-text termination synonyms (`done`, `stop`, `finish`) MUST continue to work exactly as before — slash commands are additive, never replace.
- **FR-015**: When both a slash command and a Jira-key match could parse from the same message (e.g. `/run` is followed by `ZXTL-1234`), the slash-command branch MUST run; the Jira-key form is reachable only by a bare-text message without a leading `bot_command` entity.

#### Audit

- **FR-016**: Each accepted slash-command invocation MUST insert a `session_events` row of a new event type tied to the affected session, capturing the command name and (truncated) args.
- **FR-017**: Each rejected slash-command invocation (unauthorised sender, missing default project for `/run`, no active session for `/done` / `/status` topic-detail) MUST be recorded in the audit log with a clear `reason` discriminator.
- **FR-018**: The setMyCommands registration outcome MUST be recorded in the audit log on each attempt (success or failure) so operators can debug autocomplete drift.

### Key Entities *(include if feature involves data)*

- **CommandRegistration**: A daemon-side record of `(command_name, description)` pairs sent to setMyCommands. Lives in code (single source of truth) and in `listener.state` (last successful registration timestamp). Not a DB row.
- **SlashCommandInvocation**: An in-memory parsed record produced when a `bot_command` entity is detected. Carries `command_name`, `args_text`, `sender_id`, `chat_id`, `message_thread_id` (nullable), `message_id`. Not persisted as an entity, but its acceptance/rejection feeds session_events / audit.log.
- **Session** (extension of existing entity): When created via `/run` with non-Jira-key args, `issue_key` is the synthetic topic name (still unique within the active set). A new optional column-equivalent value via `error_message` (or, if needed, a future `args_text` column) carries the operator's free-text request — for the V0001 schema, free-text args land on `trigger_text`, which already exists.
- **AuditEvent** (extension): Adds `slash_command_received`, `slash_command_rejected`, and `commands_registered` (or `commands_registration_failed`) event types.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From the moment an operator types `/` in the configured group, the autocomplete menu shows the three commands within 1 second on a typical home network. (Telegram-client local; this is essentially "the registration was already done before the operator opened the chat".)
- **SC-002**: An operator who has never read the project documentation can start a session by typing `/`, picking `/run`, and typing a short request — without consulting external docs. Verified by a one-pass usability check.
- **SC-003**: 100% of curated slash-command invocations from a whitelisted sender produce one of: a session created (for accepted `/run`), a graceful stop (for accepted `/done`), or a status reply (for accepted `/status`). No silent drops.
- **SC-004**: 100% of slash-command invocations from non-whitelisted senders produce zero visible Telegram response and 100% audit-log coverage (parity with 003's whitelist gate).
- **SC-005**: Backwards compatibility test: every existing 003 integration test (Jira-key trigger, plain-text `done` / `stop` / `finish`, rejection paths, daemon-restart recovery) passes unchanged after this feature lands.
- **SC-006**: A daemon that fails its initial setMyCommands call (simulated with a 5xx response) MUST still process all subsequent inbound slash commands correctly. Verified by an integration test with a fake Telegram that returns 503 on `setMyCommands` once.

## Assumptions

- The existing per-user-bot model from 002/003 stays in place: each operator runs their own daemon with their own bot token from BotFather. No central server, no shared bot, no multi-tenant routing. setMyCommands is called per-operator using their own token.
- BotFather's recommended description text (≤ 256 chars per command, plain text, English by default) is the intended target. A future feature may add per-user description override; out of scope here.
- The curated command set is fixed in code: `/run`, `/done`, `/status`. Adding a new command requires a code change + redeploy + daemon restart. Per-user customisation is explicitly excluded.
- `agent.default_project_jira_key` is a single optional string (e.g. `"ZXTL"`). Multi-default-project routing is out of scope.
- Synthetic topic names for `/run` without a Jira-key prefix follow the format `run-<YYYY-MM-DD-HH-MM>-<slug>` where slug is the args' first ~20 chars normalised (lowercase, dashes for whitespace, alnum + dash only). Telegram's forum topic name limit (128 chars) is honoured by truncation.
- `/status`'s main-chat reply truncates at a configurable max (default 10 lines) so a runaway active set doesn't spam the chat. Out-of-scope: pagination.
- LLM-driven free-text intent parsing for `/run` args (e.g. "what does this code do?") is out of scope; args are stored verbatim and the worker still runs the placeholder workload from 003 until a real-agent feature replaces the worker.
- The daemon retains its 003 listener state-file shape; `commands_registered` and `registered_at` are added as new fields with safe defaults.
- Privacy Mode handling: **OFF is the recommended steady state** (cooperative — both surfaces co-exist). With Privacy Mode ON, slash commands still work but plain-text Jira-key triggers do not; the slash-command surface becomes the only operable path. Quickstart documents OFF as the recommended default; ON is explicitly allowed for operators who prefer slash-only UX.
- setMyCommands scope: registration uses **default scope (all chats)** so the autocomplete menu is visible in 1:1 DMs with the bot AND in the configured group, mirroring BotFather's UX. The 003 `group_chat_id` gate continues to reject non-group invocations at dispatch time — broader menu visibility is purely discovery convenience and does not widen the trigger surface.
- This feature does not introduce a new database migration. The V0001 schema (used by 002 and 003) continues to be sufficient.
- Existing `remotask telegram status` output gets a new line ("commands registered: yes/no, last attempt: <ts>") — non-breaking addition.
