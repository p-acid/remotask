"""Single-instance daemon lifecycle: PID file + flock + signal handlers."""
from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import signal
import threading
from pathlib import Path
from types import FrameType, TracebackType
from typing import Any


class LifecycleError(Exception):
    """Base class for lifecycle errors."""


class LockHeldError(LifecycleError):
    """Raised when another instance already holds the lock."""


class Lifecycle:
    """Context manager that owns the PID file + an exclusive flock.

    On entry: opens the PID file, acquires LOCK_EX | LOCK_NB, writes the PID,
    and installs SIGTERM/SIGINT handlers that flip a stop event.

    On exit: removes the PID file, releases the lock, and restores prior
    signal handlers.
    """

    def __init__(self, pid_path: Path) -> None:
        self.pid_path = pid_path
        self._fd: int | None = None
        self._stop_event = threading.Event()
        self._prev_handlers: dict[int, Any] = {}

    def __enter__(self) -> Lifecycle:
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.pid_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(fd)
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise LockHeldError(
                    f"daemon already running (lock held on {self.pid_path})"
                ) from e
            raise
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        os.fsync(fd)
        self._fd = fd
        self._install_signal_handlers()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._restore_signal_handlers()
        if self._fd is not None:
            with contextlib.suppress(Exception):
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            with contextlib.suppress(Exception):
                os.close(self._fd)
            self._fd = None
        with contextlib.suppress(FileNotFoundError):
            self.pid_path.unlink()

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    def wait_for_stop(self) -> None:
        """Block until SIGTERM/SIGINT is received."""
        self._stop_event.wait()

    # --- signals ----------------------------------------------------------------

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:  # noqa: ARG002
        self._stop_event.set()

    def _install_signal_handlers(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            self._prev_handlers[sig] = signal.signal(sig, self._handle_signal)

    def _restore_signal_handlers(self) -> None:
        for sig, prev in self._prev_handlers.items():
            with contextlib.suppress(Exception):
                signal.signal(sig, prev or signal.SIG_DFL)
        self._prev_handlers.clear()


def is_running(pid_path: Path) -> tuple[bool, int | None]:
    """Check whether the daemon is alive based on the PID file.

    Returns ``(True, pid)`` if the PID is alive, otherwise ``(False, None)``.
    Stale or invalid PID files are removed.
    """
    if not pid_path.exists():
        return (False, None)
    raw = pid_path.read_text().strip()
    try:
        pid = int(raw)
    except ValueError:
        with contextlib.suppress(FileNotFoundError):
            pid_path.unlink()
        return (False, None)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        with contextlib.suppress(FileNotFoundError):
            pid_path.unlink()
        return (False, None)
    except PermissionError:
        # Process exists but is owned by another user; treat as running.
        return (True, pid)
    return (True, pid)
