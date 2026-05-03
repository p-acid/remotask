"""Inbound-message dispatcher.

The listener calls ``dispatch(update, ctx)`` for every text update it sees in
the configured chat. The dispatcher decides what to do with that message and
either:

- silently ignores it (no key match, or US2/US3 rejection paths),
- replies in the main chat (US2/US6 rejection paths),
- starts a session: insert row, acquire lock, create topic, spawn worker.

This module focuses on the **accept path** (US1). The unknown-prefix branch
(US2), unauthorised branch (US3), and same-issue / concurrency branches (US6)
are filled in by their respective phases — they are present here as no-op
``return`` stubs with TODO markers so the dispatcher's structure is clear from
day one.
"""
from __future__ import annotations

import asyncio
import re as _re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from remotask.core import config as rt_config
from remotask.core import db as core_db
from remotask.core import projects as rt_projects
from remotask.daemon import audit, sessions, topic, worker
from remotask.telegram import commands as rt_commands
from remotask.telegram.client import TelegramAPIError, TelegramClient
from remotask.telegram.parser import (
    SlashCommandInvocation,
    extract_first_issue_key,
    match_slash_command,
    split_prefix,
)

_log = structlog.get_logger().bind(component="dispatcher")


@dataclass
class DispatchContext:
    """Everything the dispatcher needs that isn't a message-specific value."""

    conn: sqlite3.Connection
    client: TelegramClient
    cfg: rt_config.ConfigSchema
    # Hook for spawning the worker as a background task. The runtime supplies a
    # function that registers the task in its task set so shutdown can wait on
    # it. Tests pass a synchronous-ish version that awaits the worker inline.
    spawn_worker_task: Callable[[Any], Any]
    # Custom worker argv/env (for tests pointing at fake_agent). When None, the
    # production claude-agent-sdk driver is used.
    worker_argv: list[str] | None = None
    worker_env: dict[str, str] | None = None
    # 003: hooks the runtime provides so the termination branch can record
    # in-flight stops and resolve a session id to its worker pid. Tests pass
    # in-memory stand-ins.
    mark_operator_stop_in_flight: Callable[[str, int], None] | None = None
    is_operator_stop_in_flight: Callable[[str], bool] | None = None
    worker_pid_for_session: Callable[[str], int | None] | None = None
    register_worker_pid: Callable[[str, int], None] | None = None
    # 004: bot username (without @) used to strip ``@<botname>`` suffix from
    # slash commands. None disables suffix matching; suffix-less commands
    # still work.
    bot_username: str | None = None
    # 008/T4 — active TaskSourceAdapter, built once at daemon startup via
    # ``get_active_adapter(cfg, conn)``. Both dispatcher call sites
    # (plain-text + slash) read ``ctx.adapter`` so the daemon stays
    # provider-agnostic (PRD §6 invariant). ``Any`` typing avoids the
    # task_sources → dispatcher circular import.
    adapter: Any = None


