# Feature Specification: `/cancel` Rename + `[KEY]` Prefix + Alias Deprecation

**Feature Branch**: `005-dm-channel` (folder name retained from initial draft; scope was narrowed — see Scope decision)
**Created**: 2026-05-02
**Status**: Draft (rev 2 — narrowed scope)
**Input**: User description: "Switch the operator's interaction channel from a forum group with per-session topics to a single 1:1 DM with the bot…"

## Scope decision (rev 2)

The initial draft proposed switching from the 003/004 forum-group + per-session-topic model to a single 1:1 DM. After review, the operator chose to **keep forum topics** for visual session separation — when `max_concurrent ≥ 2`, separate topics make multi-session output materially easier to follow than `[KEY]` prefix + reply chain in a single DM. The DM transition is therefore dropped from this feature.

What 005 actually delivers:

1. **`/cancel` rename**: `/done` was the wrong name (semantically "done" implies natural completion, not operator-initiated stop). `/cancel` becomes the canonical command.
2. **`[KEY]` prefix on every session-bound progress / final / canceled message**: redundant inside a topic (the topic already names the session) but valuable when an operator scrolls a multi-topic group, and forward-compatible if a future feature ever re-introduces a single-channel surface.
3. **Alias deprecation window**: `/done`, plain-text `done` / `stop` / `finish` keep working for one release with a `WARNING` log per first use per session lifetime; feature 006 removes them.
4. **`setMyCommands` payload becomes `{run, cancel, status}`** (drop `done`).

What 005 does **not** deliver:

- Channel transition to 1:1 DM
- `dm_chat_id` config rename
- `getChat` chat-type detection
- Migration notice for misconfigured chats
- `reply_to_message_id` threading (topic separation already provides visual separation; threading inside a topic is mostly redundant and adds plumbing for marginal gain — out of scope)

The 003/004 channel model (`telegram.group_chat_id` + `is_forum=true` supergroup + `createForumTopic` per session) is **preserved unchanged**.

## Clarifications

### Session 2026-05-02

