from __future__ import annotations

import re

from remotask.core import secrets as rt_secrets


def test_generate_token_minimum_length() -> None:
    t = rt_secrets.generate_token()
    assert len(t) >= 32


def test_generate_token_unique() -> None:
    a = rt_secrets.generate_token()
    b = rt_secrets.generate_token()
    assert a != b


def test_generate_token_urlsafe_charset() -> None:
    t = rt_secrets.generate_token()
    assert re.fullmatch(r"[A-Za-z0-9_\-]+", t)


def test_mask_long_string() -> None:
    masked = rt_secrets.mask("1234567890abcdef")
    assert masked == "****cdef"


def test_mask_short_string_fully_hidden() -> None:
    assert rt_secrets.mask("abc") == "****"
    assert rt_secrets.mask("") == "****"


def test_mask_none_returns_placeholder() -> None:
    assert rt_secrets.mask(None) == "****"


def test_is_secret_key_known() -> None:
    assert rt_secrets.is_secret_key("daemon.auth_token")
    assert rt_secrets.is_secret_key("telegram.bot_token")


def test_is_secret_key_unknown() -> None:
    assert not rt_secrets.is_secret_key("agent.max_concurrent")
    assert not rt_secrets.is_secret_key("foo.bar")