async def dispatch(message: dict[str, Any], ctx: DispatchContext) -> None:
    """Entry point for every inbound text message.

    ``message`` is the raw Telegram message dict. We only need ``text``,
    ``message_id``, ``from.id``, ``chat.id``.
    """
    text = message.get("text") or ""
    sender = (message.get("from") or {}).get("id")
    chat = (message.get("chat") or {}).get("id")
    msg_id = message.get("message_id")

    if sender is None or chat is None:
        # Malformed update; nothing actionable.
        return

    thread_id = message.get("message_thread_id")

    # ---- whitelist gate (FR-002, FR-003) ---------------------------------
    if sender not in ctx.cfg.telegram.allowed_user_ids:
        # 004: distinguish unauthorised slash commands so the audit log can
        # separate "someone is trying to drive my bot via the menu" from the
        # plain-text scanning case.
        slash = match_slash_command(message, bot_username=ctx.bot_username)
        if slash is not None:
            audit.log_unbound_event(
                audit.EV_SLASH_COMMAND_REJECTED,
                {
                    "reason": "unauthorized",
                    "command": slash.name,
                    "sender_id": sender,
                    "chat_id": chat,
                    "message_id": msg_id,
                    "message_thread_id": thread_id,
                    "args_text_truncated": slash.args_text[:64],
                },
            )
            return
        # Silent rejection (no Telegram reply, no topic, no session row);
        # the audit log captures sender + message + chat for later review.
        audit.log_unbound_event(
            audit.EV_TELEGRAM_UNAUTHORIZED,
            {"sender_id": sender, "chat_id": chat, "message_id": msg_id},
        )
        return

    # ---- slash-command branch (004 / US1) --------------------------------
    # Runs *before* 003's termination grammar and 002's issue-key path so a
    # slash command never falls through to plain-text routing.
    slash = match_slash_command(message, bot_username=ctx.bot_username)
    if slash is not None:
        await _handle_slash_command(slash, ctx)
        return

    # ---- parse issue key (008/T4 — adapter-driven) -----------------------
    if ctx.adapter is None:
        # Defensive fallback: if no adapter was injected (legacy test
        # setup), drop back to the 002 grammar via the parser shim.
        operator_key = extract_first_issue_key(text)
        canonical = operator_key
    else:
        operator_key = ctx.adapter.matches(text)
        canonical = (
            ctx.adapter.to_canonical(operator_key) if operator_key else None
        )
    if canonical is None:
        # Casual chat / non-trigger: ignore entirely (FR-008).
        return

    key = canonical  # legacy variable name preserved through the rest
    if ctx.adapter is None:
        prefix = split_prefix(key)
    else:
        prefix = ctx.adapter.extract_project_identifier(canonical)
    project = rt_projects.by_identifier(
        ctx.conn, source=ctx.cfg.agent.task_source, identifier=prefix
    )
    if project is None:
        # Unknown prefix (FR-007). Reply in the main chat with the registered
        # prefix list so the operator can correct a typo without leaving
        # Telegram, and emit a non-session-bound audit entry.
        registered = rt_projects.list_registered_identifiers(
            ctx.conn, source=ctx.cfg.agent.task_source
        )
        await topic.post_to_main_chat(
            ctx.client,
            chat_id=chat,
            text=topic.TPL_UNKNOWN_PREFIX.format(
                prefix=prefix,
                prefixes=", ".join(registered) if registered else "(none)",
            ),
        )
        audit.log_unbound_event(
            audit.EV_TELEGRAM_UNKNOWN_PREFIX,
            {
                "prefix": prefix,
                "key": key,
                "registered_prefixes": registered,
                "sender_id": sender,
                "chat_id": chat,
                "message_id": msg_id,
            },
        )
        return

    # ---- same-issue concurrency (FR-010 / US6) --------------------------
    existing = core_db.get_active_session_for_issue(ctx.conn, key)
    if existing is not None:
        await topic.post_to_main_chat(
            ctx.client,
            chat_id=chat,
            text=topic.TPL_ALREADY_IN_FLIGHT.format(
                key=key, topic_id=existing["topic_id"] or 0
            ),
        )
        audit.record_event(
            ctx.conn,
            session_id=existing["id"],
            type=audit.EV_TELEGRAM_ALREADY_IN_FLIGHT,
            payload={
                "existing_session_id": existing["id"],
                "existing_topic_id": existing["topic_id"],
                "incoming_message_id": msg_id,
                "incoming_sender_id": sender,
            },
        )
        ctx.conn.commit()
        return

    # ---- max_concurrent cap (US6) ---------------------------------------
    cap = ctx.cfg.agent.max_concurrent
    if core_db.count_active_sessions(ctx.conn) >= cap:
        await topic.post_to_main_chat(
            ctx.client,
            chat_id=chat,
            text=topic.TPL_CONCURRENCY_CAP.format(cap=cap),
        )
        return

    # ---- accept path (US1) ----------------------------------------------
    await _accept_trigger(
        message_text=text,
        issue_key=key,
        sender_id=sender,
        chat_id=chat,
        message_id=msg_id,
        project=project,
        ctx=ctx,
        source=ctx.cfg.agent.task_source,
        project_identifier=prefix,
    )


