# Feature Specification: Telegram Trigger

**Feature Branch**: `002-telegram-trigger`
**Created**: 2026-05-01
**Status**: Draft
**Input**: User description: "Telegram bot trigger for remote Claude Code execution — receive Jira issue keys, spawn isolated worker sessions, stream progress to forum topics."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Trigger a session from a Jira issue key (Priority: P1)

An authorized operator is away from their desk. They open the project's Telegram group, type a Jira issue key (e.g., `ZXTL-1234`) in the main channel, and the system immediately acknowledges receipt, creates a dedicated forum topic for that issue, and begins streaming progress updates as the local agent works through the task. When the agent finishes preparing changes, the topic receives the resulting pull request URL.

**Why this priority**: This is the entire point of the feature. Without it, there is no remote trigger — the operator cannot kick off work from their phone. Every other story extends or hardens this single flow.

**Independent Test**: With a single registered project mapping (issue key prefix → repository path) and one whitelisted operator, send a message containing a valid issue key from the operator's Telegram account and confirm a forum topic is created, status updates are posted, and a final PR URL appears.

**Acceptance Scenarios**:

1. **Given** an authorized operator and a registered project for prefix `ZXTL`, **When** they post `ZXTL-1234` in the group's main channel, **Then** the system creates a forum topic named after the issue key, posts a "session starting" acknowledgement within 5 seconds, and the session's lifecycle is recorded.
2. **Given** a session has started, **When** the worker progresses through its phases (starting → running → pr_created), **Then** each transition produces a corresponding update in the forum topic so the operator can follow progress without leaving Telegram.
3. **Given** a worker successfully produces a draft pull request, **When** the session completes, **Then** the topic receives a final message containing the PR URL and a clear "completed" status.

---

### User Story 2 - Reject unknown project keys with helpful guidance (Priority: P1)

An operator types an issue key whose prefix has not been registered as a project. The system replies in the main channel (not in a new topic, since no session is started) with a clear message explaining that the project is unknown and listing the prefixes that *are* registered, so the operator can correct the typo or register the missing project.

**Why this priority**: Without this, a typo or stale prefix produces silence — the operator cannot tell whether the bot is offline, the message was rejected, or the issue truly has no mapping. Fast, informative rejection is essential for trust.

**Independent Test**: With one project registered for prefix `ZXTL`, send a message `FOO-99` from a whitelisted user and confirm the bot replies in the main channel with an error that names the unknown prefix and lists `ZXTL` (and any others).

**Acceptance Scenarios**:

1. **Given** the only registered project prefix is `ZXTL`, **When** an authorized operator posts `BAR-7`, **Then** the bot replies in-channel with text identifying the unknown prefix `BAR` and listing the available prefixes (`ZXTL`).
2. **Given** the message contains text that does not match any issue-key pattern at all (e.g., a casual chat message), **When** the message is received, **Then** the bot ignores it silently — it must not pollute the channel with errors for non-trigger messages.

---

### User Story 3 - Reject unauthorized senders silently and audit the attempt (Priority: P1)

A Telegram user who is not on the whitelist posts an issue key in the group. The bot does not respond, does not create a topic, and does not start a session — but the daemon's audit log records the attempt (sender id, message id, timestamp) so the operator can review unauthorized access later.

**Why this priority**: The bot operates inside a group chat that may include guests or future members. Without a strict whitelist, anyone added to the group could trigger expensive code-modifying sessions on the operator's machine. Silent rejection (rather than a visible error) avoids signaling to attackers what the trigger format is.

**Independent Test**: With a whitelist containing only the operator's user id, post a valid issue key from a *different* Telegram account in the same group and confirm: no topic is created, no reply is sent, no session row is added, and an audit log entry exists naming the rejecting sender's id.

**Acceptance Scenarios**:

1. **Given** a user id not present in the configured whitelist, **When** that user posts a valid issue key, **Then** no session is started, no topic is created, no message is sent in reply, and an audit log entry records the rejection with the sender id and message id.
2. **Given** the whitelist is empty (misconfigured), **When** any user posts an issue key, **Then** all messages are rejected — the bot must fail closed, never open.

---

### User Story 4 - Control the listener via CLI subcommands (Priority: P2)

The operator wants to start, stop, and inspect the Telegram listener as part of the daemon they already manage. They run `remotask telegram start`, `remotask telegram stop`, and `remotask telegram status` and receive consistent feedback comparable to the existing daemon commands.

**Why this priority**: Operators should not need a separate manual to manage this feature. CLI parity with the existing daemon control surface keeps the cognitive model small. It is P2 because the listener can also be enabled implicitly by the daemon at boot — explicit CLI control is convenience, not necessity for an MVP.

**Independent Test**: Run each subcommand against a daemon that has the listener feature configured and confirm the listener transitions between running and stopped states, and that `status` reports the current state, last-message timestamp, and active session count.

**Acceptance Scenarios**:

