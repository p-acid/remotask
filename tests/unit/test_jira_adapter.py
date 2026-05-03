"""Unit tests for ``JiraAdapter`` (008 AT1 / AT2 / AT3).

The Jira adapter absorbs the 002 ``_ISSUE_KEY_RE`` and ``split_prefix``
from ``telegram/parser.py`` into Protocol methods (`matches` and
`extract_project_identifier`). ``format_issue_url`` reads ``host`` from
the constructor.
"""
from __future__ import annotations

import pytest

# T1: tests are written against the desired post-state. The import below
# fails (red) until T3 lands the JiraAdapter implementation.
from remotask.task_sources.jira import JiraAdapter  # noqa: E402


class TestJiraAdapterMatches:
    """AT1 — Jira adapter recognises the 002 grammar verbatim."""

    def test_extracts_simple_key(self) -> None:
        adapter = JiraAdapter("test.atlassian.net")
        assert adapter.matches("ZXTL-1234") == "ZXTL-1234"

    def test_extracts_key_in_sentence(self) -> None:
        adapter = JiraAdapter("test.atlassian.net")
        assert adapter.matches("please look at ZXTL-1234 thanks") == "ZXTL-1234"

    def test_first_match_wins(self) -> None:
        adapter = JiraAdapter("test.atlassian.net")
        assert adapter.matches("ZXTL-1234 and FOO-9") == "ZXTL-1234"

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "no issue keys here",
            "lowercase-1234",
            "ab-12",  # prefix too short
            "ZXTL-",
            "ZXTL-abc",
        ],
    )
    def test_no_match_returns_none(self, text: str) -> None:
        adapter = JiraAdapter("test.atlassian.net")
        assert adapter.matches(text) is None


class TestJiraAdapterRejectsForeignShape:
    """AT2 — active Jira adapter rejects GitHub-shape input.

    Proves the active adapter — not a hard-coded regex — owns the trigger
    gate. With ``agent.task_source = "jira"``, an ``owner/repo#42``
    payload must not produce a key.
    """

    def test_owner_repo_hash_is_not_a_jira_key(self) -> None:
        adapter = JiraAdapter("test.atlassian.net")
        assert adapter.matches("owner/repo#42") is None
        assert adapter.matches("p-acid/remotask#42") is None


class TestJiraAdapterCanonicalAndProject:
    """``to_canonical`` is identity for Jira; ``extract_project_identifier``
    yields the prefix.
    """

    def test_to_canonical_is_identity(self) -> None:
        adapter = JiraAdapter("test.atlassian.net")
        assert adapter.to_canonical("ZXTL-1234") == "ZXTL-1234"

    def test_extract_project_identifier_returns_prefix(self) -> None:
        adapter = JiraAdapter("test.atlassian.net")
        assert adapter.extract_project_identifier("ZXTL-1234") == "ZXTL"


class TestJiraAdapterFormatIssueUrl:
    """AT3 — Jira URL formatter."""

    def test_url_uses_constructor_host(self) -> None:
        adapter = JiraAdapter("mission.atlassian.net")
        assert (
            adapter.format_issue_url("ZXTL-1234")
            == "https://mission.atlassian.net/browse/ZXTL-1234"
        )

    def test_empty_host_raises_on_format(self) -> None:
        adapter = JiraAdapter("")
        with pytest.raises(ValueError):
            adapter.format_issue_url("ZXTL-1234")
