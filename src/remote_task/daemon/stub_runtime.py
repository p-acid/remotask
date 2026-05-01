"""Phase-1 stub daemon: PID + flock + signal handler, no business logic yet."""
from __future__ import annotations

import os

import structlog

from remote_task.core import lifecycle, paths
from remote_task.core import logging as rt_logging


def run() -> None:
    """Run the daemon in the foreground.

    Acquires the PID lock, sets up logging, waits for SIGTERM/SIGINT.
    Returns when the lifecycle context exits cleanly.
    """
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    rt_logging.setup_logging(level="INFO", log_dir=paths.log_dir(), force_json=True)
    log = structlog.get_logger().bind(component="daemon")

    with lifecycle.Lifecycle(paths.pid_path()) as lc:
        log.info("daemon.started", pid=os.getpid())
        try:
            lc.wait_for_stop()
        finally:
            log.info("daemon.shutdown", pid=os.getpid())
