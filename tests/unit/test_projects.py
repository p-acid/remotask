"""Unit tests for ``remotask.core.projects`` (008/T5 — provider-aware schema)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from remotask.core import projects


def _make_git_repo(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)  # noqa: S603, S607
    return p


# --- source validator ---


@pytest.mark.parametrize("source", ["jira", "github_issue"])
def test_source_validator_accepts(source: str) -> None:
    projects.validate_source(source)


@pytest.mark.parametrize("source", ["", "linear", "JIRA", "github"])
def test_source_validator_rejects(source: str) -> None:
    with pytest.raises(ValueError):
        projects.validate_source(source)


# --- repo_path validator ---


def test_repo_path_validator_accepts_git_repo(tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "repo")
    projects.validate_repo_path(str(repo))


def test_repo_path_validator_rejects_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        projects.validate_repo_path(str(tmp_path / "nope"))


def test_repo_path_validator_rejects_non_git(tmp_path: Path) -> None:
    plain = tmp_path / "not-git"
    plain.mkdir()
    with pytest.raises(ValueError):
        projects.validate_repo_path(str(plain))


# --- CRUD ---


def test_add_and_list_round_trip(tmp_path: Path) -> None:
    from remotask.core import db
    repo = _make_git_repo(tmp_path / "repo")
    conn = db.connect(tmp_path / "state.db")
    projects.add(conn, source="jira", identifier="ZXTL", repo_path=str(repo))
    rows = projects.list_all(conn)
    assert len(rows) == 1
    assert rows[0]["source"] == "jira"
    assert rows[0]["source_identifier"] == "ZXTL"
    assert rows[0]["base_branch"] == "main"
    assert rows[0]["enabled"] == 1


def test_add_duplicate_rejected(tmp_path: Path) -> None:
    from remotask.core import db
    repo = _make_git_repo(tmp_path / "repo")
    conn = db.connect(tmp_path / "state.db")
    projects.add(conn, source="jira", identifier="ZXTL", repo_path=str(repo))
    with pytest.raises(projects.DuplicateKeyError):
        projects.add(
            conn, source="jira", identifier="ZXTL", repo_path=str(repo)
        )


def test_add_same_identifier_different_source_allowed(tmp_path: Path) -> None:
    """Composite ``(source, identifier)`` PK permits the same identifier
    under different sources (e.g., a ``"foo"`` Jira prefix and a
    ``"foo/bar"`` GitHub identifier coexist in distinct rows).
    """
    from remotask.core import db
    repo = _make_git_repo(tmp_path / "repo")
    conn = db.connect(tmp_path / "state.db")
    projects.add(conn, source="jira", identifier="ZXTL", repo_path=str(repo))
    # Different source — must be accepted.
    projects.add(
        conn,
        source="github_issue",
        identifier="p-acid/remotask",
        repo_path=str(repo),
    )
    assert len(projects.list_all(conn)) == 2


def test_remove_existing(tmp_path: Path) -> None:
    from remotask.core import db
    repo = _make_git_repo(tmp_path / "repo")
    conn = db.connect(tmp_path / "state.db")
    projects.add(conn, source="jira", identifier="ZXTL", repo_path=str(repo))
    projects.remove(conn, source="jira", identifier="ZXTL")
    assert projects.list_all(conn) == []


def test_remove_unknown_raises(tmp_path: Path) -> None:
    from remotask.core import db
    conn = db.connect(tmp_path / "state.db")
    with pytest.raises(projects.UnknownKeyError):
        projects.remove(conn, source="jira", identifier="ZXTL")


def test_by_identifier_filters_by_source(tmp_path: Path) -> None:
    from remotask.core import db
    repo = _make_git_repo(tmp_path / "repo")
    conn = db.connect(tmp_path / "state.db")
    projects.add(conn, source="jira", identifier="ZXTL", repo_path=str(repo))
    assert (
        projects.by_identifier(conn, source="jira", identifier="ZXTL") is not None
    )
    # Cross-source lookup with the same identifier returns None.
    assert (
        projects.by_identifier(
            conn, source="github_issue", identifier="ZXTL"
        )
        is None
    )


def test_list_registered_identifiers_filters_by_source(tmp_path: Path) -> None:
    from remotask.core import db
    repo = _make_git_repo(tmp_path / "repo")
    conn = db.connect(tmp_path / "state.db")
    projects.add(conn, source="jira", identifier="ZXTL", repo_path=str(repo))
    projects.add(
        conn,
        source="github_issue",
        identifier="p-acid/remotask",
        repo_path=str(repo),
    )
    assert projects.list_registered_identifiers(conn, source="jira") == ["ZXTL"]
    assert projects.list_registered_identifiers(
        conn, source="github_issue"
    ) == ["p-acid/remotask"]