async def _handle_termination(
    *,
    ctx: DispatchContext,
    command: str,
    sender_id: int,
    chat_id: int,
    message_id: int | None,
    topic_id: int,
) -> None:
    """Resolve the topic to its session and send SIGUSR1 to the worker."""
    import os
    import signal as _signal

    log = _log.bind(topic_id=topic_id, sender_id=sender_id, command=command)

    row = core_db.get_active_session_by_topic(ctx.conn, topic_id)
    if row is None:
        # Stale topic / no active session for this thread → silent ignore + audit.
        audit.log_unbound_event(
            audit.EV_TELEGRAM_TERMINATION_REJECTED,
            {
                "reason": "no_active_session",
                "sender_id": sender_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "message_thread_id": topic_id,
                "command_text": command,
            },
        )
        return

    session_id = str(row["id"])

    # Avoid double-handling if a previous `done` is already in flight.
    if ctx.is_operator_stop_in_flight is not None and ctx.is_operator_stop_in_flight(
        session_id
    ):
        audit.record_event(
            ctx.conn,
            session_id=session_id,
            type=audit.EV_TELEGRAM_TERMINATION_RECEIVED,
            payload={
                "command": command,
                "sender_id": sender_id,
                "message_id": message_id,
                "chat_id": chat_id,
                "message_thread_id": topic_id,
                "duplicate": True,
            },
        )
        ctx.conn.commit()
        return

    pid = ctx.worker_pid_for_session(session_id) if ctx.worker_pid_for_session else None
    if pid is None:
        # Worker hasn't started yet (race: operator typed `done` between the
        # session insert and worker spawn). Treat as no_active_session for
        # audit purposes; the worker will spawn and run normally.
        audit.log_unbound_event(
            audit.EV_TELEGRAM_TERMINATION_REJECTED,
            {
                "reason": "no_active_session",
                "sender_id": sender_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "message_thread_id": topic_id,
                "command_text": command,
            },
        )
        return

    audit.record_event(
        ctx.conn,
        session_id=session_id,
        type=audit.EV_TELEGRAM_TERMINATION_RECEIVED,
        payload={
            "command": command,
            "sender_id": sender_id,
            "message_id": message_id,
            "chat_id": chat_id,
            "message_thread_id": topic_id,
        },
    )
    ctx.conn.commit()

    if ctx.mark_operator_stop_in_flight is not None:
        ctx.mark_operator_stop_in_flight(session_id, pid)

    try:
        os.kill(pid, _signal.SIGUSR1)
        log.info("dispatch.termination.sent_sigusr1")
    except ProcessLookupError:
        log.info("dispatch.termination.worker_already_gone")
        return

    # 003 / US3: grace watchdog. If the worker is still alive after the
    # configured grace window, escalate via the 002 SIGTERM/SIGKILL ladder.
    grace = float(ctx.cfg.agent.operator_stop_grace_seconds)
    asyncio.create_task(
        _operator_stop_grace_watchdog(pid=pid, grace_seconds=grace, log=log)
    )


async def _operator_stop_grace_watchdog(
    *, pid: int, grace_seconds: float, log: Any
) -> None:
    """Wait up to ``grace_seconds`` for ``pid`` to exit; escalate via SIGTERM/SIGKILL."""
    import os as _os
    import signal as _signal

    end = asyncio.get_running_loop().time() + grace_seconds
    while asyncio.get_running_loop().time() < end:
        try:
            _os.kill(pid, 0)
        except ProcessLookupError:
            log.info("dispatch.termination.graceful_exit")
            return
        await asyncio.sleep(0.2)

    # Grace expired — worker is still around. Escalate.
    log.warning("dispatch.termination.grace_expired", pid=pid)
    pgid = _safe_pgid(pid)
    target = pgid if pgid is not None else None
    try:
        if target is not None:
            _os.killpg(target, _signal.SIGTERM)
        else:
            _os.kill(pid, _signal.SIGTERM)
    except ProcessLookupError:
        return

    # Final SIGKILL after a 5s SIGTERM grace, mirroring 002's ladder.
    await asyncio.sleep(5.0)
    try:
        _os.kill(pid, 0)
    except ProcessLookupError:
        return
    log.warning("dispatch.termination.escalating_to_sigkill", pid=pid)
    try:
        if target is not None:
            _os.killpg(target, _signal.SIGKILL)
        else:
            _os.kill(pid, _signal.SIGKILL)
    except ProcessLookupError:
        pass


def _safe_pgid(pid: int) -> int | None:
    import os as _os

    try:
        return _os.getpgid(pid)
    except ProcessLookupError:
        return None