- Q: Plain-text Jira-key trigger still works in main chat? → A: **Yes, unchanged** (002 muscle memory preserved; Privacy Mode still required OFF for plain-text triggers in groups, same as 003/004).
- Q: Lifetime of deprecated aliases (`/done`, plain-text `done`/`stop`/`finish`)? → A: **Removed in feature 006 (next release after 005)**. 005 emits a structured-log `WARNING` per first use per session lifetime.
- Q: `[KEY]` prefix applies to which messages? → A: **Every progress / `Status:` / final / canceled message** (the ones that don't already name the issue key in their body). The `Session starting for ZXTL-1234. Worktree: …` template is NOT prefixed because it already names the key (would produce stutter `[ZXTL-1234] Session starting for ZXTL-1234.`).
- Q: Does the autocomplete menu show `/done` for the deprecation window? → A: **No**. `setMyCommands` advertises only `{run, cancel, status}`. Inbound `/done` still routes (with a deprecation WARNING) but it's not promoted in the menu — the migration signal is "type `/`, see `cancel` instead of `done`".

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Stop a session with `/cancel` (Priority: P1)

A session is running in its forum topic. The operator wants to stop it. Inside the topic they type `/cancel` (or, equivalently, `/done` for now) and within seconds the worker receives a stop signal, flushes a final status, and the topic shows `[ZXTL-1234] Session canceled by operator.`. The session row lands on `canceled` with `error_message=operator_stop`.

**Why this priority**: This is the entire point of 005. The naming of the operator-stop command was the most visible defect in 003/004 — `/done` semantically implies natural completion, leading to operator confusion. Renaming to `/cancel` is the smallest possible fix that resolves the confusion without churning anything else.

**Independent Test**: Trigger a session, wait for the first progress line, then post `/cancel` inside the topic. Confirm: (a) within 10 seconds the session reaches `canceled` / `operator_stop`, (b) the topic shows the operator-stop final message and the "canceled by operator" message, (c) `setMyCommands` payload contains `cancel` and not `done`.

**Acceptance Scenarios**:

1. **Given** a session is running in its topic, **When** the operator posts `/cancel` inside the topic, **Then** the worker receives a stop signal and the session terminates within 10 seconds with `status=canceled, error_message=operator_stop`.
2. **Given** the daemon has registered slash commands at startup, **When** an operator types `/` in any chat with the bot, **Then** the autocomplete menu shows exactly `/run`, `/cancel`, `/status` — `/done` is NOT shown.
3. **Given** a session is running, **When** the operator posts `/cancel` from the main chat (not inside a topic), **Then** the command is silently ignored and `audit.log` records `slash_command_rejected reason=main_chat_cancel`.

---

### User Story 2 - Backwards-compatible aliases (Priority: P1)

For one release after 005 (i.e. through to feature 006), the existing `/done` slash command and the plain-text `done`, `stop`, `finish` synonyms continue to be honoured exactly like `/cancel`. Operators with 003/004 muscle memory are not broken on day one. Each first-use-per-session of an alias logs a structured `WARNING` so operators see the migration signal in their own logs without waiting for documentation.

**Why this priority**: Same priority as US1 — these together form the migration story. Without aliases, `/done` becomes a silent no-op the day 005 ships, which would be a regression.

**Independent Test**: Trigger a session, post `/done` (slash) → confirm cancellation works. Trigger another, post plain-text `stop` → confirm cancellation works. Inspect `~/.local/share/remotask/logs/daemon.log` for `WARNING alias deprecation` lines.

**Acceptance Scenarios**:

1. **Given** a session is running, **When** the operator posts `/done` inside the topic, **Then** the session is canceled identically to `/cancel`, AND a structured-log `WARNING` line records `alias=/done canonical=cancel session_id=…`.
2. **Given** a session is running, **When** the operator posts plain-text `stop` inside the topic, **Then** the session is canceled identically, AND a `WARNING` line records `alias=stop canonical=cancel session_id=…`.
3. **Given** the operator posts `/done` twice on the same session, **When** the second `/done` arrives, **Then** the second one is a no-op (worker already exited) and no second `WARNING` is logged for that (alias, session) pair.

---

### User Story 3 - `[KEY]` prefix on every session-bound message (Priority: P2)

Every progress, status, and final-state message the worker posts to its topic carries a `[<issue_key>]` prefix. Inside one topic this is somewhat redundant, but it makes scrolling the parent group's "All Topics" view much easier — the operator can scan for messages from a specific issue without entering each topic. It also future-proofs against a single-channel presentation surface (web UI, possible future DM mode) where the prefix is the only visual attribution available.

**Why this priority**: P2 because it's a quality-of-life improvement, not a correctness fix. Multi-session operators benefit immediately; single-session operators see one extra `[KEY]` per line and don't notice.

**Independent Test**: Trigger one session and read its topic. Every line that doesn't already name the issue key (e.g. `Session starting for ZXTL-1234.`) should begin with `[ZXTL-1234]`. Trigger two concurrent sessions; scan the parent group's notification list and confirm each notification's preview begins with the right `[KEY]`.

**Acceptance Scenarios**:

1. **Given** a session is running, **When** the worker emits a `Status: iteration N/M` line, **Then** the message posted to the topic reads `[ZXTL-1234] Status: iteration N/M @ <ts>`.
2. **Given** the worker emits the final-status line, **When** the message is posted, **Then** it reads `[ZXTL-1234] Status: final iteration N (operator_stop)` (and similarly for `natural` / `timeout`).
3. **Given** the worker posts the `Session starting for ZXTL-1234. Worktree: …` template, **When** the message is composed, **Then** it is NOT prefixed (would produce stutter; the body already names the key).

---

### User Story 4 - `/run` and `/status` semantics unchanged (Priority: P3)

`/run`, `/status`, the plain-text Jira-key trigger, the topic-detail / main-chat split for `/status`, the synthetic-id format from 004, the curated-command idempotency, and every other 002/003/004 feature continue to work exactly as they did. 005 changes only the operator-stop command name and the prefix behaviour; nothing else.

**Why this priority**: P3 because the requirement is "do nothing here". This story is here so the spec explicitly nails down the no-change surface and so SC-006 has something to point at.

**Independent Test**: Run 002, 003, and 004 quickstarts unchanged (substituting `/cancel` for `/done` where applicable). All should pass.

**Acceptance Scenarios**:

1. **Given** an authorized operator and a registered project, **When** they post `/run ZXTL-1234` in the main chat, **Then** the same forum topic creation + worker spawn flow as 003/004 happens, with progress messages now `[KEY]`-prefixed (delta from US3).
2. **Given** they post `/status` in the main chat, **Then** the same active-sessions list as 004 is returned.
3. **Given** they post plain-text `ZXTL-1234` in the main chat (Privacy Mode OFF), **Then** the same trigger-handler runs as 002.

---

### Edge Cases

- **`/cancel` from main chat (no topic context)**: rejected with `reason=main_chat_cancel`, identical to 004's `main_chat_done`. The operator-stop command requires a topic context so the dispatcher can resolve which session to cancel.
- **`/cancel` arrives when the topic's session has already finished**: silent ignore + audit `reason=no_active_session`, identical to 004.
- **`/cancel` from a non-whitelisted user inside a topic**: silent ignore + audit `reason=unauthorized`.
- **`/done` (deprecated) used twice on the same session**: first use cancels the session and logs WARNING; second use is a no-op (worker already gone) — no new WARNING for the same (alias, session) pair (R2 idempotency).
- **Plain-text `done` posted in main chat**: silently ignored (003 behaviour preserved — plain-text aliases require a topic context).
- **Plain-text `stop` posted from a non-whitelisted user inside a topic**: silently ignored, identical to 003's whitelist gate.
- **`setMyCommands` registration fails on startup**: dispatcher continues; inbound `/cancel` and `/done` are still parsed and routed via the bot_command entity in the message — only the autocomplete menu is missing or stale (004 behaviour preserved).
- **Two consecutive `/cancel` lines in the same topic**: the first one signals the worker; the second one finds no active session and audit-rejects with `reason=no_active_session`.
- **Multi-line `/cancel` like `/cancel\nfoo`**: dispatcher matches only the slash-command entity at offset 0 (004 behaviour); subsequent lines ignored.
- **`/cancel <ZXTL-1234>` with explicit key inside a topic**: the topic context is the authoritative session resolver. The explicit key is **not parsed in 005** — this is a surface-area decision: 005 does not introduce explicit-key cancel grammar (out of scope; the topic already disambiguates). Future feature 006 / 007 may add explicit-key form when the channel model evolves.

## Requirements *(mandatory)*

### Functional Requirements

#### Command rename (canonical `/cancel`)

- **FR-001**: `/cancel` MUST become the canonical operator-stop slash command. It MUST behave functionally identically to 003/004's `/done` once a target session has been resolved (SIGUSR1 → grace → SIGTERM ladder, terminal status `canceled` / `operator_stop` or `operator_stop_forced`).
- **FR-002**: `/cancel` MUST resolve the target session via the inbound message's `message_thread_id` (the topic context), identical to how 004's `/done` resolved.
- **FR-003**: `/cancel` posted in the main chat (no `message_thread_id`) MUST be silently rejected with audit `reason=main_chat_cancel`. (`main_chat_done` from 004 is renamed.)

#### setMyCommands payload

- **FR-004**: The curated `setMyCommands` payload MUST be `{run, cancel, status}` — exactly three entries. `done` MUST NOT be advertised by setMyCommands.
- **FR-005**: The `cancel` command MUST be registered with the description `Cancel an active session`.

#### Backwards-compat aliases (deprecated, one release)

- **FR-006**: `/done` (slash command) MUST continue to be recognised and route to the same handler as `/cancel`. It MUST emit a deprecation `WARNING` to the structured log on first use per session lifetime.
- **FR-007**: Plain-text `done`, `stop`, `finish` (each on its own line, case-insensitive, optional leading slash, posted inside a topic) MUST continue to be recognised and route to the same handler as `/cancel`. Each first use per (alias_token, session_id) MUST emit a deprecation `WARNING`.
- **FR-008**: The deprecation `WARNING` MUST include the alias_token used, the canonical command (`cancel`), and the resolved session_id. A single (alias_token, session_id) pair MUST emit at most one WARNING per session lifetime — repeated alias use on the same session does not flood the log.

#### `[KEY]` prefix

- **FR-009**: Every outbound message the worker sends to its topic during the running phase MUST begin with `[<issue_key>] ` (with a single trailing space) — specifically: `Status: iteration N/M`, `Status: final iteration N (...)`, `Status: completed`, `Status: canceled`, `Status: failed`, `Session canceled by operator.`, `Session force-canceled by operator (grace window exceeded).`, `Session terminated: timeout ({seconds}s)`, `Session failed: <reason>`.
- **FR-010**: Templates that already name the issue_key in their body MUST NOT be prefixed (would produce visible stutter): `Session starting for ZXTL-1234. Worktree: …`, `Draft PR opened: <url>`. The exhaustive list lives in `data-model.md` "Outbound message catalogue".
- **FR-011**: The prefix MUST be applied at a single chokepoint helper (`topic.format_progress(issue_key, body)`) so reviewers can verify "did 005 forget to prefix any message?" at one location.

#### Audit and observability

- **FR-012**: A new audit event type `alias_deprecation_used` MUST be emitted to `audit.log` on every WARNING-emitting alias use. Payload: `{alias_token, canonical: "cancel", session_id, sender_id, message_id, chat_id, message_thread_id}`.
- **FR-013**: The 004 `slash_command_received` event's `command` field MUST gain the value `cancel` (alongside the existing `run`, `done`, `status`).
- **FR-014**: The 004 `slash_command_rejected` event's `reason` field MUST gain the value `main_chat_cancel` (replacing `main_chat_done` for `/cancel`-rejected cases; `main_chat_done` is retained for the deprecated `/done` alias path so the two are distinguishable in audit logs).

#### Backwards-compat invariants

- **FR-015**: 002 plain-text Jira-key trigger MUST continue to work in the main chat under Privacy Mode OFF, unchanged. 005 does not change 002's behaviour.
- **FR-016**: 003 plain-text `done`/`stop`/`finish` inside a topic MUST continue to cancel the session, with the deprecation WARNING from FR-007. 005 does not break 003's plain-text path.
- **FR-017**: 004 `/run` (Jira-key + free-text), `/status` (main-chat list + topic-detail), and synthetic-id semantics MUST continue to work unchanged.
- **FR-018**: The DB schema (V0001) MUST NOT change. No migration in this feature.
- **FR-019**: The Telegram channel model (group_chat_id + supergroup with `is_forum=true` + `createForumTopic` per session) MUST be preserved unchanged. The bot still requires `Manage Topics` permission in the configured group.

### Key Entities *(include if feature involves data)*

- **Session** (existing entity): No schema delta. The `topic_id` column continues to be populated by `createForumTopic` exactly as 003/004 did.
- **CancelInvocation**: An in-memory parsed record from a `/cancel` slash command, a `/done` slash command, or a plain-text `done`/`stop`/`finish`. Carries the resolved `session_id` (from `message_thread_id`), the originating `alias_token` (or `"cancel"` for the canonical), the sender / message / chat ids. Not persisted; its acceptance produces `slash_command_received`/`alias_deprecation_used` audit rows.
- **Curated command registry**: The `CURATED_COMMANDS` tuple in `telegram/commands.py` changes from `(run, done, status)` to `(run, cancel, status)`. Code-only data structure — no DB / config presence.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A whitelisted operator can cancel an active session by posting `/cancel` inside its topic, with the worker reaching `canceled / operator_stop` within 10 seconds on a typical home network — same budget as 003/004 graceful stop.
- **SC-002**: The autocomplete menu (`setMyCommands` registration) shows exactly three commands: `run`, `cancel`, `status`. `/done` is not visible. Verified by inspecting the registered payload in the integration tests.
- **SC-003**: Every existing 002/003/004 integration test that does not specifically assert on `/done` or the un-prefixed message body continues to pass unchanged.
- **SC-004**: A 003/004 operator who upgrades to 005 without changing usage (i.e. continues to post `/done`) sees their sessions cancel correctly and observes a deprecation `WARNING` in their daemon log within the first cancel of every session.
- **SC-005**: Multi-session operators (`max_concurrent ≥ 2`) report that the `[KEY]` prefix in the parent group's "All Topics" notification preview makes attribution faster — qualitative success criterion verified during quickstart Step 5.
- **SC-006**: Zero new database migrations land in 005. V0001 (used by 002/003/004) covers everything.

## Assumptions

- The 003/004 forum-group + per-session-topic channel model is unchanged. The bot continues to require `Manage Topics` permission in the configured group.
- The deprecation aliases (`/done`, `done`, `stop`, `finish`) live for exactly one release. **Feature 006 (the next feature after 005)** removes them and their dispatch branches.
- 005 emits a structured-log `WARNING` on the first use of any alias per (alias_token, session_id) pair to give operators a clear migration signal without flooding logs.
- `setMyCommands` from 004 is reused; the only change is the curated payload (`done` → `cancel`).
- The 003 worker stdout protocol (`PROGRESS`, `FINAL`, `PR_URL=`) is unchanged. What changes is the formatting of the messages the daemon posts in response: `[KEY]` prefix.
- Privacy Mode posture is unchanged from 004 — plain-text triggers in groups still require Privacy Mode OFF; this is a 002/003/004 inheritance, not a 005 decision.
- Constitution v1.1.0 (already amended) governs: Principle III's "channel mapping is presentation-layer" amendment is correct under the forum-topic model too — the topic mapping is an operator-facing presentation choice, and the worktree/branch isolation is the constitutional invariant. The amendment was made for 005's original DM scope but remains valid under the narrowed scope.
- The folder name `005-dm-channel` is retained because renaming would churn git history without functional benefit. The feature title in spec.md and plan.md reflects the actual narrowed scope.
