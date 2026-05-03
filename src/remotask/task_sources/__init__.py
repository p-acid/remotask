"""Task source adapter Protocol + factory (008).

008 promotes the task source-of-truth (today: Jira; next: GitHub Issue)
from a hard-pinned assumption to a per-install configurable axis. The
adapter Protocol defined here owns five responsibilities:

1. ``matches(text)`` — adapter-owned grammar, returns operator-input form.
2. ``to_canonical(operator_input)`` — normalises to a single fs/git-safe key.
3. ``extract_project_identifier(canonical_key)`` — derives the
   ``projects.source_identifier`` for the project lookup.
4. ``fetch_context(canonical_key)`` — read-only issue context.
5. ``format_issue_url(canonical_key)`` — source-issue back-link URL.

The factory ``get_active_adapter(cfg, conn)`` is a process-lifetime
singleton built once at daemon startup; config changes require a daemon
restart (no hot reload, matches the existing ``cfg`` posture).
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:
    from remotask.core.config import ConfigSchema


class ContextPayload(TypedDict):
    """Provider-agnostic 4-field issue context.

    Adapters collapse provider-native fields into this minimum set:
    - ``body`` is normalised to markdown (GitHub: native pass-through;
      Jira: ADF/wiki → markdown, plain-text fallback on conversion failure).
    - ``state`` collapses richer status sets to the binary pair: GitHub
      ``open`` / ``closed`` map directly; Jira ``Done`` / ``Resolved`` /
      ``Closed`` (and any ``Done``-category status) → ``"closed"``, every
      other status → ``"open"``.

    Richer fields (assignees, comments, custom Jira fields) are
    deliberately excluded for the abstraction's MVP and added only when a
    concrete second consumer needs them (CLAUDE.md §2 — Simplicity First).
    """

    title: str
    body: str
    state: Literal["open", "closed"]
    labels: list[str]


@runtime_checkable
class TaskSourceAdapter(Protocol):
    """Five-method Protocol implemented by ``JiraAdapter`` and
    ``GitHubIssueAdapter``.

    The dispatcher consumes adapters through ``DispatchContext.adapter``;
    direct instantiation lives behind :func:`get_active_adapter`.
    """

    def matches(self, text: str) -> str | None:
        """Return the operator-input form of the first issue key in ``text``,
        or ``None`` when no key matches.

        Jira: ``ZXTL-1234``. GitHub: ``owner/repo#42`` or ``#42`` shorthand
        (the latter only when exactly one project is registered).
        """
        ...

    def to_canonical(self, operator_input: str) -> str:
        """Normalise the operator-input form into the fs/git-safe canonical key.

        Jira: identity (``ZXTL-1234`` → ``ZXTL-1234``).
        GitHub: ``gh-<owner>-<repo>-<n>`` (collision-free across owners).
        """
        ...

    def extract_project_identifier(self, canonical_key: str) -> str:
        """Yield the ``projects.source_identifier`` for the project lookup.

        Jira: prefix (``ZXTL``). GitHub: ``<owner>/<repo>`` reconstructed
        from the canonical key + the active project mapping.
        """
        ...

    def fetch_context(self, canonical_key: str) -> ContextPayload:
        """Return read-only issue context for the agent-side bootstrap.

        Runs in the worker subprocess (D5 / D7 delegate-down posture);
        the daemon never holds task-source credentials.
        """
        ...

    def format_issue_url(self, canonical_key: str) -> str:
        """Return the source-issue back-link URL used by the topic chokepoint."""
        ...


# Process-lifetime singleton. Module-level cache mirrors the existing
# ``cfg`` posture (no hot reload — config changes require a daemon
# restart). Tests reset the cache via :func:`reset_cache`.
_cached_adapter: TaskSourceAdapter | None = None


def get_active_adapter(
    cfg: ConfigSchema, conn: sqlite3.Connection
) -> TaskSourceAdapter:
    """Return the ``TaskSourceAdapter`` instance for ``cfg.agent.task_source``.

    Built once at first call; subsequent calls return the cached instance.
    Both ``cfg`` *and* ``conn`` are required because the GitHub adapter's
    ``#N`` shorthand resolution must consult the active project mapping at
    construction time.
    """
    global _cached_adapter
    if _cached_adapter is not None:
        return _cached_adapter

    source = cfg.agent.task_source
    if source == "jira":
        from remotask.task_sources.jira import JiraAdapter

        _cached_adapter = JiraAdapter(host=cfg.jira.host)
    elif source == "github_issue":
        from remotask.core import projects as _projects
        from remotask.task_sources.github_issue import GitHubIssueAdapter

        rows = [
            r for r in _projects.list_all(conn) if r.get("source") == "github_issue"
        ]
        _cached_adapter = GitHubIssueAdapter(rows)
    else:
        raise ValueError(
            f"unknown agent.task_source: {source!r} (expected 'jira' or 'github_issue')"
        )
    return _cached_adapter


def reset_cache() -> None:
    """Drop the cached adapter. Tests call this between cases; production
    code never invokes it during normal daemon lifetime.
    """
    global _cached_adapter
    _cached_adapter = None
