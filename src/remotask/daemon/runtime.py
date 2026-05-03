"""Daemon runtime — replaces ``daemon.stub_runtime`` from 001-cli-bootstrap.

Layout:

- The **main thread** holds the PID lock (``Lifecycle``) and waits for
  SIGTERM/SIGINT, just like the stub. This keeps signal handling on the main
  thread, which macOS requires for reliable delivery.
- A **dedicated listener thread** owns an asyncio event loop. The loop hosts:

  * one ``Listener`` task (long-poll on Telegram),
  * any number of ``worker.run_worker`` tasks spawned by the dispatcher.

- All DB / Telegram I/O happens in the listener thread; the main thread only
  signals shutdown.

Shutdown sequence:

1. Main thread receives SIGTERM, sets ``Lifecycle.stop_event``.
2. Main thread calls ``Runtime.stop()``, which:
   - asks the listener to stop accepting new updates (``Listener.stop()``)
   - calls ``loop.call_soon_threadsafe`` to set an internal "drain" event
   - waits up to ``shutdown_timeout`` for in-flight workers to finish
   - cancels what's left and tears the loop down.

US3 (T035) will add config-precondition validation here. US4 (T039–T040) wires
SIGUSR1 / listener.cmd handling. US5 wires daemon-restart recovery. The shape
below is sized for those additions without further redesign.
"""
from __future__ import annotations

import asyncio
import signal
import sqlite3
import threading
from collections.abc import Coroutine
from typing import Any

import structlog

from remotask.core import config as rt_config
from remotask.core import db as core_db
from remotask.core import paths
from remotask.daemon import dispatcher as rt_dispatcher
from remotask.daemon import listener_cmd as rt_listener_cmd
from remotask.daemon.listener import Listener
from remotask.daemon.listener_state import HeartbeatWriter
from remotask.telegram import commands as rt_commands
from remotask.telegram.client import TelegramAPIError, TelegramClient

_log = structlog.get_logger().bind(component="runtime")

_DEFAULT_SHUTDOWN_TIMEOUT = 30.0


class ListenerPreconditionError(Exception):
    """Raised when the listener cannot start because config is missing/invalid.

    Surfaces the *field name* that failed (for ``remotask telegram start`` to
    print as exit-5 message text), but **never** echoes the field's value —
    that is critical for ``bot_token`` so a misconfigured token isn't logged.
    """

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"telegram listener precondition failed: {field}: {reason}")
        self.field = field
        self.reason = reason


def validate_listener_preconditions(
    cfg: rt_config.ConfigSchema, *, config_path: paths.Path | None = None
) -> None:
    """Enforce the FR-003 fail-closed posture before starting the listener.

    Raises :class:`ListenerPreconditionError` on the first problem found.
    Caller is expected to translate this into the CLI-contract exit code 5.
    """
    import re

    if not cfg.telegram.bot_token:
        raise ListenerPreconditionError("telegram.bot_token", "value is empty")
    # Same regex as core/config.py — defence in depth.
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{30,}", cfg.telegram.bot_token):
        raise ListenerPreconditionError(
            "telegram.bot_token", "does not match Telegram bot-token format"
        )
    if cfg.telegram.group_chat_id == 0:
        raise ListenerPreconditionError(
            "telegram.group_chat_id", "value is 0 (unset)"
        )
    if not cfg.telegram.allowed_user_ids:
        raise ListenerPreconditionError(
            "telegram.allowed_user_ids", "whitelist is empty (fail-closed)"
        )
    # File-mode 0600 enforcement on the on-disk config — only when the caller
    # tells us where the config lives. The default daemon path is checked by
    # ``run()`` below. Tests pass an explicit path or omit this check.
    if config_path is not None and config_path.exists():
        mode = config_path.stat().st_mode & 0o777
        if mode & 0o077:
            raise ListenerPreconditionError(
                "config_path",
                f"file mode {oct(mode)} is looser than 0600",
            )


