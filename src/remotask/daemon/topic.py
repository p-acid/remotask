"""Telegram topic / message helpers — pure outbound side of the protocol.

The wording of every outbound message is fixed by
``contracts/telegram-protocol.md``. Centralising the templates here keeps the
text on one screen so we never end up with two slightly different "Session
starting…" lines in dispatcher and worker.

Plain text only; we never set ``parse_mode`` because escaping bugs in
operator-visible text are worse than missing formatting.
"""
from __future__ import annotations

from typing import Final

from remotask.telegram.client import ForumTopic, TelegramAPIError, TelegramClient

# ---- topic-bound templates (sent into the per-session topic) -------------

TPL_SESSION_STARTING: Final = "Session starting for {key}.\nWorktree: {worktree}\nBranch: {branch}"
TPL_STATUS: Final = "Status: {status}"
TPL_PR_CREATED: Final = "Draft PR opened: {pr_url}"
TPL_SESSION_FAILED: Final = "Session failed: {reason}"
TPL_SESSION_TIMEOUT: Final = "Session terminated: timeout ({seconds}s)"
TPL_DAEMON_RESTART_CLEANUP: Final = "Session terminated by daemon restart."
TPL_PROGRESS: Final = "Status: iteration {i}/{n} @ {ts}"
TPL_FINAL: Final = "Status: final iteration {i} ({reason})"
TPL_OPERATOR_STOPPED: Final = "Session stopped by operator."
TPL_OPERATOR_STOPPED_FORCED: Final = "Session force-stopped by operator (grace window exceeded)."

# ---- main-chat-bound templates (sent in the group, not in a topic) -------

TPL_UNKNOWN_PREFIX: Final = (
    "Unknown project prefix '{prefix}'. Registered prefixes: {prefixes}"
)
TPL_ALREADY_IN_FLIGHT: Final = (
    "Issue {key} is already in flight (topic id: {topic_id})."
)
TPL_CONCURRENCY_CAP: Final = (
    "Concurrent session limit ({cap}) reached; try again once one finishes."
)
TPL_TOPIC_CREATE_FAILED: Final = (
    "Cannot create topic for {key}: {reason}. "
    "Make sure the bot has 'Manage Topics' permission."
)


async def create_topic_for_session(
    client: TelegramClient, *, chat_id: int, issue_key: str
) -> ForumTopic:
    """Create a forum topic named after ``issue_key``; returns the new topic.

    Propagates ``TelegramAPIError`` so the caller can decide how to surface the
    failure (the dispatcher posts ``TPL_TOPIC_CREATE_FAILED`` to the main chat
    on this error and records ``telegram_topic_create_failed``).
    """
    return await client.create_forum_topic(chat_id=chat_id, name=issue_key)


async def post_to_topic(
    client: TelegramClient,
    *,
    chat_id: int,
    topic_id: int,
    text: str,
) -> None:
    """Send ``text`` into the per-session topic.

    Best-effort: a transport blip should not bubble up and crash the worker
    state machine. The caller logs the error and continues.
    """
    try:
        await client.send_message(chat_id=chat_id, text=text, message_thread_id=topic_id)
    except TelegramAPIError:
        # Caller (dispatcher / worker / runtime) decides whether to log this.
        # We swallow here so a single failed sendMessage never aborts a state
        # transition on the DB side.
        return


async def post_to_main_chat(
    client: TelegramClient, *, chat_id: int, text: str
) -> None:
    """Send ``text`` to the main chat (no ``message_thread_id``)."""
    try:
        await client.send_message(chat_id=chat_id, text=text)
    except TelegramAPIError:
        return