1. **Given** the daemon is running and the listener is stopped, **When** the operator runs `remotask telegram start`, **Then** the listener begins polling Telegram within 3 seconds and `remotask telegram status` reports it as running.
2. **Given** the listener is running, **When** the operator runs `remotask telegram stop`, **Then** in-flight worker sessions are not interrupted, but no new triggers are accepted, and `status` eventually reflects the stopped state.
3. **Given** the listener is running, **When** the operator runs `remotask telegram status`, **Then** the output includes: running/stopped state, time since last successful poll, count of currently active sessions, and the configured whitelist size.

---

### User Story 5 - Surface worker failures in the originating topic (Priority: P2)

A worker session fails partway through (subprocess crash, missing dependency, repository in a bad state, etc.). The forum topic receives a clear failure message including a short reason, and the session's recorded status reflects the failure so it can be retried or investigated.

**Why this priority**: Without this, a failed session leaves the operator waiting indefinitely with no signal — the topic just stops updating. P2 rather than P1 because the happy path (US1) provides value on its own; failure surfacing is necessary for production confidence but not for first-demo correctness.

**Independent Test**: Force a worker to fail (e.g., point its repo path at a non-existent directory) and confirm the topic receives a failure message naming the cause, the session status becomes `failed`, and an audit entry is written.

**Acceptance Scenarios**:

1. **Given** a session that has started but its worker raises an exception or exits non-zero, **When** the failure is detected, **Then** the topic receives a failure message that includes a one-line reason, and the session row is marked `failed` with a timestamp.
2. **Given** a worker silently hangs (no progress for an extended period), **When** the configured timeout elapses, **Then** the worker is terminated, the topic is notified, and the session is marked `failed` with a timeout reason.

---

### User Story 6 - Run multiple sessions concurrently in isolated topics (Priority: P3)

The operator triggers two issue keys in quick succession (e.g., `ZXTL-1234` then `ZXTL-1235`). Both sessions run at the same time, each in its own forum topic, each in its own git worktree on its own branch. Updates in one topic do not appear in the other.

**Why this priority**: Single-session-at-a-time is a viable MVP. Concurrency is a quality-of-life and throughput improvement that becomes important once the system is in regular use, but it should not block the first release.

**Independent Test**: Trigger two valid issue keys within a short window and confirm two distinct topics are created, two distinct worktrees exist on disk under different branches, and both sessions reach a terminal state without one corrupting the other's repository state.

**Acceptance Scenarios**:

1. **Given** two valid trigger messages arrive within the same minute, **When** both are accepted, **Then** two separate topics are created, two worktrees on two branches are present, and the two sessions complete (or fail) independently.
2. **Given** two messages refer to the same issue key, **When** the second arrives while the first is still running, **Then** the second is rejected with a clear in-channel message that the issue is already in flight, and only one topic exists for that issue.

---

### Edge Cases

- **Message contains multiple issue keys**: Treat the first valid registered key as the trigger; ignore the rest. Document this in the rejection message format so operators understand.
- **Issue-key pattern matches but is malformed** (e.g., `ZXTL-` with no number, or `ZXTL-abc`): Treat as a non-trigger; do not reply. Avoids noisy errors on casual conversation that happens to share a prefix.
- **Telegram outage / long-poll failure**: The listener must back off and retry without crashing the daemon. After a configured number of consecutive failures, mark the listener as degraded and surface this via `status`.
- **Forum topic creation fails** (group not configured as a forum, bot lacks permission): Reply once in the main channel with an actionable error ("bot needs forum-management permission"); do not retry indefinitely.
- **Session state machine corruption** (daemon restarts mid-session): On startup, any session left in a non-terminal state is marked `failed` with reason `daemon_restart`; the topic receives a notice. Workers are not auto-resumed in MVP.
- **Whitelist changes while sessions are running**: Removing a user from the whitelist does not cancel their in-flight sessions, but their next message will be rejected.
- **Bot token rotated**: Configuration reload must be possible without losing in-flight session state. (Reload mechanism may be out of MVP scope; see Assumptions.)
- **Network partition between bot and worker**: The session continues; updates are queued in memory and flushed when connectivity returns. If the queue exceeds a configured size, oldest progress messages are dropped (final status is always preserved).

## Requirements *(mandatory)*

### Functional Requirements

#### Listener and Authentication

- **FR-001**: System MUST poll the configured Telegram bot for new messages in the configured chat using long-poll, with automatic backoff on transient failures.
- **FR-002**: System MUST accept incoming messages only from sender ids present in the configured whitelist; all other messages MUST be rejected without reply.
- **FR-003**: System MUST fail closed when the whitelist is empty or the configuration is missing — no message may trigger a session under those conditions.
- **FR-004**: System MUST record every rejected message (unauthorized sender, unknown project, malformed input) in the daemon's audit log with sender id, message id, chat id, and reason.

#### Trigger Parsing and Routing

- **FR-005**: System MUST extract the first issue key matching the canonical pattern `[A-Z][A-Z0-9_]+-\d+` from each incoming message.
- **FR-006**: System MUST resolve the extracted issue key's prefix against the registered projects table and proceed only when a matching project exists.
- **FR-007**: System MUST reply in the main channel when a message contains a syntactically valid issue key whose prefix is unknown, naming the unknown prefix and listing all currently registered prefixes.
- **FR-008**: System MUST silently ignore messages that contain no issue-key pattern at all (no reply, no audit noise beyond standard message receipt logging).

