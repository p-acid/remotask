"""Unit tests for ``GitHubIssueAdapter`` (008 AT4 / AT5 / AT6 / AT7).

GitHub Issue adapter normalises ``owner/repo#N`` (or ``#N`` shorthand
when exactly one project is registered) into the canonical
``gh-<owner>-<repo>-<n>`` form. ``fetch_context`` runs in the worker
subprocess (PID assertion in AT7).
"""
from __future__ import annotations

import os
import subprocess

import pytest

# T1: tests fail until T6 implements the adapter.
from remotask.task_sources.github_issue import GitHubIssueAdapter  # noqa: E402


def _fake_project(identifier: str, repo_path: str = "/tmp/repo") -> dict:
    """Minimal ``ProjectRow``-shaped dict for adapter construction."""
    return {
        "source": "github_issue",
        "source_identifier": identifier,
        "repo_path": repo_path,
        "base_branch": "main",
        "enabled": 1,
        "added_at": 0,
        "updated_at": 0,
    }


class TestGitHubIssueAdapterMatches:
    """AT4 — adapter recognises ``owner/repo#N`` and ``#N`` shorthand."""

    def test_full_form_matches(self) -> None:
        adapter = GitHubIssueAdapter([_fake_project("p-acid/remotask")])
        assert adapter.matches("p-acid/remotask#42") == "p-acid/remotask#42"

    def test_shorthand_matches_with_single_project(self) -> None:
        adapter = GitHubIssueAdapter([_fake_project("p-acid/remotask")])
        assert adapter.matches("#42") == "#42"

    def test_shorthand_rejected_with_multiple_projects(self) -> None:
        """When 2+ projects are registered, ``#N`` is ambiguous → ``None``."""
        adapter = GitHubIssueAdapter(
            [
                _fake_project("p-acid/remotask"),
                _fake_project("p-acid/another"),
            ]
        )
        assert adapter.matches("#42") is None

    def test_jira_shape_rejected(self) -> None:
        adapter = GitHubIssueAdapter([_fake_project("p-acid/remotask")])
        assert adapter.matches("ZXTL-1234") is None


class TestGitHubIssueAdapterCanonicalForm:
    """AT4 — normalisation to ``gh-<owner>-<repo>-<n>`` (collision-free)."""

    def test_full_form_normalises(self) -> None:
        adapter = GitHubIssueAdapter([_fake_project("p-acid/remotask")])
        assert (
            adapter.to_canonical("p-acid/remotask#42") == "gh-p-acid-remotask-42"
        )

    def test_shorthand_normalises_to_active_project(self) -> None:
        adapter = GitHubIssueAdapter([_fake_project("p-acid/remotask")])
        assert adapter.to_canonical("#42") == "gh-p-acid-remotask-42"

    def test_owner_segment_avoids_collision(self) -> None:
        """``a/foo#1`` and ``b/foo#1`` must produce distinct canonical keys."""
        adapter_a = GitHubIssueAdapter([_fake_project("a/foo")])
        adapter_b = GitHubIssueAdapter([_fake_project("b/foo")])
        assert adapter_a.to_canonical("a/foo#1") != adapter_b.to_canonical("b/foo#1")


class TestGitHubIssueAdapterProjectIdentifier:
    def test_extract_project_from_canonical(self) -> None:
        adapter = GitHubIssueAdapter([_fake_project("p-acid/remotask")])
        assert (
            adapter.extract_project_identifier("gh-p-acid-remotask-42")
            == "p-acid/remotask"
        )


class TestGitHubIssueAdapterFormatIssueUrl:
    """AT5 — GitHub URL formatter."""

    def test_url_points_to_github_issues_path(self) -> None:
        adapter = GitHubIssueAdapter([_fake_project("p-acid/remotask")])
        assert (
            adapter.format_issue_url("gh-p-acid-remotask-42")
            == "https://github.com/p-acid/remotask/issues/42"
        )


class TestGitHubIssueAdapterCanonicalKeyIsGitRefSafe:
    """AT6 — sanitisation invariant: canonical key passes ``git check-ref-format``."""

    @pytest.mark.parametrize(
        "operator_input",
        [
            "p-acid/remotask#42",
            "#42",
        ],
    )
    def test_canonical_is_valid_branch_component(
        self, operator_input: str
    ) -> None:
        adapter = GitHubIssueAdapter([_fake_project("p-acid/remotask")])
        canonical = adapter.to_canonical(operator_input)
        # ``agent/<canonical>`` is the branch name shape from 003.
        result = subprocess.run(
            ["git", "check-ref-format", f"refs/heads/agent/{canonical}"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"git check-ref-format rejected {canonical!r}: {result.stderr}"
        )


class TestGitHubIssueAdapterFetchContextCrossesProcessBoundary:
    """AT7 — credential read happens in worker PID, not daemon PID.

    The fake adapter pattern: the adapter records ``os.getpid()`` on each
    fetch. The test launches the adapter inside a subprocess and asserts
    the recorded PID differs from the test (≈ daemon) PID.
    """

    def test_fetch_records_caller_pid(
        self, mock_gh_issue_view: object
    ) -> None:
        # Configure mock once (no-op for this PID-only assertion).
        mock_gh_issue_view({"title": "x", "body": "y", "state": "open", "labels": []})  # type: ignore[operator]
        adapter = GitHubIssueAdapter([_fake_project("p-acid/remotask")])
        daemon_pid = os.getpid()
        adapter.fetch_context("gh-p-acid-remotask-42")
        # When the adapter is exercised in-process the recorded PID equals
        # the test PID; the actual daemon-vs-worker boundary is exercised
        # by the integration test (test_credential_boundary). Here we only
        # pin the *interface*: the adapter writes its caller PID to
        # ``last_fetch_pid``.
        assert adapter.last_fetch_pid == daemon_pid

    def test_subprocess_invocation_records_different_pid(
        self, tmp_path
    ) -> None:
        """Strong form of AT7: spawn the adapter in a child process and
        assert the recorded PID differs from the parent (daemon) PID.
        """
        import sys
        import textwrap

        script = tmp_path / "child.py"
        script.write_text(
            textwrap.dedent(
                """
                import json
                import os
                import sys
                from unittest.mock import patch

                from remotask.task_sources.github_issue import GitHubIssueAdapter

                project = {
                    "source": "github_issue",
                    "source_identifier": "p-acid/remotask",
                    "repo_path": "/tmp/repo",
                    "base_branch": "main",
                    "enabled": 1, "added_at": 0, "updated_at": 0,
                }
                with patch("subprocess.run") as run:
                    run.return_value = type(
                        "R", (),
                        {"returncode": 0, "stdout": "{}", "stderr": ""},
                    )()
                    adapter = GitHubIssueAdapter([project])
                    adapter.fetch_context("gh-p-acid-remotask-42")
                    print(json.dumps({"pid": adapter.last_fetch_pid}))
                """
            ).strip()
        )
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            check=True,
        )
        import json as _json

        child_pid = _json.loads(result.stdout)["pid"]
        assert child_pid != os.getpid()
