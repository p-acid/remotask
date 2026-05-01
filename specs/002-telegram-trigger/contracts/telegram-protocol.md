# Telegram Protocol Contract

**Feature**: 002-telegram-trigger
**Status**: Phase 1 design

This document defines the message-level contract between the operator (humans posting in Telegram) and the daemon: what messages are accepted, what replies/topics result, and what is silently ignored.

## Inbound message grammar

The listener processes only **text** messages from the configured `group_chat_id`. Other update types (edited messages, channel posts, callback queries, voice, photos, documents, stickers) are ignored without audit-log entries.

A text message is a **trigger candidate** if and only if its text contains at least one substring matching:

```
\b[A-Z][A-Z0-9_]{1,9}-\d{1,6}\b
```

Notes:
- Whole-word boundaries on both sides — `aZXTL-1234b` is not a match.
- Prefix is 2–10 uppercase letters/digits/underscores starting with a letter (matches Atlassian's project-key rules).
- The first match in the message is the trigger; later matches in the same message are ignored. (Documented in spec Edge Cases.)
- Messages with no match are silently ignored (no log noise, no reply).

## Decision tree per inbound message

```
text message arrives in configured chat
        │
        ├─ sender_id NOT in whitelist
        │    → write WARNING audit log (telegram_unauthorized)
        │    → no reply, no topic, no session
        │
        ├─ sender_id IN whitelist
        │    │
        │    ├─ text has no issue-key match
        │    │    → ignore entirely
        │    │
        │    └─ first issue-key match = <KEY>
        │         │
        │         ├─ extract prefix from <KEY>
        │         │
        │         ├─ prefix not in projects (or row.enabled=0)
        │         │    → reply in main chat:
        │         │      "Unknown project prefix '<P>'. Registered: <list>."
        │         │    → audit log (telegram_unknown_prefix)
        │         │
        │         ├─ same-issue session already active
        │         │    → reply in main chat:
        │         │      "Issue <KEY> is already in flight (topic: <link>)."
        │         │    → audit log (telegram_already_in_flight)
        │         │
        │         ├─ max_concurrent cap reached
        │         │    → reply in main chat:
        │         │      "Concurrent session limit (<N>) reached; try again
        │         │       once one finishes."
        │         │
        │         └─ accepted
        │              ├─ insert sessions row (status=enqueued)
        │              ├─ acquire issue lock
        │              ├─ createForumTopic name=<KEY>
        │              ├─ on success: store topic_id, post "session starting…",
        │              │   transition to status=starting, spawn worker
        │              └─ on createForumTopic failure:
        │                   → reply in main chat:
        │                     "Cannot create topic for <KEY>: <reason>.
        │                      Bot may need 'Manage Topics' permission."
        │                   → mark session failed
        │                   → audit log (telegram_topic_create_failed)
```

## Outbound message templates

All outbound messages use plain text (no Markdown/HTML parsing flags), to avoid escape bugs in operator-visible text.

### Topic-bound (sent into the per-session topic)

| Trigger | Template |
|---------|----------|
| Session starting | `Session starting for <KEY>.\nWorktree: <abs path>\nBranch: <name>` |
| State transition | `Status: <new_status>` |
| PR created | `Draft PR opened: <pr_url>` |
| Worker failed | `Session failed: <one-line reason>` |
| Worker timed out | `Session terminated: timeout (<N>s)` |
| Daemon restart cleanup | `Session terminated by daemon restart.` |

### Main-chat-bound (sent in the group, not in a topic)

| Trigger | Template |
|---------|----------|
| Unknown prefix | `Unknown project prefix '<P>'. Registered prefixes: <comma list>` |
| Already in flight | `Issue <KEY> is already in flight (topic id: <topic_id>).` |
| Concurrency cap | `Concurrent session limit (<N>) reached; try again once one finishes.` |
| Topic create failure | `Cannot create topic for <KEY>: <reason>. Make sure the bot has 'Manage Topics' permission.` |
| Listener disabled | (no reply — silent rejection if listener is stopped, by design) |

## Bot Telegram API surface used

Only three Bot API methods are called:

| Method | Purpose |
|--------|---------|
| `getUpdates` | Long-poll inbound messages. Parameters: `timeout=<poll_timeout_seconds>`, `allowed_updates=["message"]`, `offset=<last_update_id+1>`. |
| `createForumTopic` | Create a new forum topic per accepted trigger. Parameters: `chat_id=<group_chat_id>`, `name=<KEY>`. |
| `sendMessage` | Post text to either the main chat or a topic. Parameters: `chat_id=<group_chat_id>`, `text=<...>`, optional `message_thread_id=<topic_id>`. |

No other Bot API methods are used. In particular: no `editMessage`, no inline keyboards, no `setWebhook`.

## Update offset persistence

The Telegram `getUpdates` API requires the client to track `update_id` to avoid re-processing. The daemon persists `last_update_id` in `~/.local/share/remotask/listener.state` (alongside the existing fields). On startup, the listener reads this value and resumes from `last_update_id + 1`.

If the file is missing or corrupt on startup, the listener calls `getUpdates(offset=-1, limit=1)` once to discover the latest update and skip ahead — this prevents replaying potentially weeks of stale messages after a long downtime.

## Rate limits and politeness

- Outbound messages are sent serially with at least 50ms spacing to stay under Telegram's per-bot rate limit comfortably.
- On HTTP 429 responses with `retry_after`, the listener honours the value (sleeps the requested duration before next call).

## Privacy / log redaction

- Trigger message bodies are stored in `sessions.trigger_text` (existing column) verbatim, because the operator owns the chat and message contents are part of the audit trail.
- The bot token is never logged or stored outside `config.toml`.
- Sender display names are NOT persisted (only numeric `sender_id`), to limit PII surface.
