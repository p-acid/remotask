# Feature Specification: Remove Deprecated Termination Aliases

**Feature Branch**: `006-remove-termination-aliases`
**Created**: 2026-05-02
**Status**: Draft
**Input**: User description: "005가 한 릴리스 동안 deprecated alias로 유지한 4개 종료 별칭(`/done` 슬래시 + 토픽 안 평문 `done`/`stop`/`finish`)을 완전히 제거한다 …"

## Background

In feature 005, the operator-initiated termination command was renamed from `/done` to `/cancel`. To avoid breaking
existing operator muscle memory mid-release, 005 kept four legacy tokens working as **deprecated aliases** for one
release window:

- `/done` (slash command)
- Plain-text `done`, `stop`, `finish` (topic-scoped 003 termination grammar)

When any of these were used, the dispatcher executed the same termination ladder as `/cancel` *and* posted a one-time
warning per `(alias_token, session_id)` directing the operator to `/cancel`. 005 explicitly committed to removing the
aliases in the next release; this feature is that removal.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator uses `/cancel` as sole termination command (Priority: P1)

The operator wants to stop a running session and the only command they can use is `/cancel`. After this feature ships,
typing the legacy `/done` slash command no longer cancels the session — it returns an "unknown command" rejection just
like any other non-curated slash command.

**Why this priority**: This is the contract change the feature exists to deliver. Without it, the cleanup is purely
internal and the deprecation timebox promised in 005 has not been honored.

**Independent Test**: An operator triggers a session, types `/done` in the session's topic, observes that the session
is **not** canceled and that the bot rejects the command. The operator then types `/cancel` and observes the session
canceling normally.

**Acceptance Scenarios**:

1. **Given** a running session, **When** the operator sends `/done` in its topic, **Then** the session keeps running,
   the dispatcher emits a `slash_command_rejected reason=unknown_command` audit event, and no termination ladder
   starts.
2. **Given** a running session, **When** the operator sends `/cancel` in its topic, **Then** the session terminates
   exactly as in 005 (graceful → forced ladder, `Session canceled` template, `[<issue_key>]` prefix on outbound
   messages).

---

### User Story 2 - Plain-text `done`/`stop`/`finish` are non-control text (Priority: P2)

When the operator types a bare `done`, `stop`, or `finish` in a session topic, the dispatcher treats it as ordinary
chat — no termination is initiated, no warning is posted, and no audit event is written. Casual conversation in topics
no longer accidentally triggers any control-plane behavior.

**Why this priority**: Removing the plain-text 003 termination grammar is the riskier half of the cleanup because the
dispatcher previously had a topic-scoped fast path for these tokens. Verifying the path is gone protects against silent
regressions where typed text accidentally cancels a session.

**Independent Test**: With a running session, the operator posts the literal text `done` (and again, `stop`, then
`finish`) inside the topic. The session keeps running. No new audit events are written for those messages.

**Acceptance Scenarios**:

1. **Given** a running session, **When** the operator posts plain `done` in its topic, **Then** the session is
   unaffected and no `alias_deprecation_used` or termination event is written.
2. **Given** a running session, **When** the operator posts `stop` or `finish` in its topic, **Then** the session is
   unaffected and the dispatcher writes no new audit events for those messages.

---

### User Story 3 - No alias-deprecation warnings reach the operator (Priority: P3)

The operator never again sees a "deprecated alias — use /cancel instead" message, because the warning code path no
longer exists. The cognitive overhead of the deprecation period is gone.

**Why this priority**: Surface-level cleanup. Lower priority because P1+P2 already imply the warning machinery cannot
fire, but pinning it as its own scenario gives us an explicit verification point for the absence of these messages.

**Independent Test**: Across a session that includes `/cancel` from main chat (which in 005 would *not* warn) and one
that includes a now-removed alias attempt, the operator's view contains zero deprecation warning bodies.

**Acceptance Scenarios**:

