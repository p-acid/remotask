"""AT11 — both adapters satisfy the ``TaskSourceAdapter`` Protocol surface.

Parametrised over ``JiraAdapter`` and ``GitHubIssueAdapter`` instances.
Each adapter must expose the five Protocol methods with correct shapes.
"""
from __future__ import annotations

import pytest

from remotask.task_sources import TaskSourceAdapter
from remotask.task_sources.github_issue import GitHubIssueAdapter
from remotask.task_sources.jira import JiraAdapter


def _fake_project(identifier: str) -> dict:
    return {
        "source": "github_issue",
        "source_identifier": identifier,
        "repo_path": "/tmp/repo",
        "base_branch": "main",
        "enabled": 1,
        "added_at": 0,
        "updated_at": 0,
    }


@pytest.fixture(
    params=[
        pytest.param(("jira", "ZXTL-1234"), id="jira"),
        pytest.param(("github_issue", "p-acid/remotask#42"), id="github_issue"),
    ]
)
def adapter_with_input(request) -> tuple[TaskSourceAdapter, str]:  # type: ignore[no-untyped-def]
    kind, sample = request.param
    if kind == "jira":
        return JiraAdapter("test.atlassian.net"), sample
    return GitHubIssueAdapter([_fake_project("p-acid/remotask")]), sample


class TestProtocolConsistency:
    def test_matches_returns_str_or_none(
        self, adapter_with_input: tuple[TaskSourceAdapter, str]
    ) -> None:
        adapter, sample = adapter_with_input
        result = adapter.matches(sample)
        assert isinstance(result, str)
        # Negative case must return ``None``.
        assert adapter.matches("definitely-not-an-issue-key") is None

    def test_to_canonical_returns_str(
        self, adapter_with_input: tuple[TaskSourceAdapter, str]
    ) -> None:
        adapter, sample = adapter_with_input
        canonical = adapter.to_canonical(sample)
        assert isinstance(canonical, str)
        assert canonical  # non-empty

    def test_extract_project_identifier_returns_str(
        self, adapter_with_input: tuple[TaskSourceAdapter, str]
    ) -> None:
        adapter, sample = adapter_with_input
        canonical = adapter.to_canonical(sample)
        identifier = adapter.extract_project_identifier(canonical)
        assert isinstance(identifier, str)
        assert identifier

    def test_format_issue_url_returns_str_url(
        self, adapter_with_input: tuple[TaskSourceAdapter, str]
    ) -> None:
        adapter, sample = adapter_with_input
        canonical = adapter.to_canonical(sample)
        url = adapter.format_issue_url(canonical)
        assert isinstance(url, str)
        assert url.startswith("https://")

    def test_fetch_context_returns_4_field_payload(
        self,
        adapter_with_input: tuple[TaskSourceAdapter, str],
        mock_gh_issue_view: object,
    ) -> None:
        mock_gh_issue_view(  # type: ignore[operator]
            {"title": "T", "body": "B", "state": "open", "labels": ["a"]}
        )
        adapter, sample = adapter_with_input
        canonical = adapter.to_canonical(sample)
        payload = adapter.fetch_context(canonical)
        assert set(payload.keys()) == {"title", "body", "state", "labels"}
        assert isinstance(payload["title"], str)
        assert isinstance(payload["body"], str)
        assert payload["state"] in ("open", "closed")
        assert isinstance(payload["labels"], list)
