"""Unit tests for ``remotask.telegram.parser``.

The grammar is fixed by ``contracts/telegram-protocol.md``; these tests pin
each accept / reject branch.
"""
from __future__ import annotations

import pytest

from remotask.telegram.parser import extract_first_issue_key, split_prefix


class TestExtractFirstIssueKey:
    def test_extracts_simple_key(self) -> None:
        assert extract_first_issue_key("ZXTL-1234") == "ZXTL-1234"

    def test_extracts_key_embedded_in_sentence(self) -> None:
        assert extract_first_issue_key("please look at ZXTL-1234 thanks") == "ZXTL-1234"

    def test_takes_first_match_when_multiple(self) -> None:
        # First valid key wins; later ones are ignored (per protocol contract).
        assert extract_first_issue_key("ZXTL-1234 and FOO-9") == "ZXTL-1234"

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "no issue keys here",
            "lowercase-1234",  # prefix must start with uppercase
            "ab-12",  # prefix too short (need 2-10 starting with letter)
            "TOOLONGPREFIXX-1",  # 13-char prefix exceeds 10-char ceiling
            "ZXTL-",  # missing number
            "ZXTL-abc",  # number must be digits
            "ZXTL-1234567",  # number > 6 digits
        ],
    )
    def test_returns_none_for_no_match(self, text: str) -> None:
        assert extract_first_issue_key(text) is None

    def test_respects_word_boundaries(self) -> None:
        # Embedded inside a longer word — must not match.
        assert extract_first_issue_key("aZXTL-1234b") is None
        assert extract_first_issue_key("xZXTL-1234") is None
        assert extract_first_issue_key("ZXTL-1234x") is None

    def test_accepts_underscore_in_prefix(self) -> None:
        assert extract_first_issue_key("PRJ_X-7") == "PRJ_X-7"

    def test_accepts_digits_in_prefix(self) -> None:
        # Prefix may contain digits but must START with a letter; minimum
        # total prefix length is 2 (one starter + at least one extra char).
        assert extract_first_issue_key("A1-100") == "A1-100"
        assert extract_first_issue_key("AB1-100") == "AB1-100"
        # A single letter prefix is rejected — minimum prefix length is 2.
        assert extract_first_issue_key("A-100") is None

    def test_handles_punctuation_around_key(self) -> None:
        assert extract_first_issue_key("(ZXTL-1).") == "ZXTL-1"
        assert extract_first_issue_key("see: ZXTL-99!") == "ZXTL-99"


class TestSplitPrefix:
    def test_splits_simple(self) -> None:
        assert split_prefix("ZXTL-1234") == "ZXTL"

    def test_splits_underscore_prefix(self) -> None:
        assert split_prefix("PRJ_X-7") == "PRJ_X"