1. **Given** a session, **When** any combination of `/cancel`, `/done`, `done`, `stop`, `finish` is typed by the
   operator, **Then** no message body containing "deprecated" reaches the topic or main chat.

---

### Edge Cases

- **`/done` typed in main chat (not a topic)**: Same outcome as in a topic — dispatcher rejects as `unknown_command`.
  005's `main_chat_done` audit reason is no longer emitted because the entire alias path is gone.
- **`/done@<bot_username>` form**: Same rejection path — Telegram strips the `@<bot_username>` suffix during command
  parsing; the dispatcher then sees the bare `done` command name and rejects it.
- **Plain `done` posted in main chat (not a topic)**: Already non-control in 005 (003 termination grammar was
  topic-scoped). Behavior unchanged.
- **In-flight session that was started before the deploy**: No effect. The runtime state for live sessions is the
  same shape; the alias-warning bookkeeping just stops being read or written. Existing `/cancel` paths continue to
  work.
- **Audit log readers that consumed `alias_deprecation_used` events**: No such consumers exist in the project; no
  external systems are affected. The constant `EV_ALIAS_DEPRECATION_USED` is removed cleanly.
- **`REASON_MAIN_CHAT_DONE` references in old audit files**: Historical audit log entries on disk still contain the
  string; this is expected — log files are append-only and we do not rewrite them. The constant is removed from code
  but the literal value remains valid in older log lines.

## Requirements *(mandatory)*

### Functional Requirements — Operator-visible behavior

- **FR-001**: The system MUST reject `/done` (and `/done@<bot_username>`) with `slash_command_rejected
  reason=unknown_command`, identical to any other non-curated slash command. The session, if any, MUST keep running.
- **FR-002**: The system MUST treat plain-text `done`, `stop`, and `finish` in topics as ordinary chat. No termination
  ladder MUST start, no warning MUST be posted, and no audit event MUST be written specifically because of the token.
- **FR-003**: The system MUST preserve `/cancel` as the canonical, sole operator-initiated termination slash command,
  with the exact 005 semantics (graceful SIGUSR1 → grace window → forced SIGTERM/SIGKILL ladder, "Session canceled by
  operator." / "Session force-canceled by operator (grace window exceeded)." templates).
- **FR-004**: The system MUST preserve the `[<issue_key>]` prefix on every session-bound outbound message exactly as
  005 introduced it.
- **FR-005**: The system MUST preserve the `REASON_MAIN_CHAT_CANCEL` audit reason emitted when `/cancel` is issued
  outside a topic.
- **FR-006**: The system MUST NOT emit any "deprecated alias" warning message to any chat for any token.
- **FR-007**: The system MUST NOT write any `alias_deprecation_used` audit event going forward.

### Functional Requirements — Internal cleanup

- **FR-008**: The dispatcher's slash-command branch handling `name == "done"` MUST be removed.
- **FR-009**: The dispatcher's `_emit_alias_warning` helper MUST be removed.
- **FR-010**: The dispatcher's plain-text 003 termination dispatch path (any code that consults a "termination
  command" parser for non-slash messages) MUST be removed.
- **FR-011**: The runtime's in-memory `_alias_deprecation_warned` set and its three accessor methods
  (`has_alias_deprecation_warned`, `record_alias_deprecation_warned`, `clear_alias_deprecation_for_session`) MUST be
  removed.
- **FR-012**: The parser's `match_termination_command` function MUST be removed.
- **FR-013**: The audit module constants `EV_ALIAS_DEPRECATION_USED` and `REASON_MAIN_CHAT_DONE` MUST be removed.
- **FR-014**: The worker's `on_terminal` callback parameter (added in 005 solely to clean up the alias-warned set on
  terminal session transitions) MUST be removed, along with the dispatcher wiring that supplied it.
- **FR-015**: The `DispatchContext` MUST no longer carry the three alias-deprecation callback fields
  (`has_alias_deprecation_warned`, `record_alias_deprecation_warned`, `clear_alias_deprecation_for_session`).

### Functional Requirements — Test surface

