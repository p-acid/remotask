"""Test double for ``TaskSourceAdapter`` (008).

Records ``os.getpid()`` on every ``fetch_context`` call so AT7 can assert
that the credential read crosses the daemon → worker process boundary.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, TypedDict


class ContextPayload(TypedDict):
    """Provider-agnostic 4-field issue context (008 Behavior)."""

    title: str
    body: str
    state: Literal["open", "closed"]
    labels: list[str]


@dataclass
class FakeTaskSourceAdapter:
    """In-memory adapter recording PID on each ``fetch_context``.

    AT7 asserts ``last_fetch_pid != daemon_pid`` to prove the credential
    read happens inside the worker subprocess.
    """

    name: str = "fake"
    key_pattern: str = "FAKE-"  # ``matches`` accepts any text starting with this
    project_identifier: str = "FAKE"
    last_fetch_pid: int | None = None
    payload: ContextPayload = field(
        default_factory=lambda: ContextPayload(
            title="fake title",
            body="fake body",
            state="open",
            labels=[],
        )
    )

    def matches(self, text: str) -> str | None:
        idx = text.find(self.key_pattern)
        if idx < 0:
            return None
        # Return the first whitespace-delimited token starting at the match.
        token = text[idx:].split()[0]
        return token

    def to_canonical(self, operator_input: str) -> str:
        return operator_input  # identity for the fake

    def extract_project_identifier(self, canonical_key: str) -> str:
        return self.project_identifier

    def fetch_context(self, canonical_key: str) -> ContextPayload:
        self.last_fetch_pid = os.getpid()
        return self.payload

    def format_issue_url(self, canonical_key: str) -> str:
        return f"https://fake.example/{canonical_key}"
