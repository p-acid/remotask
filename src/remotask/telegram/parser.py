"""Telegram message parsers — issue-key trigger, termination grammar, slash commands.

The grammars are fixed by the contracts in ``specs/002-…/`` (issue-key),
``specs/003-…/`` (termination), and ``specs/004-…/`` (slash commands).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Word-boundary anchored. Prefix is 2-10 chars (1+9), starting with an uppercase
# letter, then up to 9 uppercase letters / digits / underscores. Number is 1-6
# digits. The first match wins (per protocol contract).
_ISSUE_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9_]{1,9}-\d{1,6}\b")


def extract_first_issue_key(text: str) -> str | None:
    """Return the first issue key in ``text``, or ``None`` when no key matches.

    Pure function — performs no I/O, never raises on input shape.
    """
    if not text:
        return None
    m = _ISSUE_KEY_RE.search(text)
    return m.group(0) if m else None


def split_prefix(issue_key: str) -> str:
    """Return the prefix portion of an issue key (the part before the dash)."""
    return issue_key.split("-", 1)[0]


# 003 termination grammar: a single token from a small fixed set, case-insensitive.
# Match is performed against the trimmed text to absorb trailing whitespace.
_TERMINATION_RE = re.compile(r"^(done|stop|finish)$", re.IGNORECASE)


def match_termination_command(text: str) -> str | None:
    """Return the canonical lowercase token if ``text`` is a termination command.

    The grammar is intentionally narrow (single token from ``{done, stop,
    finish}``, case-insensitive) so that ordinary topic chat doesn't
    accidentally cancel a session.
    """
    if not text:
        return None
    m = _TERMINATION_RE.match(text.strip())
    if m is None:
        return None
    return m.group(1).lower()


# 004: slash-command parser. Telegram annotates `/foo bar` messages with
# entities[0].type == "bot_command" at offset 0. We trust the entity rather
# than re-grammaring the text — that's how clients themselves recognise the
# autocomplete-driven command.


@dataclass(frozen=True)
class SlashCommandInvocation:
    """An inbound message recognised as a slash command.

    Args are the trimmed text after the command (and after ``@<botname>`` if
    present). They preserve any internal whitespace verbatim so the operator's
    free-text request reaches the worker untouched.
    """

    name: str  # canonical lowercase, no leading slash
    args_text: str  # everything after the command, leading whitespace stripped
    sender_id: int
    chat_id: int
    message_thread_id: int | None
    message_id: int


def match_slash_command(
    message: dict[str, Any], *, bot_username: str | None = None
) -> SlashCommandInvocation | None:
    """Return a ``SlashCommandInvocation`` if ``message`` carries a slash command.

    Recognition rule (per ``contracts/slash-command-protocol.md``):

    - The message must have an ``entities`` array.
    - One of those entities must have ``type == "bot_command"`` and
      ``offset == 0``.

    Anything else (no entity, entity at non-zero offset, edited messages with a
    different shape) returns ``None``.
    """
    entities = message.get("entities") or []
    cmd_entity = next(
        (
            e
            for e in entities
            if e.get("type") == "bot_command" and e.get("offset") == 0
        ),
        None,
    )
    if cmd_entity is None:
        return None

    text = message.get("text") or ""
    length = int(cmd_entity.get("length") or 0)
    if length <= 0:
        return None

    raw = text[:length]
    rest = text[length:].lstrip()

    # raw is "/run" or "/run@curious_claude_notification_bot".
    name_with_at = raw.lstrip("/")
    name = name_with_at.split("@", 1)[0].lower()
    if not name:
        return None

    # If a bot username is known and it appears as the suffix, it must match.
    # We don't *require* a known bot_username (it's optional in the runtime),
    # but if we have it we use it to defend against hostile @<otherbot>
    # suffixes that some Telegram clients would still send our way.
    if "@" in name_with_at and bot_username is not None:
        provided_bot = name_with_at.split("@", 1)[1].lower()
        if provided_bot != bot_username.lower():
            return None

    sender = (message.get("from") or {}).get("id")
    chat = (message.get("chat") or {}).get("id")
    if sender is None or chat is None:
        return None

    return SlashCommandInvocation(
        name=name,
        args_text=rest,
        sender_id=int(sender),
        chat_id=int(chat),
        message_thread_id=(
            int(message["message_thread_id"])
            if message.get("message_thread_id") is not None
            else None
        ),
        message_id=int(message.get("message_id") or 0),
    )
