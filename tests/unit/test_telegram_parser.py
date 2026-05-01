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