- **FR-016**: Tests dedicated solely to deprecated-alias behavior MUST be deleted:
  - `tests/integration/test_alias_deprecation.py`
  - `tests/integration/test_slash_done.py`
  - `tests/unit/test_runtime_alias_warned.py`
- **FR-017**: Test classes targeting removed grammar MUST be deleted:
  - `TestMatchTerminationCommand` in `tests/unit/test_telegram_parser.py`
  - `TestAliasDeprecation` (and any analogous deprecation-only class) in `tests/unit/test_dispatcher.py`
- **FR-018**: Existing 003 plain-text-termination integration tests
  (`tests/integration/test_operator_stop.py`, `tests/integration/test_operator_stop_forced.py`) MUST be migrated to
  trigger termination via the `/cancel` slash command instead of plain text. Their non-trigger expectations (graceful
  ladder, forced ladder, error-message templates, `[KEY]` prefix) MUST remain unchanged.
- **FR-019**: A regression test MUST exist asserting that **`/done` slash → unknown_command rejection** for both
  in-topic and main-chat contexts.
- **FR-020**: A regression test MUST exist asserting that **plain-text `done`, `stop`, `finish`** posted in a topic
  during a running session do NOT trigger any termination, warning, or audit event tied to those tokens.

### Out of Scope

- Database schema changes. V0001 is unchanged.
- Constitution amendments. v1.1.0 stands.
- `setMyCommands` curated set changes. Already `{run, cancel, status}` since 005.
- Rewriting historical audit log lines containing `alias_deprecation_used` or `main_chat_done`. Append-only logs are
  immutable.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After this feature ships, a `grep` across `src/` for `match_termination_command`,
  `_alias_deprecation_warned`, `EV_ALIAS_DEPRECATION_USED`, `REASON_MAIN_CHAT_DONE`, `_emit_alias_warning`, and any
  `on_terminal=` worker keyword argument returns zero hits in production source.
- **SC-002**: Operator typing `/done` in any chat receives the unknown-command rejection in under 1 second
  (matching 004 baseline reject latency).
- **SC-003**: Operator typing plain `done`, `stop`, or `finish` in a topic during a running session sees zero new
  outbound messages from the bot and zero new database session events tied to that input.
- **SC-004**: All 005-introduced behaviors continue to pass their existing tests: `/cancel` canonical (in-topic and
  main-chat), `[<issue_key>]` prefix, `REASON_MAIN_CHAT_CANCEL` audit reason. Zero regression-test breakages.
- **SC-005**: The full test suite passes with the deletions and migrations applied. The actual net delta is **−34
  tests** (308 baseline → 274; FR-016/017 file/class deletions plus the additional plain-text-grammar dependents
  identified during implementation, minus 8 new regression tests across FR-019 and FR-020). All `/cancel`
  canonical, `[<issue_key>]` prefix, and `REASON_MAIN_CHAT_CANCEL` coverage from 005 is preserved.

## Assumptions

- The 005 release has been deployed long enough that operators have already adopted `/cancel`. The deprecation warning
  during 005 was the migration vehicle; this feature is the deprecation deadline.
- No external system consumes the `alias_deprecation_used` audit event type. Internal-only audit log readers are the
  only consumers and they tolerate the disappearance of an event type.
- `setMyCommands` was already updated to `{run, cancel, status}` in 005, so this feature does not need to touch
  Telegram-side command registration.
- Operators will have their Telegram client cache the curated command list from the 005 release. After this deploy,
  using `/done` will surface either as "unknown command" (if the client lets the bare command through) or as a
  Telegram-side autocomplete miss (the menu won't suggest it). Both paths are acceptable.
- 003's plain-text termination grammar was the *only* consumer of `match_termination_command`. Removing the function
  is safe.
- The worker's `on_terminal` hook was added in 005 specifically for alias-set cleanup. No other call site uses it.
- The `DispatchContext` shape change (removing three callback fields) is internal — no external module constructs
  `DispatchContext` outside the runtime.
