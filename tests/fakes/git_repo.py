"""Helpers for creating throwaway git repositories in tests.

The worker needs a real ``git`` binary (it shells out to ``git worktree add``),
so we set up a tiny repo on disk with a single commit. The repo can then back
a ``projects`` row in the test DB.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def make_repo(parent: Path, *, name: str = "fakerepo") -> Path:
    """Create a git repo under ``parent / name`` with one commit and return its path."""
    repo = parent / name
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "tester@example.com")
    _git(repo, "config", "user.name", "Tester")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("# fake\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)
