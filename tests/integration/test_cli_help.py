from __future__ import annotations

import re
import time

import pytest

SUBCOMMANDS = ["init", "install", "uninstall", "daemon", "config", "login", "sessions", "projects"]
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def test_version_prints_string(cli_runner) -> None:
    result = cli_runner("--version")
    assert result.returncode == 0
    out = result.stdout.strip().splitlines()
    assert len(out) == 1
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[-+].*)?", out[0])


def test_help_lists_all_subcommands(cli_runner) -> None:
    result = cli_runner("--help")
    assert result.returncode == 0
    for sub in SUBCOMMANDS:
        assert sub in result.stdout, f"subcommand {sub!r} missing from --help output"


@pytest.mark.parametrize("sub", SUBCOMMANDS)
def test_each_subcommand_help(cli_runner, sub: str) -> None:
    result = cli_runner(sub, "--help")
    assert result.returncode == 0
    assert result.stdout.strip(), f"--help for {sub!r} produced empty stdout"


def test_unknown_command_exits_nonzero(cli_runner) -> None:
    result = cli_runner("definitely-not-a-command", expect_exit=None)
    assert result.returncode != 0


def test_help_under_1s(cli_runner) -> None:
    """SC-002: --help responds within 1 second."""
    start = time.perf_counter()
    result = cli_runner("--help")
    elapsed = time.perf_counter() - start
    assert result.returncode == 0
    assert elapsed < 1.0, f"--help took {elapsed:.3f}s (>= 1.0s)"


def test_no_color_in_pipe(cli_runner) -> None:
    """SC-010 / FR-005: stdout has no ANSI escapes when piped."""
    result = cli_runner("--help", extra_env={"NO_COLOR": "1"})
    assert result.returncode == 0
    assert not ANSI_RE.search(result.stdout), (
        f"unexpected ANSI escapes in stdout when NO_COLOR=1:\n{result.stdout!r}"
    )