async def recover_non_terminal_sessions(
    *,
    conn: sqlite3.Connection,
    client: TelegramClient,
    chat_id: int,
) -> int:
    """Force-fail any session left non-terminal by a previous daemon run.

    Returns the number of rows recovered. For each row:

    1. status → ``failed``, ``error_message='daemon_restart'``, ``ended_at=now``
    2. insert ``daemon_restart`` event in ``session_events``
    3. release the per-issue lock
    4. best-effort post ``Session terminated by daemon restart.`` to the topic

    A failure to post in step (4) is logged but never blocks startup.
    """
    from remotask.daemon import audit, sessions, topic

    rows = core_db.iter_non_terminal_sessions(conn)
    if not rows:
        return 0
    _log.info("runtime.recovery.start", count=len(rows))
    for row in rows:
        sid = row["id"]
        prior = row["status"]
        try:
            sessions.transition(
                conn,
                session_id=sid,
                from_status=prior,
                to_status="failed",
                extra_columns={"error_message": "daemon_restart"},
            )
        except RuntimeError:
            # Status changed under us (race with another runtime); skip.
            continue
        audit.record_event(
            conn,
            session_id=sid,
            type=audit.EV_DAEMON_RESTART,
            payload={"prior_status": prior},
        )
        # The issue_key column is non-null per V0001; safe to release.
        sessions.release_issue_lock(conn, issue_key=row["issue_key"])
        conn.commit()
        if row["topic_id"] is not None:
            try:
                await topic.post_to_topic(
                    client,
                    chat_id=chat_id,
                    topic_id=int(row["topic_id"]),
                    text=topic.TPL_DAEMON_RESTART_CLEANUP,
                )
            except Exception as e:  # pragma: no cover — best-effort
                _log.warning("runtime.recovery.topic_post_failed", error=str(e))
    return len(rows)


