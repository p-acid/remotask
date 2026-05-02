"""Unit tests for the curated slash-command registry.

Pins the shape so accidental drift (a command appearing in the menu but not in
the dispatcher, or vice versa) is caught at PR time.
"""
from __future__ import annotations

from remotask.telegram.commands import (
    CURATED_COMMANDS,
    lookup,
    to_bot_api_payload,
)


class TestRegistryShape:
    def test_three_commands_present(self) -> None:
        assert len(CURATED_COMMANDS) == 3

    def test_canonical_names(self) -> None:
        # 005: registry switches from {run, done, status} to {run, cancel, status}.
        # /done is no longer advertised but still routed inbound (deprecation alias).
        assert {c.name for c in CURATED_COMMANDS} == {"run", "cancel", "status"}

    def test_done_is_not_advertised_in_registry(self) -> None:
        # 005 FR-004 / FR-011: /done MUST NOT appear in the curated set.
        assert "done" not in {c.name for c in CURATED_COMMANDS}

    def test_names_have_no_leading_slash(self) -> None:
        for c in CURATED_COMMANDS:
            assert not c.name.startswith("/"), c

    def test_descriptions_within_telegram_limit(self) -> None:
        for c in CURATED_COMMANDS:
            assert 1 <= len(c.description) <= 256, c

    def test_requires_topic_only_for_cancel(self) -> None:
        # 005: /cancel inherits /done's requires_topic=True (operator-stop is
        # only meaningful inside a session topic).
        topic_only = {c.name for c in CURATED_COMMANDS if c.requires_topic}
        assert topic_only == {"cancel"}

    def test_requires_args_only_for_run(self) -> None:
        args_required = {c.name for c in CURATED_COMMANDS if c.requires_args}
        assert args_required == {"run"}

    def test_cancel_description_says_cancel(self) -> None:
        # Sanity check the operator-visible description.
        c = next(c for c in CURATED_COMMANDS if c.name == "cancel")
        assert "ancel" in c.description  # "Cancel" or "cancel"


class TestLookup:
    def test_lookup_by_canonical_name(self) -> None:
        c = lookup("run")
        assert c is not None
        assert c.name == "run"

    def test_lookup_is_case_insensitive(self) -> None:
        assert lookup("RUN") is not None
        assert lookup("Cancel") is not None

    def test_lookup_done_returns_none_post_005(self) -> None:
        # 005: /done is NOT in the curated registry. Inbound /done is still
        # handled by the dispatcher (deprecation alias path) — that lookup
        # is hard-coded in dispatcher._handle_slash_command, not via this
        # registry function.
        assert lookup("done") is None

    def test_lookup_unknown_returns_none(self) -> None:
        assert lookup("foo") is None
        assert lookup("") is None


class TestBotApiPayload:
    def test_payload_shape_matches_telegram_contract(self) -> None:
        payload = to_bot_api_payload()
        assert isinstance(payload, list)
        assert len(payload) == 3
        for entry in payload:
            assert set(entry.keys()) == {"command", "description"}
            assert isinstance(entry["command"], str)
            assert isinstance(entry["description"], str)

    def test_payload_preserves_registry_order(self) -> None:
        payload = to_bot_api_payload()
        registry_names = [c.name for c in CURATED_COMMANDS]
        payload_names = [e["command"] for e in payload]
        assert payload_names == registry_names


class TestFrozenness:
    def test_curated_commands_is_a_tuple(self) -> None:
        assert isinstance(CURATED_COMMANDS, tuple)

    def test_records_are_frozen(self) -> None:
        import dataclasses

        for c in CURATED_COMMANDS:
            assert dataclasses.is_dataclass(c)
            with __import__("pytest").raises(dataclasses.FrozenInstanceError):
                c.name = "mutated"  # type: ignore[misc]


class TestNoOverlapWithLegacyCommands:
    """The slash-command registry must not collide with 003 plain-text tokens."""

    def test_done_synonyms_not_in_registry(self) -> None:
        # 005: the canonical command is /cancel; the plain-text 003 synonyms
        # are done/stop/finish and they must NOT also be slash commands
        # (otherwise the menu would show /stop and /finish that we don't
        # actually handle).
        legacy_synonyms = {"done", "stop", "finish"}
        registry_names = {c.name for c in CURATED_COMMANDS}
        assert registry_names.isdisjoint(legacy_synonyms)
