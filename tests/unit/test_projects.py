from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from remote_task.core import projects


def _make_git_repo(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)  # noqa: S603, S607
    return p


# --- jira_key validator ---


@pytest.mark.parametrize("key", ["ZXTL", "AB", "ZZZZZZZZZZ", "ABC"])
def test_jira_key_validator_accepts(key: str) -> None:
    projects.validate_jira_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "Z",
        "zxtl",
        "ZXTL-1",
        "ZXTL1",
        "TOOLONGKEYNAMEX",
        "",
        "AB CD",
    ],
)
def test_jira_key_validator_rejects(key: str) -> None:
    with pytest.raises(ValueError):
        projects.validate_jira_key(key)


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
    from remote_task.core import db
    repo = _make_git_repo(tmp_path / "repo")
    conn = db.connect(tmp_path / "state.db")
    projects.add(conn, "ZXTL", str(repo), "main")
    rows = projects.list_all(conn)
    assert len(rows) == 1
    assert rows[0]["jira_key"] == "ZXTL"
    assert rows[0]["base_branch"] == "main"
    assert rows[0]["enabled"] == 1


def test_add_duplicate_rejected(tmp_path: Path) -> None:
    from remote_task.core import db
    repo = _make_git_repo(tmp_path / "repo")
    conn = db.connect(tmp_path / "state.db")
    projects.add(conn, "ZXTL", str(repo), "main")
    with pytest.raises(projects.DuplicateKeyError):
        projects.add(conn, "ZXTL", str(repo), "main")


def test_remove_existing(tmp_path: Path) -> None:
    from remote_task.core import db
    repo = _make_git_repo(tmp_path / "repo")
    conn = db.connect(tmp_path / "state.db")
    projects.add(conn, "ZXTL", str(repo), "main")
    projects.remove(conn, "ZXTL")
    assert projects.list_all(conn) == []


def test_remove_unknown_raises(tmp_path: Path) -> None:
    from remote_task.core import db
    conn = db.connect(tmp_path / "state.db")
    with pytest.raises(projects.UnknownKeyError):
        projects.remove(conn, "ZXTL")
