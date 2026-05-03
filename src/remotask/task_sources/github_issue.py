"""GitHub Issue adapter — second concrete ``TaskSourceAdapter`` (008/T6).

Constructor takes the list of registered ``(source="github_issue")``
``ProjectRow`` rows from ``rt_projects.list_all(conn)`` (factory injects
the filtered slice). The adapter uses that list both for ``#N`` shorthand
resolution and for ``extract_project_identifier`` reverse lookup.

Authentication delegates to the operator's host-level ``gh auth status``
(D5 / D7 delegate-down posture); ``fetch_context`` shells out to
``gh issue view``. Tests use the ``mock_gh_issue_view`` fixture in
``tests/conftest.py`` to avoid hitting the real GitHub API.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any

from remotask.task_sources import ContextPayload

# ``owner/repo#N`` — alphanumerics + dot / dash / underscore in each segment.
_FULL_RE = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#\d+")
# ``#N`` shorthand — anchored on a non-word, non-slash boundary so it
# doesn't capture the trailing ``#42`` of a ``p-acid/remotask#42`` form
# (the full regex above wins on those).
_SHORT_RE = re.compile(r"(?:^|[^\w/])#(\d+)\b")


class GitHubIssueAdapter:
    """GitHub-Issue retrofit for the ``TaskSourceAdapter`` Protocol."""

    def __init__(self, projects: list[dict[str, Any]]) -> None:
        # ``projects`` is the filtered list (source == "github_issue")
        # injected by ``get_active_adapter``. Tests pass a list of dicts
        # mirroring the ``ProjectRow`` shape.
        self._projects = list(projects)
        # AT7 instrumentation: PID recorded on every ``fetch_context`` call.
        self.last_fetch_pid: int | None = None

    # ---- Protocol methods -------------------------------------------------

    def matches(self, text: str) -> str | None:
        if not text:
            return None
        # Full ``owner/repo#N`` form wins.
        m = _FULL_RE.search(text)
        if m is not None:
            return m.group(0)
        # ``#N`` shorthand resolves only when exactly one project is
        # registered (B2 policy). Otherwise return None — the dispatcher
        # falls through to a "specify owner/repo#N" reply (Telegram-side
        # UX, not part of the adapter contract).
        if len(self._projects) != 1:
            return None
        m = _SHORT_RE.search(text)
        if m is not None:
            return f"#{m.group(1)}"
        return None

    def to_canonical(self, operator_input: str) -> str:
        if operator_input.startswith("#"):
            # Shorthand: resolve against the single registered project.
            if len(self._projects) != 1:
                raise ValueError(
                    "GitHubIssueAdapter.to_canonical: '#N' shorthand "
                    "requires exactly one registered project"
                )
            identifier = self._projects[0]["source_identifier"]
            n = operator_input[1:]
        elif "#" in operator_input and "/" in operator_input:
            identifier, n = operator_input.split("#", 1)
        else:
            raise ValueError(
                f"GitHubIssueAdapter.to_canonical: invalid input "
                f"{operator_input!r} (expected 'owner/repo#N' or '#N')"
            )
        if "/" not in identifier:
            raise ValueError(
                f"GitHubIssueAdapter.to_canonical: identifier "
                f"{identifier!r} is not in owner/repo form"
            )
        owner, repo = identifier.split("/", 1)
        return f"gh-{owner}-{repo}-{n}"

    def extract_project_identifier(self, canonical_key: str) -> str:
        owner, repo, _n = self._parse_canonical(canonical_key)
        return f"{owner}/{repo}"

    def fetch_context(self, canonical_key: str) -> ContextPayload:
        self.last_fetch_pid = os.getpid()
        owner, repo, n = self._parse_canonical(canonical_key)
        identifier = f"{owner}/{repo}"
        result = subprocess.run(
            [
                "gh",
                "issue",
                "view",
                str(n),
                "--repo",
                identifier,
                "--json",
                "title,body,state,labels",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        # gh exits non-zero when the issue / repo is unavailable; the
        # adapter surfaces an empty payload so the agent-side bootstrap
        # can decide how to react. Strict failure could be added when a
        # second concrete consumer needs it (CLAUDE.md §2).
        if result.returncode != 0 or not result.stdout.strip():
            return ContextPayload(title="", body="", state="open", labels=[])
        data = json.loads(result.stdout)
        state_raw = (data.get("state") or "open").lower()
        state: Any = "closed" if state_raw == "closed" else "open"
        labels = data.get("labels") or []
        # ``gh issue view`` returns labels as ``[{"name": "...", ...}, ...]``.
        # Extract just the names so ``ContextPayload.labels`` is a flat list.
        if labels and isinstance(labels[0], dict):
            label_names = [lbl.get("name", "") for lbl in labels]
        else:
            label_names = list(labels)
        return ContextPayload(
            title=data.get("title", "") or "",
            body=data.get("body", "") or "",
            state=state,
            labels=label_names,
        )

    def format_issue_url(self, canonical_key: str) -> str:
        owner, repo, n = self._parse_canonical(canonical_key)
        return f"https://github.com/{owner}/{repo}/issues/{n}"

    # ---- helpers ----------------------------------------------------------

    def _parse_canonical(self, canonical_key: str) -> tuple[str, str, int]:
        """Reverse ``gh-<owner>-<repo>-<n>`` → ``(owner, repo, n)``.

        Owner / repo names may legally contain ``-``; the only reliable
        reverse is to match the canonical against each registered
        project's ``owner/repo`` identifier.
        """
        if not canonical_key.startswith("gh-"):
            raise ValueError(
                f"not a GitHub canonical key: {canonical_key!r}"
            )
        body = canonical_key[3:]  # "<owner>-<repo>-<n>"
        last_dash = body.rfind("-")
        if last_dash < 0:
            raise ValueError(f"malformed canonical key: {canonical_key!r}")
        owner_repo_dashed = body[:last_dash]  # "<owner>-<repo>"
        n_str = body[last_dash + 1:]
        if not n_str.isdigit():
            raise ValueError(f"malformed canonical key: {canonical_key!r}")
        # Match against registered projects.
        for proj in self._projects:
            identifier = proj.get("source_identifier", "")
            if "/" not in identifier:
                continue
            owner, repo = identifier.split("/", 1)
            if owner_repo_dashed == f"{owner}-{repo}":
                return owner, repo, int(n_str)
        raise ValueError(
            f"canonical key {canonical_key!r} does not match any "
            f"registered GitHub project"
        )