class Runtime:
    """Owns the listener thread, the asyncio loop, and every worker task."""

    def __init__(
        self,
        *,
        cfg: rt_config.ConfigSchema,
        worker_argv: list[str] | None = None,
        worker_env: dict[str, str] | None = None,
        shutdown_timeout: float = _DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> None:
        self._cfg = cfg
        self._worker_argv = worker_argv
        self._worker_env = worker_env
        self._shutdown_timeout = shutdown_timeout

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._listener: Listener | None = None
        self._client: TelegramClient | None = None
        self._conn: sqlite3.Connection | None = None
        self._worker_tasks: set[asyncio.Task[Any]] = set()
        self._ready = threading.Event()
        # Last applied listener.cmd seq — guards against re-applying a stale
        # command file when the daemon has already processed it.
        self._last_cmd_seq = 0
        # 003: session ids for which an operator stop is currently in flight.
        # The dispatcher's termination branch adds; the worker exit handler
        # checks (and the worker.run_worker post-exit logic uses to decide
        # between operator_stop and timeout / failed transitions). Both
        # mutators run on the listener thread's event loop, so a plain set
        # is sufficient — no lock needed.
        self._operator_stop_in_flight: set[str] = set()
        # 003: per-session worker-pid index, populated by the dispatcher when
        # it spawns a worker so the termination branch can ``os.kill`` it.
        self._worker_pid_by_session: dict[str, int] = {}
        # 004: cached bot username from getMe; used to strip @<botname> suffix
        # on inbound slash commands. None until the runtime calls getMe.
        self._bot_username: str | None = None
        # 004: heartbeat writer cached so the setMyCommands result can flush
        # immediately into listener.state.
        self._heartbeat_writer: HeartbeatWriter | None = None
        self._listener_state_obj = None  # filled by _async_main

    # ---- lifecycle (main thread) ---------------------------------------------

    def start(self) -> None:
        """Spin up the listener thread and block until it's ready."""
        if self._thread is not None:
            raise RuntimeError("runtime already started")
        self._thread = threading.Thread(
            target=self._thread_main, name="remotask-listener", daemon=False
        )
        self._thread.start()
        # Wait for the loop to publish itself before returning.
        self._ready.wait(timeout=10.0)

    def stop(self) -> None:
        """Drain in-flight workers (best effort) and tear the loop down."""
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._initiate_shutdown)
        if self._thread is not None:
            self._thread.join(timeout=self._shutdown_timeout + 5.0)

    # ---- SIGUSR1 handler (main thread) ---------------------------------------

    def install_sigusr1_handler(self) -> None:
        """Install a SIGUSR1 handler that processes ``listener.cmd``.

        This must be called from the **main thread** (signal.signal needs it),
        which is where ``run()`` runs. The handler reads the command file and
        bridges into the listener thread via ``loop.call_soon_threadsafe``.
        """
        signal.signal(signal.SIGUSR1, self._on_sigusr1)

    def _on_sigusr1(self, signum: int, frame: Any) -> None:  # noqa: ARG002
        cmd = rt_listener_cmd.read()
        if cmd is None or cmd.seq <= self._last_cmd_seq:
            return
        self._last_cmd_seq = cmd.seq
        loop = self._loop
        if loop is None or self._listener is None:
            return
        if cmd.command == "start":
            loop.call_soon_threadsafe(self._listener.resume)
        elif cmd.command == "stop":
            loop.call_soon_threadsafe(self._listener.pause)

    # ---- listener-thread entry point -----------------------------------------

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._async_main())
        finally:
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)

    async def _async_main(self) -> None:
        # DB conn lives on the listener thread.
        conn = core_db.connect(paths.db_path())
        self._conn = conn

        client = TelegramClient(self._cfg.telegram.bot_token)
        self._client = client

        try:
            # Daemon-restart recovery (R10 / FR-014). Any session left in a
            # non-terminal state from a previous run is forcibly transitioned
            # to ``failed`` with reason ``daemon_restart`` and a notice posted
            # to its bound topic (best-effort).
            await recover_non_terminal_sessions(
                conn=conn, client=client, chat_id=self._cfg.telegram.group_chat_id
            )

            # 004: fetch the bot's own metadata so the dispatcher can strip
            # ``@<botname>`` suffixes from slash commands. Best-effort — a
            # transient failure here only weakens suffix matching, not
            # dispatch correctness.
            try:
                me = await client.get_me()
                self._bot_username = (me or {}).get("username")
            except TelegramAPIError as e:
                _log.warning("runtime.get_me_failed", error=str(e))

            heartbeat = HeartbeatWriter()
            self._heartbeat_writer = heartbeat

            listener = Listener(
                client=client,
                chat_id=self._cfg.telegram.group_chat_id,
                on_message=self._on_message,
                poll_timeout_seconds=self._cfg.telegram.poll_timeout_seconds,
                backoff_max_seconds=self._cfg.telegram.backoff_max_seconds,
                whitelist_size=len(self._cfg.telegram.allowed_user_ids),
                state_writer=heartbeat,
            )
            self._listener = listener
            self._listener_state_obj = listener.state

            # 004: register the curated slash-command set on the bot.
            # Fired as a background task so a slow / unavailable Telegram
            # cannot delay listener startup readiness — the listener loop
            # below begins polling immediately. Best-effort per FR-002.
            asyncio.create_task(self._register_slash_commands())

            self._ready.set()
            await listener.run()
        finally:
            await self._drain_workers()
            await client.aclose()
            with _suppress():
                conn.close()

    async def _register_slash_commands(self) -> None:
        """Best-effort setMyCommands. Failure is logged + audited but never raises."""
        import time as _time

        from remotask.daemon import audit as rt_audit

        assert self._client is not None and self._listener_state_obj is not None
        payload = rt_commands.to_bot_api_payload()
        try:
            await self._client.set_my_commands(payload)
        except Exception as e:  # noqa: BLE001 — best-effort
            _log.warning("runtime.set_my_commands_failed", error=str(e))
            self._listener_state_obj.commands_registered = False
            rt_audit.log_unbound_event(
                rt_audit.EV_COMMANDS_REGISTRATION_FAILED,
                {"error": str(e), "attempted_at": _time.time()},
            )
            return

        now = _time.time()
        self._listener_state_obj.commands_registered = True
        self._listener_state_obj.commands_registered_at = now
        rt_audit.log_unbound_event(
            rt_audit.EV_COMMANDS_REGISTERED,
            {"commands": payload, "registered_at": now},
        )
        _log.info("runtime.commands_registered", count=len(payload))

    # ---- dispatcher hook -----------------------------------------------------

    async def _on_message(self, message: dict[str, Any]) -> None:
        """Called by the listener for every accepted text message."""
        assert self._conn is not None and self._client is not None
        # 008/T4 — build the active task source adapter once at first
        # dispatch (process-lifetime singleton inside task_sources).
        from remotask.task_sources import get_active_adapter

        adapter = get_active_adapter(self._cfg, self._conn)
        ctx = rt_dispatcher.DispatchContext(
            conn=self._conn,
            client=self._client,
            cfg=self._cfg,
            adapter=adapter,
            spawn_worker_task=self._spawn_worker_task,
            worker_argv=self._worker_argv,
            worker_env=self._worker_env,
            mark_operator_stop_in_flight=self.mark_operator_stop_in_flight,
            is_operator_stop_in_flight=self.is_operator_stop_in_flight,
            worker_pid_for_session=self.worker_pid_for_session,
            register_worker_pid=self.register_worker_pid,
            bot_username=self._bot_username,
        )
        await rt_dispatcher.dispatch(message, ctx)

    def _spawn_worker_task(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Register a worker coroutine as a tracked task on the listener loop."""
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        self._worker_tasks.add(task)
        task.add_done_callback(self._worker_tasks.discard)

    # ---- 003: operator-stop coordination ------------------------------------

    def mark_operator_stop_in_flight(self, session_id: str, worker_pid: int) -> None:
        """Record that an operator stop has been initiated for ``session_id``.

        Called from the dispatcher's termination branch right before sending
        SIGUSR1. The pid is captured here too so the dispatcher's grace
        watchdog can escalate via ``_kill_worker_group`` if needed.
        """
        self._operator_stop_in_flight.add(session_id)
        self._worker_pid_by_session[session_id] = worker_pid

    def is_operator_stop_in_flight(self, session_id: str) -> bool:
        return session_id in self._operator_stop_in_flight

    def clear_operator_stop_in_flight(self, session_id: str) -> None:
        self._operator_stop_in_flight.discard(session_id)
        self._worker_pid_by_session.pop(session_id, None)

    def register_worker_pid(self, session_id: str, worker_pid: int) -> None:
        """Index a session id to its worker pid (called by the dispatcher)."""
        self._worker_pid_by_session[session_id] = worker_pid

    def worker_pid_for_session(self, session_id: str) -> int | None:
        return self._worker_pid_by_session.get(session_id)

    # ---- shutdown ------------------------------------------------------------

    def _initiate_shutdown(self) -> None:
        if self._listener is not None:
            self._listener.stop()

    async def _drain_workers(self) -> None:
        """Wait for in-flight workers up to ``shutdown_timeout``; cancel the rest."""
        if not self._worker_tasks:
            return
        _log.info("runtime.draining_workers", count=len(self._worker_tasks))
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._worker_tasks, return_exceptions=True),
                timeout=self._shutdown_timeout,
            )
        except TimeoutError:
            _log.warning("runtime.drain_timeout", remaining=len(self._worker_tasks))
            for t in list(self._worker_tasks):
                t.cancel()
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)


# ---- helpers ---------------------------------------------------------------


class _suppress:
    """Tiny ``contextlib.suppress`` clone tuned to the two errors we expect on close."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return exc_type is not None and issubclass(
            exc_type, (sqlite3.ProgrammingError, sqlite3.OperationalError)
        )