class TestMatchTerminationCommand:
    """003 termination grammar — single token from {done, stop, finish}."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("done", "done"),
            ("Done", "done"),
            ("DONE", "done"),
            ("stop", "stop"),
            ("Stop", "stop"),
            ("finish", "finish"),
            ("FINISH", "finish"),
            ("  done  ", "done"),  # leading/trailing whitespace tolerated
        ],
    )
    def test_accepts_canonical_tokens(self, text: str, expected: str) -> None:
        from remotask.telegram.parser import match_termination_command

        assert match_termination_command(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "done please",
            "cancel",
            "kill",
            "Stop?",
            "are we done",
            "done done",
            "FOO-1",  # an issue key, not a termination
            "STAHP",
        ],
    )
    def test_rejects_anything_else(self, text: str) -> None:
        from remotask.telegram.parser import match_termination_command

        assert match_termination_command(text) is None

    def test_handles_none_safely(self) -> None:
        from remotask.telegram.parser import match_termination_command

        assert match_termination_command("") is None


def _slash_msg(
    text: str,
    *,
    sender_id: int = 99001,
    chat_id: int = -1000000000001,
    message_id: int = 1,
    message_thread_id: int | None = None,
    cmd_length: int | None = None,
) -> dict:
    """Construct a Telegram message dict with a bot_command entity at offset 0."""
    if cmd_length is None:
        # Default: command is the first whitespace-delimited token.
        first = text.split(" ", 1)[0]
        cmd_length = len(first)
    msg = {
        "message_id": message_id,
        "from": {"id": sender_id, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat_id, "type": "supergroup"},
        "date": 1746115200,
        "text": text,
        "entities": [{"type": "bot_command", "offset": 0, "length": cmd_length}],
    }
    if message_thread_id is not None:
        msg["message_thread_id"] = message_thread_id
    return msg


class TestMatchSlashCommand:
    """004 slash-command parser."""

    def test_run_with_no_args(self) -> None:
        from remotask.telegram.parser import match_slash_command

        m = match_slash_command(_slash_msg("/run"))
        assert m is not None
        assert m.name == "run"
        assert m.args_text == ""

    def test_run_with_args(self) -> None:
        from remotask.telegram.parser import match_slash_command

        m = match_slash_command(_slash_msg("/run ZXTL-1234 add tests"))
        assert m is not None
        assert m.name == "run"
        assert m.args_text == "ZXTL-1234 add tests"

    def test_done_in_topic(self) -> None:
        from remotask.telegram.parser import match_slash_command

        m = match_slash_command(_slash_msg("/done", message_thread_id=42))
        assert m is not None
        assert m.name == "done"
        assert m.message_thread_id == 42

    def test_strips_at_botname_suffix(self) -> None:
        from remotask.telegram.parser import match_slash_command

        msg = _slash_msg("/run@curious_claude_notification_bot ZXTL-1234")
        # Recompute the entity length to include the @<botname> portion.
        msg["entities"][0]["length"] = len("/run@curious_claude_notification_bot")
        m = match_slash_command(
            msg, bot_username="curious_claude_notification_bot"
        )
        assert m is not None
        assert m.name == "run"
        assert m.args_text == "ZXTL-1234"

    def test_rejects_other_bot_suffix(self) -> None:
        from remotask.telegram.parser import match_slash_command

        msg = _slash_msg("/run@some_other_bot ZXTL-1234")
        msg["entities"][0]["length"] = len("/run@some_other_bot")
        m = match_slash_command(msg, bot_username="curious_claude_notification_bot")
        assert m is None

    def test_no_entity_returns_none(self) -> None:
        from remotask.telegram.parser import match_slash_command

        msg = _slash_msg("/run ZXTL-1234")
        msg["entities"] = []
        assert match_slash_command(msg) is None

    def test_entity_at_non_zero_offset_returns_none(self) -> None:
        from remotask.telegram.parser import match_slash_command

        msg = _slash_msg("/run ZXTL-1234")
        msg["entities"] = [{"type": "bot_command", "offset": 4, "length": 5}]
        assert match_slash_command(msg) is None

    def test_strips_leading_whitespace_from_args(self) -> None:
        from remotask.telegram.parser import match_slash_command

        m = match_slash_command(_slash_msg("/run    ZXTL-1234"))
        assert m is not None
        assert m.args_text == "ZXTL-1234"

    def test_case_insensitive_command_name(self) -> None:
        from remotask.telegram.parser import match_slash_command

        m = match_slash_command(_slash_msg("/RUN args"))
        assert m is not None
        assert m.name == "run"


class TestSlashCancel:
    """005: /cancel canonical operator-stop slash command."""

    def test_cancel_in_topic_no_args(self) -> None:
        from remotask.telegram.parser import match_slash_command

        m = match_slash_command(_slash_msg("/cancel", message_thread_id=42))
        assert m is not None
        assert m.name == "cancel"
        assert m.args_text == ""
        assert m.message_thread_id == 42

    def test_cancel_in_main_chat(self) -> None:
        from remotask.telegram.parser import match_slash_command

        m = match_slash_command(_slash_msg("/cancel"))
        assert m is not None
        assert m.name == "cancel"
        assert m.message_thread_id is None

    def test_cancel_uppercase_canonicalises_to_lower(self) -> None:
        from remotask.telegram.parser import match_slash_command

        m = match_slash_command(_slash_msg("/CANCEL"))
        assert m is not None
        assert m.name == "cancel"

    def test_cancel_at_botname(self) -> None:
        from remotask.telegram.parser import match_slash_command

        msg = _slash_msg("/cancel@curious_claude_notification_bot")
        msg["entities"][0]["length"] = len("/cancel@curious_claude_notification_bot")
        m = match_slash_command(msg, bot_username="curious_claude_notification_bot")
        assert m is not None
        assert m.name == "cancel"

    def test_cancel_with_trailing_text_parses_args(self) -> None:
        # /cancel grammar in 005 ignores args at dispatcher level (FR-002),
        # but the parser still extracts them — the dispatcher decides what
        # to do with non-empty args (treats as casual chat / out-of-scope).
        from remotask.telegram.parser import match_slash_command

        m = match_slash_command(_slash_msg("/cancel something"))
        assert m is not None
        assert m.name == "cancel"
        assert m.args_text == "something"
