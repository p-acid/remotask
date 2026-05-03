from __future__ import annotations

import subprocess
from pathlib import Path


def _git_init(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)  # noqa: S603, S607
    return p


def test_list_empty(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    result = cli_runner("projects", "list")
    assert "no projects" in result.stdout.lower()


def test_add_creates_row(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    repo = _git_init(tmp_xdg_env / "repo")
    cli_runner("projects", "add", "ZXTL", str(repo))
    result = cli_runner("projects", "list")
    assert "ZXTL" in result.stdout
    assert str(repo) in result.stdout


def test_add_invalid_key_rejected(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    repo = _git_init(tmp_xdg_env / "repo")
    result = cli_runner("projects", "add", "zxtl-1", str(repo), expect_exit=None)
    assert result.returncode == 1
    msg = result.stdout + result.stderr
    assert "identifier" in msg.lower() or "key" in msg.lower() or "format" in msg.lower()


def test_add_nonexistent_path_rejected(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    result = cli_runner(
        "projects", "add", "ZXTL", str(tmp_xdg_env / "nope"), expect_exit=None
    )
    assert result.returncode == 1


def test_add_non_git_path_rejected(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    plain = tmp_xdg_env / "plain"
    plain.mkdir()
    result = cli_runner("projects", "add", "ZXTL", str(plain), expect_exit=None)
    assert result.returncode == 1
    msg = result.stdout + result.stderr
    assert "git" in msg.lower()


def test_add_duplicate_rejected(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    repo = _git_init(tmp_xdg_env / "repo")
    cli_runner("projects", "add", "ZXTL", str(repo))
    result = cli_runner("projects", "add", "ZXTL", str(repo), expect_exit=None)
    assert result.returncode == 1
    msg = result.stdout + result.stderr
    assert "exist" in msg.lower() or "duplicate" in msg.lower()


def test_add_with_branch_option(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    repo = _git_init(tmp_xdg_env / "repo")
    cli_runner("projects", "add", "ZXTL", str(repo), "--branch", "develop")
    result = cli_runner("projects", "list")
    assert "develop" in result.stdout


def test_remove_deletes_row(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    repo = _git_init(tmp_xdg_env / "repo")
    cli_runner("projects", "add", "ZXTL", str(repo))
    cli_runner("projects", "remove", "ZXTL")
    result = cli_runner("projects", "list")
    assert "ZXTL" not in result.stdout


def test_remove_unknown_key_error(cli_runner, tmp_xdg_env: Path) -> None:
    cli_runner("init")
    result = cli_runner("projects", "remove", "ZXTL", expect_exit=None)
    assert result.returncode == 1


def test_add_github_issue_identifier(cli_runner, tmp_xdg_env: Path) -> None:
    """008/T-A4 — CLI GH mode: ``projects add p-acid/remotask <path>``
    with ``agent.task_source = "github_issue"`` registers under the
    ``github_issue`` source. Mirror of the Jira-mode add tests above.
    """
    cli_runner("init")
    cli_runner("config", "set", "agent.task_source", "github_issue")
    repo = _git_init(tmp_xdg_env / "repo")
    cli_runner("projects", "add", "p-acid/remotask", str(repo))
    result = cli_runner("projects", "list")
    assert "github_issue" in result.stdout
    assert "p-acid/remotask" in result.stdout


def test_add_github_mode_rejects_jira_shape(
    cli_runner, tmp_xdg_env: Path
) -> None:
    """B9 policy — active provider mismatch is rejected at add time."""
    cli_runner("init")
    cli_runner("config", "set", "agent.task_source", "github_issue")
    repo = _git_init(tmp_xdg_env / "repo")
    result = cli_runner(
        "projects", "add", "ZXTL", str(repo), expect_exit=None
    )
    assert result.returncode == 1
    msg = (result.stdout + result.stderr).lower()
    assert "github" in msg or "owner/repo" in msg or "identifier" in msg


def test_list_shows_columns(cli_runner: object, tmp_xdg_env: Path) -> None:  # type: ignore[no-untyped-def]
    """008/T5: list output uses ``source`` + ``identifier`` columns."""
    cli_runner("init")
    repo = _git_init(tmp_xdg_env / "repo")
    cli_runner("projects", "add", "ZXTL", str(repo))
    result = cli_runner("projects", "list")
    out = result.stdout.lower()
    for col in ("source", "identifier", "repo_path", "base_branch", "enabled"):
        assert col in out, f"column {col} missing from list output"