async def _accept_trigger(
    *,
    message_text: str,
    issue_key: str,
    sender_id: int,
    chat_id: int,
    message_id: int | None,
    project: rt_projects.ProjectRow,
    ctx: DispatchContext,
    source: str = "jira",
    project_identifier: str | None = None,
) -> str | None:
    """Insert the session row + create the topic + hand off to the worker.

    Returns the new session id on success, or ``None`` if the accept path
    bailed early (e.g. createForumTopic failed and the session was marked
    failed before the worker could spawn). 004 callers use the returned id
    to record an additional ``slash_command_received`` audit row directly,
    avoiding a race-prone post-hoc lookup.
    """
    log = _log.bind(issue_key=issue_key, sender_id=sender_id)
    session_id = sessions.new_session_id()

    # The same-issue / concurrency-cap branches (US6) wrap this insert. For US1
    # we trust the caller to only invoke us when no active session exists.
    try:
        ctx.conn.execute("BEGIN IMMEDIATE")
        sessions.insert_enqueued_session(
            ctx.conn,
            session_id=session_id,
            issue_key=issue_key,
            trigger_user=sender_id,
            trigger_text=message_text,
            source=source,
            project_identifier=project_identifier,
        )
        sessions.acquire_issue_lock(
            ctx.conn, issue_key=issue_key, session_id=session_id
        )
        ctx.conn.commit()
    except Exception:
        ctx.conn.rollback()
        raise

    audit.record_event(
        ctx.conn,
        session_id=session_id,
        type=audit.EV_TELEGRAM_MESSAGE_RECEIVED,
        payload={
            "message_id": message_id,
            "sender_id": sender_id,
            "chat_id": chat_id,
            "parsed_key": issue_key,
        },
    )
    ctx.conn.commit()
    log.info("dispatch.accepted", session_id=session_id)

    # Create the forum topic. Failure is recoverable: mark session failed,
    # post to main chat, audit-log the failure.
    try:
        forum = await topic.create_topic_for_session(
            ctx.client, chat_id=chat_id, issue_key=issue_key
        )
    except TelegramAPIError as e:
        audit.record_event(
            ctx.conn,
            session_id=session_id,
            type=audit.EV_TELEGRAM_TOPIC_CREATE_FAILED,
            payload={"error_code": e.error_code, "description": e.description},
        )
        sessions.transition(
            ctx.conn,
            session_id=session_id,
            from_status="enqueued",
            to_status="failed",
            extra_columns={"error_message": f"createForumTopic: {e.description}"},
        )
        sessions.release_issue_lock(ctx.conn, issue_key=issue_key)
        ctx.conn.commit()
        await topic.post_to_main_chat(
            ctx.client,
            chat_id=chat_id,
            text=topic.TPL_TOPIC_CREATE_FAILED.format(
                key=issue_key, reason=e.description or "unknown error"
            ),
        )
        return None

    sessions.set_topic_id(ctx.conn, session_id=session_id, topic_id=forum.message_thread_id)

    # enqueued → starting (worktree creation about to begin in worker.run_worker)
    sessions.transition(
        ctx.conn,
        session_id=session_id,
        from_status="enqueued",
        to_status="starting",
    )

    # Build worker spec.
    worktree_root = worker.make_worktree_root(ctx.cfg.agent)
    worktree_path_for_msg = worktree_root / issue_key
    branch_for_msg = f"agent/{issue_key}"
    spec = worker.WorkerSpec(
        session_id=session_id,
        issue_key=issue_key,
        repo_path=Path(project["repo_path"]).expanduser(),
        base_branch=project["base_branch"],
        worktree_root=worktree_root,
        argv=ctx.worker_argv,
        extra_env=dict(ctx.worker_env or {}),
        timeout_seconds=float(ctx.cfg.agent.session_timeout_seconds),
    )

    # Topic-bound "Session starting…" announcement (uses planned worktree
    # path / branch; the worker emits "Status: running" once it actually moves
    # the row to running).
    await topic.post_to_topic(
        ctx.client,
        chat_id=chat_id,
        topic_id=forum.message_thread_id,
        text=topic.TPL_SESSION_STARTING.format(
            key=issue_key,
            worktree=str(worktree_path_for_msg),
            branch=branch_for_msg,
        ),
    )
    await sessions.post_status_to_topic(
        ctx.client,
        chat_id=chat_id,
        topic_id=forum.message_thread_id,
        new_status="starting",
        issue_key=issue_key,
    )

    # Hand off to the worker. The runtime registers this as a background task
    # so its lifetime is tracked across shutdown.
    def _on_worker_started(pid: int) -> None:
        if ctx.register_worker_pid is not None:
            ctx.register_worker_pid(session_id, pid)

    def _is_op_stop_in_flight() -> bool:
        if ctx.is_operator_stop_in_flight is None:
            return False
        return ctx.is_operator_stop_in_flight(session_id)

    coro = worker.run_worker(
        spec,
        conn=ctx.conn,
        client=ctx.client,
        chat_id=chat_id,
        topic_id=forum.message_thread_id,
        on_worker_started=_on_worker_started,
        is_operator_stop_in_flight=_is_op_stop_in_flight,
    )
    ctx.spawn_worker_task(coro)
    return session_id


