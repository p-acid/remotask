"""Pure issue-key extraction.

The grammar is fixed by ``contracts/telegram-protocol.md``:
``\\b[A-Z][A-Z0-9_]{1,9}-\\d{1,6}\\b``. The first match in the message is the
trigger; later matches are ignored.
"""
from __future__ import annotations

import re

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
