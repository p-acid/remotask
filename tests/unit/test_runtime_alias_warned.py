"""Unit tests for the 005 alias-deprecation idempotency state on Runtime.

The set lives at ``Runtime._alias_deprecation_warned`` and is exposed via:

- ``has_alias_deprecation_warned(alias_token, session_id) -> bool``
- ``record_alias_deprecation_warned(alias_token, session_id) -> None``
- ``clear_alias_deprecation_for_session(session_id) -> None``

The dispatcher consults / updates these via the ``DispatchContext`` callbacks
populated in ``Runtime._on_message``. This unit test exercises the
``Runtime`` API directly so we don't need to spin up the listener thread.
"""
from __future__ import annotations

from remotask.core import config as rt_config
from remotask.daemon.runtime import Runtime


def _make_runtime() -> Runtime:
    cfg = rt_config.default_schema()
    cfg.telegram.bot_token = "123456:" + "a" * 32
    cfg.telegram.group_chat_id = -100123
    cfg.telegram.allowed_user_ids = [99001]
    return Runtime(cfg=cfg)


class TestAliasDeprecationSet:
    def test_empty_on_init(self) -> None:
        rt = _make_runtime()
        assert rt.has_alias_deprecation_warned("/done", "S1") is False
        assert rt.has_alias_deprecation_warned("done", "S1") is False
        assert rt.has_alias_deprecation_warned("stop", "S1") is False

    def test_record_marks_pair_warned(self) -> None:
        rt = _make_runtime()
        rt.record_alias_deprecation_warned("/done", "S1")
        assert rt.has_alias_deprecation_warned("/done", "S1") is True

    def test_record_is_per_session(self) -> None:
        rt = _make_runtime()
        rt.record_alias_deprecation_warned("/done", "S1")
        # A different session is unaffected.
        assert rt.has_alias_deprecation_warned("/done", "S2") is False

    def test_record_is_per_alias_token(self) -> None:
        rt = _make_runtime()
        rt.record_alias_deprecation_warned("/done", "S1")
        # A different alias on the same session is independent.
        assert rt.has_alias_deprecation_warned("done", "S1") is False
        assert rt.has_alias_deprecation_warned("stop", "S1") is False

    def test_record_idempotent(self) -> None:
        rt = _make_runtime()
        rt.record_alias_deprecation_warned("/done", "S1")
        rt.record_alias_deprecation_warned("/done", "S1")  # no error
        assert rt.has_alias_deprecation_warned("/done", "S1") is True

    def test_clear_removes_only_target_session(self) -> None:
        rt = _make_runtime()
        rt.record_alias_deprecation_warned("/done", "S1")
        rt.record_alias_deprecation_warned("stop", "S1")
        rt.record_alias_deprecation_warned("/done", "S2")

        rt.clear_alias_deprecation_for_session("S1")

        assert rt.has_alias_deprecation_warned("/done", "S1") is False
        assert rt.has_alias_deprecation_warned("stop", "S1") is False
        # S2 entries survive.
        assert rt.has_alias_deprecation_warned("/done", "S2") is True

    def test_clear_unknown_session_is_noop(self) -> None:
        rt = _make_runtime()
        rt.record_alias_deprecation_warned("/done", "S1")
        rt.clear_alias_deprecation_for_session("S_doesntexist")
        assert rt.has_alias_deprecation_warned("/done", "S1") is True