# ===========================================================================
# 004 — Slash-command handlers
# ===========================================================================


async def _handle_slash_command(
    invocation: SlashCommandInvocation, ctx: DispatchContext
) -> None:
    """Route an authorised slash-command invocation to its dedicated handler."""
    cmd = rt_commands.lookup(invocation.name)
    if cmd is None:
        audit.log_unbound_event(
            audit.EV_SLASH_COMMAND_REJECTED,
            {
                "reason": "unknown_command",
                "command": invocation.name,
                "sender_id": invocation.sender_id,
                "chat_id": invocation.chat_id,
                "message_id": invocation.message_id,
                "message_thread_id": invocation.message_thread_id,
                "args_text_truncated": invocation.args_text[:64],
            },
        )
        return

    if cmd.requires_args and not invocation.args_text.strip():
        # Reply in the chat the command came from.
        await _reply_to_invocation(
            ctx, invocation, text=topic.TPL_RUN_USAGE_HINT
        )
        audit.log_unbound_event(
            audit.EV_SLASH_COMMAND_REJECTED,
            {
                "reason": "empty_args",
                "command": invocation.name,
                "sender_id": invocation.sender_id,
                "chat_id": invocation.chat_id,
                "message_id": invocation.message_id,
                "message_thread_id": invocation.message_thread_id,
                "args_text_truncated": "",
            },
        )
        return

    if cmd.requires_topic and invocation.message_thread_id is None:
        # 005: /cancel in main chat → main_chat_cancel.
        audit.log_unbound_event(
            audit.EV_SLASH_COMMAND_REJECTED,
            {
                "reason": audit.REASON_MAIN_CHAT_CANCEL,
                "command": invocation.name,
                "sender_id": invocation.sender_id,
                "chat_id": invocation.chat_id,
                "message_id": invocation.message_id,
                "message_thread_id": None,
                "args_text_truncated": invocation.args_text[:64],
            },
        )
        return

    if invocation.name == "run":
        await _handle_slash_run(invocation, ctx)
    elif invocation.name == "cancel":
        await _handle_slash_cancel(invocation, ctx)
    elif invocation.name == "status":
        await _handle_slash_status(invocation, ctx)


async def _reply_to_invocation(
    ctx: DispatchContext, invocation: SlashCommandInvocation, *, text: str
) -> None:
    """Post ``text`` back to the chat-of-origin (topic if present, else main)."""
    if invocation.message_thread_id is not None:
        await topic.post_to_topic(
            ctx.client,
            chat_id=invocation.chat_id,
            topic_id=invocation.message_thread_id,
            text=text,
        )
    else:
        await topic.post_to_main_chat(ctx.client, chat_id=invocation.chat_id, text=text)


