"""Jira adapter — first concrete ``TaskSourceAdapter`` implementation (008/T3).

Absorbs the 002 ``_ISSUE_KEY_RE`` (``telegram/parser.py:15``) into
``matches`` and ``split_prefix`` (``telegram/parser.py:29``) into
``extract_project_identifier``. The legacy ``parser.py`` symbols are
removed in T4 alongside the dispatcher's two call-site rewrites; T3
introduces the new home so that step is purely a delete + import update.
"""
from __future__ import annotations

import re

from remotask.task_sources import ContextPayload

# Word-boundary anchored. Prefix is 2-10 chars (1+9), starting with an
# uppercase letter, then up to 9 uppercase letters / digits / underscores.
# Number is 1-6 digits. The first match wins (per protocol contract).
_ISSUE_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9_]{1,9}-\d{1,6}\b")


class JiraAdapter:
    """Jira retrofit for the ``TaskSourceAdapter`` Protocol.

    Constructor takes the Jira host as a single dependency (``self.host``);
    ``format_issue_url`` raises if it is empty so misconfiguration fails
    loudly at format time rather than silently producing a broken link.
    """

    def __init__(self, host: str) -> None:
        self.host = host

    def matches(self, text: str) -> str | None:
        if not text:
            return None
        m = _ISSUE_KEY_RE.search(text)
        return m.group(0) if m else None

    def to_canonical(self, operator_input: str) -> str:
        # Jira keys are already fs/git-safe (uppercase + digits + dash).
        return operator_input

    def extract_project_identifier(self, canonical_key: str) -> str:
        # Jira: prefix is the project key. ``ZXTL-1234`` → ``ZXTL``.
        return canonical_key.split("-", 1)[0]

    def fetch_context(self, canonical_key: str) -> ContextPayload:
        """Read-only issue context for the agent-side bootstrap.

        The MVP implementation is operator-supplied: the agent-side
        bootstrap (Out-of-scope per 008) shells out to a Jira CLI or REST
        API with the operator's own credentials. T3 ships an inert
        placeholder so the Protocol surface is exercised; concrete API
        integration is a follow-up when a need surfaces (CLAUDE.md §2 —
        no abstractions for single-use code).
        """
        return ContextPayload(
            title=f"[Jira issue {canonical_key}]",
            body=(
                "(placeholder — agent-side bootstrap fetches the actual "
                "issue body via the operator's Jira credentials)"
            ),
            state="open",
            labels=[],
        )

    def format_issue_url(self, canonical_key: str) -> str:
        if not self.host:
            raise ValueError(
                "JiraAdapter.host is empty; set jira.host in config.toml "
                "to format issue URLs"
            )
        return f"https://{self.host}/browse/{canonical_key}"
