"""FR-018: 007 must NOT change the curated setMyCommands set.

The set is `{run, cancel, status}` (locked at 005/006). 007 introduces no
new Telegram slash command; ``/work-start`` and ``/work-done`` are
agent-side skills the driver invokes — they MUST NOT be exposed in
BotFather's UI.
"""
from __future__ import annotations

from remotask.telegram import commands as rt_commands


def test_curated_command_set_is_run_cancel_status() -> None:
    names = {c.name for c in rt_commands.CURATED_COMMANDS}
    assert names == {"run", "cancel", "status"}


def test_work_start_and_work_done_are_not_telegram_commands() -> None:
    names = {c.name for c in rt_commands.CURATED_COMMANDS}
    assert "work-start" not in names
    assert "work_start" not in names
    assert "workstart" not in names
    assert "work-done" not in names
    assert "work_done" not in names
    assert "workdone" not in names


def test_curated_payload_serialises_to_three_entries() -> None:
    payload = rt_commands.to_bot_api_payload()
    assert isinstance(payload, list)
    assert len(payload) == 3
    cmd_names = {entry["command"] for entry in payload}
    assert cmd_names == {"run", "cancel", "status"}