async def _handle_slash_run(
    invocation: SlashCommandInvocation, ctx: DispatchContext
) -> None:
    """Route ``/run <args>`` to a session.

    Two paths: (a) args lead with a Jira-key (`PREFIX-NNN`) → reuse 002's
    accept-trigger pipeline against that prefix; (b) args are free-text →
    fall back to ``cfg.agent.default_project_jira_key`` (US4 — implemented
    in T025; T013 stubs free-text as ``no_default_project`` reject).
    """
    args = invocation.args_text.strip()
    # Args validity already checked in _handle_slash_command (requires_args).
    parts = args.split(None, 1)
    first_token = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    # 008/T4 — adapter-driven recognition. Falls back to the parser shim
    # when no adapter is injected (legacy test fixtures).
    if ctx.adapter is None:
        issue_key_match = extract_first_issue_key(first_token)
        canonical = issue_key_match
        if canonical is not None:
            prefix = split_prefix(canonical)
        else:
            prefix = ""
    else:
        operator_form = ctx.adapter.matches(first_token)
        canonical = (
            ctx.adapter.to_canonical(operator_form) if operator_form else None
        )
        prefix = (
            ctx.adapter.extract_project_identifier(canonical)
            if canonical
            else ""
        )
        # Path-(a) acceptance keys off ``first_token`` matching the operator
        # input form (post-adapter). For Jira keys this preserves the
        # 004 ``issue_key_match == first_token`` invariant; for GitHub
        # the operator-input form may differ from canonical (e.g.
        # ``p-acid/remotask#42`` vs ``gh-p-acid-remotask-42``).
        issue_key_match = canonical if (operator_form == first_token) else None

    if issue_key_match is not None:
        # Path (a): adapter-recognised key. Use the accept-trigger flow.
        project = rt_projects.by_identifier(
            ctx.conn, source=ctx.cfg.agent.task_source, identifier=prefix
        )
        if project is None:
            registered = rt_projects.list_registered_identifiers(
                ctx.conn, source=ctx.cfg.agent.task_source
            )
            await _reply_to_invocation(
                ctx,
                invocation,
                text=topic.TPL_UNKNOWN_PREFIX.format(
                    prefix=prefix,
                    prefixes=", ".join(registered) if registered else "(none)",
                ),
            )
            audit.log_unbound_event(
                audit.EV_TELEGRAM_UNKNOWN_PREFIX,
                {
                    "prefix": prefix,
                    "key": issue_key_match,
                    "registered_prefixes": registered,
                    "sender_id": invocation.sender_id,
                    "chat_id": invocation.chat_id,
                    "message_id": invocation.message_id,
                },
            )
            return

        await _accept_via_slash(
            invocation=invocation,
            issue_key=issue_key_match,
            trigger_text=rest,
            project=project,
            ctx=ctx,
            source=ctx.cfg.agent.task_source,
            project_identifier=prefix,
        )
        return

    # Path (b): free-text fallback. Filled in by US4 / T025. T013 (US1) stubs
    # this as a clear "default project not configured" reject so the menu
    # surface is at least honest while US4 is in flight.
    await _handle_slash_run_free_text(invocation, ctx, args=args)


async def _handle_slash_run_free_text(
    invocation: SlashCommandInvocation, ctx: DispatchContext, *, args: str
) -> None:
    """Free-text /run path. Resolves ``agent.default_project`` (008/T4 —
    renamed from ``agent.default_project_jira_key``, provider-neutral).

    When unset/unregistered → reply with a setup hint and reject.
    When set → synthesise a topic-id and run against the default project.
    """
    default_key = (ctx.cfg.agent.default_project or "").strip()
    project = (
        rt_projects.by_identifier(
            ctx.conn,
            source=ctx.cfg.agent.task_source,
            identifier=default_key,
        )
        if default_key
        else None
    )
    if project is None:
        await _reply_to_invocation(
            ctx, invocation, text=topic.TPL_RUN_NO_DEFAULT_PROJECT
        )
        audit.log_unbound_event(
            audit.EV_SLASH_COMMAND_REJECTED,
            {
                "reason": "no_default_project",
                "command": "run",
                "sender_id": invocation.sender_id,
                "chat_id": invocation.chat_id,
                "message_id": invocation.message_id,
                "message_thread_id": invocation.message_thread_id,
                "args_text_truncated": args[:64],
            },
        )
        return

    synthetic_id = synthesize_run_topic_id(args)
    await _accept_via_slash(
        invocation=invocation,
        issue_key=synthetic_id,
        trigger_text=args,
        project=project,
        ctx=ctx,
        source=ctx.cfg.agent.task_source,
        project_identifier=default_key,
    )


def synthesize_run_topic_id(args_text: str, *, now: datetime | None = None) -> str:
    """Produce ``run-<YYYY-MM-DD-HH-MM>-<slug>-<6-hex>`` per data-model.md."""
    import secrets as _secrets
    from datetime import UTC

    when = now if now is not None else datetime.now(UTC)
    timestamp = when.strftime("%Y-%m-%d-%H-%M")
    slug_raw = _re.sub(r"[^a-z0-9]+", "-", args_text.lower()).strip("-")
    slug_raw = slug_raw[:20].rstrip("-") or "untitled"
    return f"run-{timestamp}-{slug_raw}-{_secrets.token_hex(3)}"


