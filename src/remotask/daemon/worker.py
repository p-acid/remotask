"""Worker subprocess wrapper.

The worker for a session is a child subprocess of the daemon. We:

1. Create a git worktree on a fresh branch (off the project's ``base_branch``).
2. Move the session from ``starting`` → ``running``.
3. Spawn the agent subprocess (``claude-agent-sdk`` driver in production; the
   ``tests.fakes.fake_agent`` script in tests) inside that worktree.
4. Stream stdout/stderr to ``~/.local/share/remotask/logs/sessions/<id>.log``.
5. Parse ``PR_URL=<url>`` lines out of stdout to capture the draft PR.
6. On exit code 0 with a PR URL → ``pr_created``; with no PR URL → ``completed``.
7. On non-zero exit / timeout → ``failed`` with a one-line reason posted to
   the bound topic.

The per-session timeout (``cfg.agent.session_timeout_seconds``) is enforced by
``run_worker`` via ``os.killpg`` on the worker's process group: SIGTERM first,
then SIGKILL after a 10-second grace period (R9 in research.md).
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import re
import signal
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from remotask.core import config as rt_config
from remotask.core import paths
from remotask.daemon import audit, sessions, topic
from remotask.telegram.client import TelegramClient

_log = structlog.get_logger().bind(component="worker")
_PR_URL_RE = re.compile(r"^PR_URL=(\S+)\s*$")
# 003 demo worker stdout protocol — see specs/003-e2e-demo/contracts/worker-stdout-protocol.md.
_PROGRESS_RE = re.compile(r"^PROGRESS (\d+)/(\d+) (\S+)\s*$")
_FINAL_RE = re.compile(r"^FINAL (\d+) (\S+)\s*$")
_SIGTERM_GRACE = 10.0


@dataclass
class WorkerSpec:
    """All the inputs needed to spawn a worker."""

    session_id: str
    issue_key: str
    repo_path: Path
    base_branch: str
    worktree_root: Path
    argv: list[str] | None = None
    extra_env: dict[str, str] = field(default_factory=dict)
    # Per-session timeout. None means "use the runtime default" — the runtime
    # passes the value of ``cfg.agent.session_timeout_seconds``.
    timeout_seconds: float | None = None


@dataclass
class WorkerOutcome:
    exit_code: int
    pr_url: str | None
    stderr_tail: str
    timed_out: bool = False
    # 003: last ``FINAL`` line emitted by the worker, if any.
    final_marker: tuple[int, str] | None = None
    # 003: True when this terminal transition was triggered by an operator
    # stop command (graceful or forced). The dispatcher sets a flag on the
    # runtime; the daemon-side waiter reads it after the worker exits.
    operator_stopped: bool = False
    operator_stop_forced: bool = False


def _branch_for(issue_key: str) -> str:
    return f"agent/{issue_key}"


def _worktree_path_for(root: Path, issue_key: str) -> Path:
    return root.expanduser() / issue_key


async def _create_worktree(
    *, repo_path: Path, worktree_path: Path, branch: str, base_branch: str
) -> None:
    """git worktree add <path> -b <branch> <base_branch>.

    The worktree path's parent must exist; ``worktree add`` creates the leaf.
    """
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "git",
        "-C",
        str(repo_path),
        "worktree",
        "add",
        str(worktree_path),
        "-b",
        branch,
        base_branch,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"git worktree add failed (rc={proc.returncode}): "
            f"{stderr.decode(errors='replace').strip()}"
        )


async def _remove_worktree(*, repo_path: Path, worktree_path: Path) -> None:
    """Best-effort ``git worktree remove --force``; logs failures and continues."""
    cmd = [
        "git",
        "-C",
        str(repo_path),
        "worktree",
        "remove",
        "--force",
        str(worktree_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        _log.warning(
            "worktree.remove.failed",
            worktree_path=str(worktree_path),
            stderr=stderr.decode(errors="replace").strip(),
        )


def _session_log_path(session_id: str) -> Path:
    p = paths.data_dir() / "logs" / "sessions" / f"{session_id}.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class StreamResult:
    """Captured outputs from a worker subprocess run."""

    pr_url: str | None = None
    stderr_tail: str = ""
    # Last ``FINAL`` line observed (003): tuple ``(iteration, reason)`` or None.
    final_marker: tuple[int, str] | None = None


async def _stream_subprocess_output(
    proc: asyncio.subprocess.Process,
    log_path: Path,
    *,
    progress_handler: Callable[[int, int, str], Awaitable[None]] | None = None,
    final_handler: Callable[[int, str], Awaitable[None]] | None = None,
) -> StreamResult:
    """Tee stdout to ``log_path`` while harvesting marker lines and the stderr tail.

    Recognised stdout line shapes (each posted to Telegram via the optional
    handlers if provided; otherwise just logged):

    - ``PR_URL=<url>`` — captured into ``pr_url`` (002 behaviour, unchanged).
    - ``PROGRESS i/N <iso8601>`` — invokes ``progress_handler(i, N, ts)``.
    - ``FINAL <i> <reason>`` — invokes ``final_handler(i, reason)`` and
      records the marker in the result.
    - Anything else — log-only.
    """
    result = StreamResult()
    stderr_chunks: list[str] = []

    assert proc.stdout is not None and proc.stderr is not None

    async def _read_stdout() -> None:
        with log_path.open("ab") as out:
            while True:
                line = await proc.stdout.readline()  # type: ignore[union-attr]
                if not line:
                    return
                out.write(line)
                out.flush()
                text = line.decode(errors="replace").rstrip("\r\n")

                m_pr = _PR_URL_RE.match(text)
                if m_pr and result.pr_url is None:
                    result.pr_url = m_pr.group(1)
                    continue

                m_prog = _PROGRESS_RE.match(text)
                if m_prog:
                    if progress_handler is not None:
                        try:
                            await progress_handler(
                                int(m_prog.group(1)),
                                int(m_prog.group(2)),
                                m_prog.group(3),
                            )
                        except Exception as e:  # pragma: no cover — best-effort
                            _log.warning("worker.progress_handler_failed", error=str(e))
                    continue

                m_final = _FINAL_RE.match(text)
                if m_final:
                    iteration = int(m_final.group(1))
                    reason = m_final.group(2)
                    result.final_marker = (iteration, reason)
                    if final_handler is not None:
                        try:
                            await final_handler(iteration, reason)
                        except Exception as e:  # pragma: no cover — best-effort
                            _log.warning("worker.final_handler_failed", error=str(e))
                    continue
                # Unmatched lines: log-only (already written above).

    async def _read_stderr() -> None:
        with log_path.open("ab") as out:
            while True:
                line = await proc.stderr.readline()  # type: ignore[union-attr]
                if not line:
                    return
                out.write(b"[stderr] " + line)
                out.flush()
                stderr_chunks.append(line.decode(errors="replace"))

    await asyncio.gather(_read_stdout(), _read_stderr())
    result.stderr_tail = "".join(stderr_chunks)[-2000:].rstrip()
    return result


async def run_worker(
    spec: WorkerSpec,
    *,
    conn: sqlite3.Connection,
    client: TelegramClient,
    chat_id: int,
    topic_id: int,
    is_operator_stop_in_flight: Callable[[], bool] | None = None,
    on_worker_started: Callable[[int], None] | None = None,
) -> WorkerOutcome:
    """Spawn the worker, watch it to completion, and apply the resulting transitions.

    Preconditions: the session row exists in status ``starting`` and its
    ``topic_id`` is set. This function performs:

    - worktree creation
    - ``starting`` → ``running`` transition (with worktree_path / branch set)
    - subprocess spawn + output streaming
    - terminal transition (``pr_created`` / ``completed`` / ``failed``)
    - issue lock release

    Returns the captured outcome so callers (the runtime, tests) can assert on
    exit codes without scraping the DB.
    """
    log = _log.bind(session_id=spec.session_id, issue_key=spec.issue_key)
    branch = _branch_for(spec.issue_key)
    worktree_path = _worktree_path_for(spec.worktree_root, spec.issue_key)

    try:
        await _create_worktree(
            repo_path=spec.repo_path,
            worktree_path=worktree_path,
            branch=branch,
            base_branch=spec.base_branch,
        )
    except Exception as e:
        # Worktree creation failed before the worker ever started. Mark the
        # session failed and notify the topic. This is the "starting failed"
        # arrow in data-model.md.
        reason = str(e)
        sessions.transition(
            conn,
            session_id=spec.session_id,
            from_status="starting",
            to_status="failed",
            extra_columns={"error_message": reason},
        )
        sessions.release_issue_lock(conn, issue_key=spec.issue_key)
        conn.commit()
        await topic.post_to_topic(
            client,
            chat_id=chat_id,
            topic_id=topic_id,
            text=topic.TPL_SESSION_FAILED.format(reason=reason.splitlines()[0]),
        )
        return WorkerOutcome(exit_code=-1, pr_url=None, stderr_tail=reason)

    # Move starting → running and persist worktree + branch.
    sessions.transition(
        conn,
        session_id=spec.session_id,
        from_status="starting",
        to_status="running",
        extra_columns={
            "worktree_path": str(worktree_path),
            "branch": branch,
            "log_path": str(_session_log_path(spec.session_id)),
        },
    )
    await sessions.post_status_to_topic(
        client, chat_id=chat_id, topic_id=topic_id, new_status="running"
    )

    log_path = _session_log_path(spec.session_id)
    argv = spec.argv if spec.argv is not None else _default_worker_argv()
    env = os.environ.copy()
    env.update(spec.extra_env)
    env.setdefault("REMOTASK_SESSION_ID", spec.session_id)
    env.setdefault("REMOTASK_ISSUE_KEY", spec.issue_key)

    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(worktree_path),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # Process group lets the timeout watchdog kill grandchildren too (US5).
        start_new_session=True,
    )
    audit.record_event(
        conn,
        session_id=spec.session_id,
        type=audit.EV_WORKER_SPAWN,
        payload={"pid": proc.pid, "cmd": argv},
    )
    conn.execute("UPDATE sessions SET pid = ? WHERE id = ?", (proc.pid, spec.session_id))
    conn.commit()
    log.info("worker.spawned", pid=proc.pid)
    if on_worker_started is not None:
        try:
            on_worker_started(proc.pid)
        except Exception as e:  # pragma: no cover — defensive
            log.warning("worker.on_started_callback_failed", error=str(e))

    # 003 stdout streaming handlers — post PROGRESS lines verbatim to the topic
    # and FINAL lines as the marker template. Both are best-effort posts; a
    # failed sendMessage doesn't crash the worker.
    async def _on_progress(i: int, n: int, ts: str) -> None:
        await topic.post_to_topic(
            client,
            chat_id=chat_id,
            topic_id=topic_id,
            text=topic.TPL_PROGRESS.format(i=i, n=n, ts=ts),
        )

    async def _on_final(iteration: int, reason: str) -> None:
        await topic.post_to_topic(
            client,
            chat_id=chat_id,
            topic_id=topic_id,
            text=topic.TPL_FINAL.format(i=iteration, reason=reason),
        )

    timed_out = False
    timeout = spec.timeout_seconds
    stream_task = asyncio.create_task(
        _stream_subprocess_output(
            proc,
            log_path,
            progress_handler=_on_progress,
            final_handler=_on_final,
        )
    )
    try:
        if timeout is not None and timeout > 0:
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except TimeoutError:
                timed_out = True
                await _kill_worker_group(proc, log)
        else:
            await proc.wait()
    finally:
        # Drain pipes after the process exits (or is killed).
        stream_result = StreamResult()
        try:
            stream_result = await asyncio.wait_for(stream_task, timeout=5.0)
        except (TimeoutError, Exception):
            stream_task.cancel()
            with contextlib.suppress(Exception):
                await stream_task
        pr_url = stream_result.pr_url
        stderr_tail = stream_result.stderr_tail
        final_marker = stream_result.final_marker

    rc = proc.returncode if proc.returncode is not None else -1

    if timed_out:
        audit.record_event(
            conn,
            session_id=spec.session_id,
            type=audit.EV_WORKER_TIMEOUT,
            payload={"pid": proc.pid, "timeout_s": timeout},
        )
    audit.record_event(
        conn,
        session_id=spec.session_id,
        type=audit.EV_WORKER_EXIT,
        payload={"pid": proc.pid, "exit_code": rc, "signal": _signal_name(rc)},
    )
    conn.commit()

    # 003: was an operator stop in-flight when the worker exited?
    in_flight = (
        is_operator_stop_in_flight() if is_operator_stop_in_flight is not None else False
    )
    # The worker's own ``FINAL <i> <reason>`` line is the source of truth for
    # graceful operator stops — if it is `operator_stop`, we trust it even
    # when the runtime's in-flight flag was racy. Conversely, a `natural`
    # FINAL emitted *after* a stop signal means the worker beat us to the
    # natural-completion path and we should NOT classify it as operator stop.
    final_reason = final_marker[1] if final_marker is not None else None

    if final_reason == "operator_stop":
        operator_stopped = True
        operator_stop_forced = False
    elif final_reason == "natural":
        operator_stopped = False
        operator_stop_forced = False
    else:
        # No FINAL line emitted (e.g. SIGKILL'd before flush). Fall back to
        # the in-flight flag — if the dispatcher did request a stop, the kill
        # was operator-driven.
        operator_stopped = in_flight
        operator_stop_forced = in_flight and (rc != 0 or rc < 0)

    # Apply terminal transition.
    if operator_stopped and not operator_stop_forced:
        # Graceful operator stop: exit 0 + operator_stop FINAL line.
        sessions.transition(
            conn,
            session_id=spec.session_id,
            from_status="running",
            to_status="canceled",
            extra_columns={"error_message": "operator_stop"},
        )
        await topic.post_to_topic(
            client,
            chat_id=chat_id,
            topic_id=topic_id,
            text=topic.TPL_OPERATOR_STOPPED,
        )
    elif operator_stop_forced:
        # Worker had to be killed after grace expired.
        sessions.transition(
            conn,
            session_id=spec.session_id,
            from_status="running",
            to_status="canceled",
            extra_columns={"error_message": "operator_stop_forced"},
        )
        await topic.post_to_topic(
            client,
            chat_id=chat_id,
            topic_id=topic_id,
            text=topic.TPL_OPERATOR_STOPPED_FORCED,
        )
    elif timed_out:
        sessions.transition(
            conn,
            session_id=spec.session_id,
            from_status="running",
            to_status="failed",
            extra_columns={"error_message": f"timeout after {int(timeout or 0)}s"},
        )
        await topic.post_to_topic(
            client,
            chat_id=chat_id,
            topic_id=topic_id,
            text=topic.TPL_SESSION_TIMEOUT.format(seconds=int(timeout or 0)),
        )
    elif rc == 0 and pr_url:
        sessions.transition(
            conn,
            session_id=spec.session_id,
            from_status="running",
            to_status="pr_created",
            extra_columns={"pr_url": pr_url},
        )
        await sessions.post_status_to_topic(
            client, chat_id=chat_id, topic_id=topic_id, new_status="pr_created"
        )
        await topic.post_to_topic(
            client,
            chat_id=chat_id,
            topic_id=topic_id,
            text=topic.TPL_PR_CREATED.format(pr_url=pr_url),
        )
    elif rc == 0:
        sessions.transition(
            conn,
            session_id=spec.session_id,
            from_status="running",
            to_status="completed",
        )
        await sessions.post_status_to_topic(
            client, chat_id=chat_id, topic_id=topic_id, new_status="completed"
        )
    else:
        # Non-zero exit. ``stderr_tail`` carries the worker's last error line —
        # surface that as the topic-visible reason. The full stderr lives in
        # the per-session log file.
        reason = (stderr_tail.splitlines() or [f"exit code {rc}"])[-1]
        sessions.transition(
            conn,
            session_id=spec.session_id,
            from_status="running",
            to_status="failed",
            extra_columns={"error_message": reason[:500]},
        )
        await topic.post_to_topic(
            client,
            chat_id=chat_id,
            topic_id=topic_id,
            text=topic.TPL_SESSION_FAILED.format(reason=reason[:200]),
        )

    sessions.release_issue_lock(conn, issue_key=spec.issue_key)
    conn.commit()

    # Best-effort worktree cleanup; we keep the branch for inspection.
    with contextlib.suppress(Exception):
        await _remove_worktree(repo_path=spec.repo_path, worktree_path=worktree_path)

    return WorkerOutcome(
        exit_code=rc,
        pr_url=pr_url,
        stderr_tail=stderr_tail,
        timed_out=timed_out,
        final_marker=final_marker,
        operator_stopped=operator_stopped and not operator_stop_forced,
        operator_stop_forced=operator_stop_forced,
    )


async def _kill_worker_group(proc: asyncio.subprocess.Process, log: Any) -> None:
    """Send SIGTERM to the worker's process group, escalate to SIGKILL after grace."""
    if proc.returncode is not None:
        return
    pgid = _safe_pgid(proc.pid)
    if pgid is None:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pgid, signal.SIGTERM)
    log.warning("worker.timeout.sigterm", pid=proc.pid)
    try:
        await asyncio.wait_for(proc.wait(), timeout=_SIGTERM_GRACE)
        return
    except TimeoutError:
        pass
    log.warning("worker.timeout.sigkill", pid=proc.pid)
    if pgid is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pgid, signal.SIGKILL)
    with contextlib.suppress(Exception):
        await proc.wait()


def _safe_pgid(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except ProcessLookupError:
        return None


def _signal_name(rc: int) -> str | None:
    """Return the signal name when ``rc`` is a negative-encoded signal exit."""
    if rc is None or rc >= 0:
        return None
    try:
        return signal.Signals(-rc).name
    except (ValueError, AttributeError):
        return None


def _default_worker_argv() -> list[str]:
    """Argv for the production worker entrypoint.

    Points at ``remotask.agent.demo_worker`` (003) — a deterministic
    placeholder workload that streams ``PROGRESS`` / ``FINAL`` lines to
    stdout and honours ``SIGUSR1`` as a cooperative stop signal. A real
    claude-agent-sdk driver will replace this in a future feature without
    changing the daemon-side wiring.
    """
    import sys as _sys

    return [_sys.executable, "-m", "remotask.agent.demo_worker"]


def make_worktree_root(cfg: rt_config.AgentConfig) -> Path:
    """Resolve the agent's worktree root from config (expanduser-ed)."""
    return Path(cfg.worktree_root).expanduser()
