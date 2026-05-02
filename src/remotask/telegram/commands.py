"""Curated Telegram slash-command registry — single source of truth.

The dispatcher and the ``setMyCommands`` caller both import the tuple below.
Adding or removing a command is intentionally a code change: the registered
menu can never drift from what the dispatcher actually handles, and tests pin
the shape so accidental drift is caught at PR time.

Per ``specs/005-dm-channel/data-model.md`` the curated set is now:

* ``/run``    — start a session
* ``/cancel`` — cancel an active session (canonical operator-stop, 005)
* ``/status`` — list active sessions or report current-topic state

The deprecated ``/done`` is no longer advertised but still routes inbound
through the dispatcher's deprecation-alias hook (data-model.md "Audit event
taxonomy additions"). Removed in feature 006.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CuratedCommand:
    """A single entry in the bot's setMyCommands payload."""

    name: str
    description: str
    requires_topic: bool
    requires_args: bool

    def to_bot_api_dict(self) -> dict[str, str]:
        """Serialise to the shape Telegram's setMyCommands expects."""
        return {"command": self.name, "description": self.description}


CURATED_COMMANDS: tuple[CuratedCommand, ...] = (
    CuratedCommand(
        name="run",
        description="Start a new session",
        requires_topic=False,
        requires_args=True,
    ),
    CuratedCommand(
        name="cancel",
        description="Cancel an active session",
        requires_topic=True,
        requires_args=False,
    ),
    CuratedCommand(
        name="status",
        description="Show active sessions",
        requires_topic=False,
        requires_args=False,
    ),
)


def lookup(name: str) -> CuratedCommand | None:
    """Return the curated command record for ``name`` (case-insensitive) or None."""
    lc = name.lower()
    return next((c for c in CURATED_COMMANDS if c.name == lc), None)


def to_bot_api_payload() -> list[dict[str, str]]:
    """Serialise the curated set to the JSON payload setMyCommands expects."""
    return [c.to_bot_api_dict() for c in CURATED_COMMANDS]