async def _accept_via_slash(
    *,
    invocation: SlashCommandInvocation,
    issue_key: str,
    trigger_text: str,
    project: rt_projects.ProjectRow,
    ctx: DispatchContext,
    source: str = "jira",
    project_identifier: str | None = None,
) -> None:
    """Slash-driven equivalent of the 002 accept-trigger flow.

    Records both the message-received audit (for parity with the plain-text
    path) and a new ``slash_command_received`` event tied to the new session.
    """
    # Same-issue concurrency check (002 FR-010).
    existing = core_db.get_active_session_for_issue(ctx.conn, issue_key)
    if existing is not None:
        await _reply_to_invocation(
            ctx,
            invocation,
            text=topic.TPL_ALREADY_IN_FLIGHT.format(
                key=issue_key, topic_id=existing["topic_id"] or 0
            ),
        )
        audit.record_event(
            ctx.conn,
            session_id=existing["id"],
            type=audit.EV_TELEGRAM_ALREADY_IN_FLIGHT,
            payload={
                "existing_session_id": existing["id"],
                "existing_topic_id": existing["topic_id"],
                "incoming_message_id": invocation.message_id,
                "incoming_sender_id": invocation.sender_id,
            },
        )
        ctx.conn.commit()
        return

    # max_concurrent cap.
    cap = ctx.cfg.agent.max_concurrent
    if core_db.count_active_sessions(ctx.conn) >= cap:
        await _reply_to_invocation(
            ctx, invocation, text=topic.TPL_CONCURRENCY_CAP.format(cap=cap)
        )
        return

    # Reuse the existing 002 accept-trigger flow. It returns the new session
    # id directly so we can attach the slash-command audit event without a
    # post-hoc lookup (which would race with workers that complete inline).
    new_session_id = await _accept_trigger(
        message_text=trigger_text,
        issue_key=issue_key,
        sender_id=invocation.sender_id,
        chat_id=invocation.chat_id,
        message_id=invocation.message_id,
        project=project,
        ctx=ctx,
        source=source,
        project_identifier=project_identifier,
    )

    if new_session_id is not None:
        audit.record_event(
            ctx.conn,
            session_id=new_session_id,
            type=audit.EV_SLASH_COMMAND_RECEIVED,
            payload={
                "command": invocation.name,
                "args_text_truncated": invocation.args_text[:64],
                "sender_id": invocation.sender_id,
                "message_id": invocation.message_id,
                "chat_id": invocation.chat_id,
                "message_thread_id": invocation.message_thread_id,
            },
        )
        ctx.conn.commit()


async def _handle_slash_cancel(
    invocation: SlashCommandInvocation, ctx: DispatchContext
) -> None:
    """Route ``/cancel`` to the operator-stop termination ladder.

    Reuses :func:`_handle_termination` so the SIGUSR1 / grace ladder /
    audit trail is identical to the cancel path. Records an
    ``EV_SLASH_COMMAND_RECEIVED`` event and ``telegram_termination_received``
    so the audit log captures the slash invocation.
    """
    # message_thread_id non-None already enforced by _handle_slash_command.
    assert invocation.message_thread_id is not None
    row = core_db.get_active_session_by_topic(
        ctx.conn, invocation.message_thread_id
    )
    session_id_for_audit = str(row["id"]) if row is not None else None

    if row is not None:
        audit.record_event(
            ctx.conn,
            session_id=session_id_for_audit,
            type=audit.EV_SLASH_COMMAND_RECEIVED,
            payload={
                "command": invocation.name,
                "args_text_truncated": "",
                "sender_id": invocation.sender_id,
                "message_id": invocation.message_id,
                "chat_id": invocation.chat_id,
                "message_thread_id": invocation.message_thread_id,
            },
        )
        ctx.conn.commit()

    await _handle_termination(
        ctx=ctx,
        command=invocation.name,
        sender_id=invocation.sender_id,
        chat_id=invocation.chat_id,
        message_id=invocation.message_id,
        topic_id=invocation.message_thread_id,
    )


async def _handle_slash_status(
    invocation: SlashCommandInvocation, ctx: DispatchContext
) -> None:
    """Reply with the active-session list (main chat) or topic-detail."""
    if invocation.message_thread_id is None:
        await _slash_status_main_chat(invocation, ctx)
    else:
        await _slash_status_topic_detail(invocation, ctx)


