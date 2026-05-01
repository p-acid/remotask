"""Subprocess coverage hook.

Activated when ``COVERAGE_PROCESS_START`` is in the environment so coverage
captures the CLI subprocess invoked by integration tests via ``cli_runner``.
"""
from __future__ import annotations

import os

if os.environ.get("COVERAGE_PROCESS_START"):
    try:
        import coverage  # type: ignore[import-untyped]

        coverage.process_startup()
    except Exception:  # pragma: no cover
        pass
