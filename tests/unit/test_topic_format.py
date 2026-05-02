"""Unit tests for ``topic.format_progress`` (005 / US3 / FR-011).

Single chokepoint that applies the ``[<issue_key>]`` prefix to session-bound
message bodies.
"""
from __future__ import annotations

import pytest

from remotask.daemon import topic


class TestFormatProgress:
    def test_simple_jira_key(self) -> None:
        assert (
            topic.format_progress("ZXTL-1234", "Status: iter 1/5")
            == "[ZXTL-1234] Status: iter 1/5"
        )

    def test_synthetic_id_from_004_free_text_run(self) -> None:
        # 004 synthetic ids are also valid issue_key inputs (R3).
        synthetic = "run-2026-05-02-14-30-fix-the-cache-a3f9b1"
        assert (
            topic.format_progress(synthetic, "Status: completed")
            == f"[{synthetic}] Status: completed"
        )

    @pytest.mark.parametrize(
        "body",
        [
            "Status: iteration 1/5 @ 2026-05-02T14:32:18Z",
            "Status: final iteration 5 (natural)",
            "Status: final iteration 3 (operator_stop)",
            "Status: completed",
            "Status: canceled",
            "Status: failed",
            "Session canceled by operator.",
            "Session force-canceled by operator (grace window exceeded).",
            "Session terminated: timeout (3600s)",
            "Session failed: exit code 1",
        ],
    )
    def test_session_bound_bodies_get_prefixed(self, body: str) -> None:
        assert topic.format_progress("ZXTL-1234", body) == f"[ZXTL-1234] {body}"

    def test_does_not_strip_internal_whitespace(self) -> None:
        # Helper is a pure formatter — does not touch the body content.
        body = "Status:    iteration   1/5"
        assert topic.format_progress("ZXTL-1234", body) == f"[ZXTL-1234] {body}"

    def test_does_not_strip_leading_whitespace_from_body(self) -> None:
        # Pure concatenation — no rstrip/lstrip.
        body = "  leading spaces"
        assert topic.format_progress("KEY-1", body) == "[KEY-1]   leading spaces"