#### Session Lifecycle

- **FR-009**: System MUST create exactly one forum topic per accepted trigger and bind that topic to a single session row throughout its lifecycle.
- **FR-010**: System MUST refuse to start a second concurrent session for the same issue key while the first is still in a non-terminal state, replying in the main channel with the existing topic reference.
- **FR-011**: System MUST persist each session through the states `enqueued → starting → running → pr_created → completed` (with `failed` and `canceled` as terminal alternatives), recording the timestamp of every transition.
- **FR-012**: System MUST post a status message to the bound topic on every session state transition.
- **FR-013**: System MUST post the final pull-request URL to the bound topic when the session reaches `pr_created`.
- **FR-014**: On daemon startup, system MUST mark any session left in a non-terminal state as `failed` with reason `daemon_restart` and post a notice to its bound topic.

#### Worker Isolation

- **FR-015**: Each session MUST execute in an isolated git worktree on a dedicated branch, so concurrent sessions cannot interfere with one another's working tree state.
- **FR-016**: System MUST detect worker process exit and translate it into a session state transition (success → `completed`/`pr_created`; non-zero exit or exception → `failed`).
- **FR-017**: System MUST enforce a per-session timeout; sessions that exceed it MUST be terminated and marked `failed` with reason `timeout`.

#### CLI Control

- **FR-018**: System MUST provide a `remotask telegram start` subcommand that signals the daemon to begin polling.
- **FR-019**: System MUST provide a `remotask telegram stop` subcommand that signals the daemon to stop accepting new triggers without interrupting in-flight sessions.
- **FR-020**: System MUST provide a `remotask telegram status` subcommand that reports listener state, time since last successful poll, active session count, and whitelist size.

#### Configuration and Security

- **FR-021**: Bot token, chat id, and whitelist MUST be stored in the existing daemon configuration file with file-mode `0600` enforced on read and write.
- **FR-022**: Bot token MUST be treated as a secret in audit logs and CLI output (never printed in cleartext).
- **FR-023**: System MUST refuse to start the listener if the configuration file's permissions are looser than `0600` and report a clear error.

### Key Entities *(include if feature involves data)*

- **TelegramConfig**: Bot token (secret), chat id, whitelist of allowed sender ids, poll interval, per-session timeout. Stored in the existing config file alongside daemon settings.
- **Session** (extension of existing entity): Adds a `topic_id` field binding it to a Telegram forum topic, and a `trigger_message_id` for traceability.
- **Project** (existing entity): Used as the routing table — mapping from issue-key prefix to repository path is the sole bridge between an incoming message and a workspace.
- **AuditEvent** (existing entity): Extended to record the new event types: `telegram_message_received`, `telegram_unauthorized`, `telegram_unknown_prefix`, `telegram_topic_created`, `telegram_session_started`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From the moment an authorized operator posts a valid issue key, a topic exists and an acknowledgement is visible within 5 seconds on a typical home network.
- **SC-002**: Unauthorized messages produce zero visible response in the chat (silent rejection rate is 100%) and 100% audit-log coverage.
- **SC-003**: Two simultaneously triggered sessions reach a terminal state without either one's repository state corrupting the other (verified across at least 10 paired runs).
- **SC-004**: Listener uptime, measured as fraction of time the daemon is running and the listener reports `running`, is at least 99% over a 7-day window of normal home use.
- **SC-005**: Operator-reported time from "I want to kick off this Jira ticket" to "PR is open and reviewable on my phone" is under 10 minutes for a small task that the agent can complete in one pass.
- **SC-006**: Zero instances over a 30-day window where a session ends in an unexplained state — every terminal state has either a PR URL (success) or a recorded failure reason.

## Assumptions

- The Telegram group is configured as a forum (topics enabled) and the bot has been granted topic-management permissions by the operator. This is a one-time setup, documented in the quickstart.
- The Claude Agent SDK is authenticated via the local `claude` CLI's OAuth session; no separate API key is required, consistent with the prior feature's decision (PRD §D11 / 001-cli-bootstrap research).
- All triggers originate from a single Telegram chat. Multi-chat or multi-bot operation is out of scope for this MVP.
- Triggers are text only. Voice messages, images, and documents are not interpreted.
- In-topic two-way conversation (operator replying inside a topic to influence the running agent) is out of scope for this MVP; topics are write-only from the bot's perspective during a session.
- Configuration changes (whitelist, token rotation) take effect on listener restart in MVP. Hot-reload is not in scope.
- Workers run as direct subprocesses of the daemon on the same host. Remote workers, container isolation, or sandboxing are out of scope.
- The existing `projects` table (from 001-cli-bootstrap) is the single source of truth for prefix-to-repository routing; no separate routing config is introduced.
- Network access to `api.telegram.org` is reliable enough at the operator's home that long-poll backoff and retry are sufficient — no offline queueing of outbound messages is required beyond a small in-memory buffer.
- The operator merges the resulting draft PR manually via the GitHub mobile app; this feature does not auto-merge.