async def _slash_status_main_chat(
    invocation: SlashCommandInvocation, ctx: DispatchContext
) -> None:
    cur = ctx.conn.cursor()
    cur.row_factory = sqlite3.Row
    # Single read = consistent snapshot. We pull up to 10 rows for display
    # PLUS a separate COUNT(*) so the "+ N more" footer reflects the actual
    # overflow rather than `min(actual, 11) - 10` (= always 1).
    cur.execute(
        f"SELECT id, issue_key, status, started_at, log_path, enqueued_at "
        f"FROM sessions WHERE status IN ({core_db._NON_TERMINAL_PLACEHOLDERS}) "
        f"ORDER BY enqueued_at DESC LIMIT 10",
        core_db.NON_TERMINAL_STATES,
    )
    rows = cur.fetchall()
    if not rows:
        await topic.post_to_main_chat(
            ctx.client, chat_id=invocation.chat_id, text=topic.TPL_STATUS_NO_ACTIVE
        )
        return
    total = ctx.conn.execute(
        f"SELECT COUNT(*) FROM sessions WHERE status IN ({core_db._NON_TERMINAL_PLACEHOLDERS})",
        core_db.NON_TERMINAL_STATES,
    ).fetchone()[0]

    lines = [topic.TPL_STATUS_LIST_HEADER.format(count=total)]
    for row in rows:
        iter_str = _format_iteration_for_log(row["log_path"])
        # Prefer started_at (when the worker actually began) — falls back to
        # enqueued_at for sessions that haven't transitioned past 'enqueued'.
        anchor = row["started_at"] or row["enqueued_at"]
        age = _format_age(int(anchor))
        lines.append(
            topic.TPL_STATUS_LIST_LINE.format(
                key=row["issue_key"],
                status=row["status"],
                iter=iter_str,
                age=age,
            )
        )
    if total > len(rows):
        lines.append(topic.TPL_STATUS_TRUNCATED.format(n=total - len(rows)))
    lines.append("")
    lines.append(topic.TPL_STATUS_LIST_HINT)
    await topic.post_to_main_chat(
        ctx.client, chat_id=invocation.chat_id, text="\n".join(lines)
    )


async def _slash_status_topic_detail(
    invocation: SlashCommandInvocation, ctx: DispatchContext
) -> None:
    assert invocation.message_thread_id is not None
    row = core_db.get_active_session_by_topic(
        ctx.conn, invocation.message_thread_id
    )
    if row is None:
        await topic.post_to_topic(
            ctx.client,
            chat_id=invocation.chat_id,
            topic_id=invocation.message_thread_id,
            text=topic.TPL_STATUS_NO_TOPIC_SESSION,
        )
        return

    iter_str = _format_iteration_for_log(row["log_path"])
    anchor = row["started_at"] or row["enqueued_at"]
    age = _format_age(int(anchor))
    detail = topic.TPL_STATUS_DETAIL.format(
        key=row["issue_key"],
        status=row["status"],
        iteration=iter_str,
        age=age,
        worktree=row["worktree_path"] or "(not yet created)",
    )
    await topic.post_to_topic(
        ctx.client,
        chat_id=invocation.chat_id,
        topic_id=invocation.message_thread_id,
        text=detail,
    )


# ----- helpers ------------------------------------------------------------


_PROGRESS_LINE_RE = _re.compile(r"^PROGRESS (\d+)/(\d+) (\S+)\s*$")


def _format_iteration_for_log(log_path: str | None) -> str:
    """Read the most recent PROGRESS line from a session log; render `i/N` or `—`.

    The returned value is the bare ``i/N`` (e.g. ``3/5``) so callers can put it
    behind their own label (``iteration: 3/5`` in the detail view, just ``3/5``
    in the list view). This avoids the ``iteration: iteration 3/5`` label
    duplication an earlier draft produced.
    """
    if not log_path:
        return "—"
    try:
        with Path(log_path).open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            # Read last 4 KB; placeholder workload's lines are ~50 bytes each.
            f.seek(max(0, size - 4096))
            tail = f.read().decode(errors="replace")
    except OSError:
        return "—"
    last: str | None = None
    for line in tail.splitlines():
        m = _PROGRESS_LINE_RE.match(line)
        if m is not None:
            last = f"{m.group(1)}/{m.group(2)}"
    return last or "—"


def _format_age(epoch_seconds: int) -> str:
    import time as _time

    delta = max(0, int(_time.time() - epoch_seconds))
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60} min ago"
    if delta < 86400:
        return f"{delta // 3600} h ago"
    return f"{delta // 86400} d ago"