# ---- entry point used by ``commands/daemon.py run-foreground`` ----------------


def run() -> None:
    """Foreground daemon entry — drop-in replacement for ``stub_runtime.run``.

    Acquires PID lock, sets up logging, brings up Runtime, and waits for
    SIGTERM / SIGINT.

    If the Telegram listener is not yet configured (empty ``bot_token``,
    ``group_chat_id``, or ``allowed_user_ids``), the daemon falls back to the
    pre-002 behaviour: hold the PID lock and wait for shutdown without
    starting the listener. This keeps ``remotask init`` + ``remotask install``
    usable before the operator sets up Telegram.
    """
    import os

    from remotask.core import lifecycle
    from remotask.core import logging as rt_logging

    paths.data_dir().mkdir(parents=True, exist_ok=True)
    rt_logging.setup_logging(level="INFO", log_dir=paths.log_dir(), force_json=True)
    log = structlog.get_logger().bind(component="daemon")

    cfg = rt_config.load(paths.config_path())
    listener_configured = bool(
        cfg.telegram.bot_token
        and cfg.telegram.group_chat_id
        and cfg.telegram.allowed_user_ids
    )

    with lifecycle.Lifecycle(paths.pid_path()) as lc:
        log.info(
            "daemon.started",
            pid=os.getpid(),
            telegram_listener=("running" if listener_configured else "not configured"),
        )
        if not listener_configured:
            try:
                lc.wait_for_stop()
            finally:
                log.info("daemon.shutdown", pid=os.getpid())
            return

        # Fail-closed precondition check (FR-003 / US3). Issues are logged with
        # the field name only, never the value (so a misconfigured bot_token
        # does not leak into the daemon log).
        try:
            validate_listener_preconditions(cfg, config_path=paths.config_path())
        except ListenerPreconditionError as e:
            log.error("daemon.listener_precondition_failed", field=e.field, reason=e.reason)
            try:
                lc.wait_for_stop()
            finally:
                log.info("daemon.shutdown", pid=os.getpid())
            return

        runtime = Runtime(cfg=cfg)
        try:
            runtime.start()
            runtime.install_sigusr1_handler()
            lc.wait_for_stop()
        finally:
            runtime.stop()
            log.info("daemon.shutdown", pid=os.getpid())
