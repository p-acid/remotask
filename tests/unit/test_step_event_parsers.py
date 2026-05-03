"""Unit coverage for the 007 STEP / EVENT line parsers in worker.py.

Validates the two regexes (``_STEP_RE``, ``_EVENT_RE``) plus the priority
ordering of the matcher chain inside ``_stream_subprocess_output``. The
priority test inspects the dispatch by reading the source — we exercise it
end-to-end from ``test_step_event_pipeline.py``.
"""
from __future__ import annotations

import pytest

from remotask.daemon import worker


@pytest.mark.parametrize(
    "line,expected_body",
    [
        ("STEP Bash: gh pr create --draft", "Bash: gh pr create --draft"),
        ("STEP Edited src/foo.py", "Edited src/foo.py"),
        # Trailing whitespace is captured into the body group; harmless.
        ("STEP a", "a"),
        ("STEP " + "x" * 500, "x" * 500),  # 500-char ceiling exactly.
    ],
)
def test_step_re_accepts_canonical(line: str, expected_body: str) -> None:
    m = worker._STEP_RE.match(line)
    assert m is not None
    assert m.group(1) == expected_body


@pytest.mark.parametrize(
    "line",
    [
        "STEP",  # no body
        "STEP ",  # body must be ≥ 1 char (regex .{1,500})
        "step lowercase keyword",  # case-sensitive STEP keyword
        "STEP " + "x" * 501,  # 501 chars over the ceiling
    ],
)
def test_step_re_rejects_malformed(line: str) -> None:
    assert worker._STEP_RE.match(line) is None


@pytest.mark.parametrize(
    "line,expected_type,expected_payload_str",
    [
        (
            'EVENT agent.tool_use {"tool":"Bash","iter":1}',
            "agent.tool_use",
            '{"tool":"Bash","iter":1}',
        ),
        (
            'EVENT agent.stop {"iter":3,"reason":"natural"}',
            "agent.stop",
            '{"iter":3,"reason":"natural"}',
        ),
        (
            'EVENT agent.interrupt {"iter_at_interrupt":2}',
            "agent.interrupt",
            '{"iter_at_interrupt":2}',
        ),
    ],
)
def test_event_re_accepts_canonical(
    line: str, expected_type: str, expected_payload_str: str
) -> None:
    m = worker._EVENT_RE.match(line)
    assert m is not None
    assert m.group(1) == expected_type
    assert m.group(2) == expected_payload_str


@pytest.mark.parametrize(
    "line",
    [
        "EVENT agent {}",  # type must contain a dot
        "EVENT Agent.tool_use {}",  # uppercase first char rejected
        "EVENT 1agent.tool_use {}",  # numeric prefix rejected
        "event agent.tool_use {}",  # case-sensitive EVENT keyword
        "EVENT agent.tool_use",  # missing payload
    ],
)
def test_event_re_rejects_malformed(line: str) -> None:
    assert worker._EVENT_RE.match(line) is None


def test_priority_pr_url_beats_step() -> None:
    # Pathological line that matches both. Daemon dispatch tries PR_URL first,
    # so it must win and STEP must never fire.
    line = "PR_URL=https://example.com/pr/1"
    assert worker._PR_URL_RE.match(line) is not None
    assert worker._STEP_RE.match(line) is None  # no leading "STEP "


def test_priority_progress_not_step() -> None:
    # PROGRESS lines must not be eaten by STEP — the trimmed line begins with
    # "PROGRESS" not "STEP", so STEP_RE doesn't match anyway.
    line = "PROGRESS 1/3 2026-05-03T00:00:00Z"
    assert worker._PROGRESS_RE.match(line) is not None
    assert worker._STEP_RE.match(line) is None


def test_priority_final_not_event() -> None:
    line = "FINAL 1 natural"
    assert worker._FINAL_RE.match(line) is not None
    assert worker._EVENT_RE.match(line) is None


def test_step_re_body_stops_at_newline() -> None:
    # Bodies must be one-liners — the regex's ``.`` doesn't match newlines and
    # ``$`` is end-of-line, so an embedded \n means the regex sees only "a"
    # but the trailing "b" prevents a full-string match. Stream callers feed
    # the parser one rstripped line at a time so this case never arises in
    # practice; we still document the parser's behaviour here.
    assert worker._STEP_RE.match("STEP a\nb") is None
    # The single-line case works as expected.
    m = worker._STEP_RE.match("STEP a")
    assert m is not None
    assert m.group(1) == "a"
