# Phase 0 Research: End-to-End Demo Workflow

**Feature**: 003-e2e-demo
**Date**: 2026-05-02

Each entry resolves an open decision raised in `plan.md`. After this phase, no `NEEDS CLARIFICATION` markers remain in Technical Context.

---

## R1. Stop signal: SIGUSR1 vs SIGTERM

**Decision**: Operator-initiated stop uses **`SIGUSR1`**. The 002 timeout / forced-kill ladder (SIGTERM → grace → SIGKILL) is reused unchanged for the *escalation* path when the worker fails to honour SIGUSR1 within the grace window.

**Rationale**:
- 002 already wired `SIGTERM` to the timeout watchdog. If we overload `SIGTERM` for operator stop, the worker's signal handler can't distinguish "operator pressed done" from "your time is up", which weakens audit and forces a side-channel disambiguator.
- `SIGUSR1` has no default Python behaviour we care about, is conventionally used for application-defined IPC, and is the same signal 002 already plumbs from the CLI through SIGUSR1 to the daemon for `telegram start/stop` (the daemon's existing handler stays distinct because it's installed in the daemon process; the worker installs its own SIGUSR1 handler on its own PID).
- Reusing the SIGTERM-then-SIGKILL ladder for the *escalation* path is desirable: only one place in the code path enforces "this process is going to die now"; the only new code is the *cooperative* SIGUSR1 handler on the worker side.

**Alternatives rejected**:
- *Single-signal scheme (SIGTERM for both)*: forces the worker to disambiguate via env var or a side-file. Adds state, hides intent.
- *SIGINT*: shares default handlers with terminal Ctrl-C; risky if the worker is ever attached to a TTY for debugging.
- *Custom IPC (named pipe / signalfd)*: over-engineered for a single-bit "please stop" message.

---

## R2. Worker stdout protocol shape

**Decision**: Extend the existing 002 stdout-line parser (`_stream_subprocess_output` in `daemon/worker.py`) to recognise three line shapes, in priority order:

```
PR_URL=<url>                   # 002, unchanged
PROGRESS <i>/<N> <iso8601>     # NEW — daemon posts as a topic message
FINAL <iteration> <reason>     # NEW — daemon posts as a topic message; reason ∈ {natural, operator_stop}
```

Anything that doesn't match these prefixes is **not** auto-posted to the topic — it is logged to `~/.local/share/remotask/logs/sessions/<id>.log` (already done by 002) and that's it. This avoids accidentally bridging unfiltered stderr or debug lines to Telegram.

**Rationale**:
- Single IPC channel (stdout) — no new sockets, FIFOs, or shared files.
- Pattern matches the 002 `PR_URL=` precedent; readers/maintainers find the shape consistent.
- Whitelist-style match (only known prefixes are bridged) prevents accidental noise from leaking to operator-visible messages.
- The `iso8601` timestamp is in the line so the operator on Telegram can see how long iterations actually took, even if the message arrived later.

**Alternatives rejected**:
- *JSON line per progress*: more flexible but the operator never reads raw stdout; the small line shape is simpler and still parseable in tests.
- *Push from worker directly to Telegram*: requires the worker to have the bot token + chat id. Bigger blast radius, more env surface, no clear win.

---

## R3. Topic → session lookup

**Decision**: Add `core.db.get_active_session_by_topic(conn, topic_id) -> Row | None` returning the latest non-terminal session whose `topic_id` equals the given value. Implementation: same shape as `get_active_session_for_issue` from 002. No index added; the active set is at most a handful of rows.

**Rationale**:
- The dispatcher receives Telegram updates with `message_thread_id` (= our `topic_id`). The natural lookup is "is there an active session bound to this topic?" — a single row read.
- Having both helpers (`by_issue` for the trigger path, `by_topic` for the termination path) keeps each call site straightforward.

**Alternatives rejected**:
- *Iterate active sessions in memory*: invites stale-cache bugs; the DB read costs nothing.
- *Compound key on `(issue_key, topic_id)`*: redundant — every session's `topic_id` is unique because of 002's 1:1:1:1 invariant.

---

## R4. Termination grammar

**Decision**: Case-insensitive single-token match against the fixed set `{done, stop, finish}` after `str.strip()`. Anything else is **not** a termination command. The parser lives in `telegram/parser.py` next to the issue-key extractor, exposed as `match_termination_command(text: str) -> str | None` returning the canonical lowercase form.

**Rationale**:
- Strict grammar prevents accidental termination on casual chat in the topic ("are we done?", "stop messing around").
- Single token avoids ambiguity with multi-word commands (which we explicitly out-of-scope in spec Assumptions).
- Three synonyms accommodates muscle memory; lowercase canonical form simplifies audit.

**Alternatives rejected**:
- *Slash commands (`/done`)*: Telegram bot framework convention but mixes triggers (`/cancel ZXTL-1234`) into a different namespace; we keep one minimum viable shape and can broaden later.
- *Free-form ("please stop", "kill it")*: too open; would require an LLM to interpret reliably, way out of scope.

---

## R5. Dispatcher branching order

**Decision**: When a text message arrives in the configured chat, the dispatcher applies these gates in order:

1. **whitelist** (sender id) — if not allowed, audit-log + return (silent).
2. **is the message in a topic** (`message_thread_id` non-null)? if yes:
   - try termination parser first.
   - if termination match → handle termination (R3 lookup, signal worker, audit, post final). Return.
3. fall through to issue-key extraction (the 002 trigger path) for the rest.

**Rationale**:
- Putting termination ahead of issue-key extraction inside-topic prevents weird matches: a topic message of `done` should never be treated as a (failed) issue key.
- Falling through means a topic message like "let's also look at FOO-1" is *not* treated as a new trigger — but neither is a casual chat message in the main channel. Both are silently ignored, consistent with 002's "no issue key, no reply" behaviour.
- The topic-vs-main-chat split is what enforces "stop commands in the main chat are silent ignores" without a special branch — main-chat messages have no `message_thread_id`, so the termination parser never fires on them.

**Alternatives rejected**:
- *Always run termination parser first*: would let `done` typed in the main chat trigger a global cancel — the operator would have to remember which session was active. The Q1 clarification ruled this out.
- *Always run issue-key parser first*: termination tokens like `done` don't match the issue-key regex anyway, so this is functionally equivalent for valid input — but it confuses readers about precedence.

---

## R6. Worker signal handler details

**Decision**: The placeholder worker installs a SIGUSR1 handler in `agent/demo_worker.py` that:

1. Sets a module-level "stop requested" flag (a `threading.Event` is overkill; a plain `bool` in a closure is enough since Python signal handlers run on the main thread).
2. The main loop checks the flag at the top of each iteration AND breaks the inter-iteration sleep into 0.5 s slices so a stop request mid-sleep is noticed within ≤ 0.5 s.
3. On stop, the worker prints `FINAL <i> operator_stop` to stdout, flushes, and exits 0. The daemon-side worker wrapper recognises `FINAL` and does the topic post + state transition.

**Rationale**:
- The handler is intentionally tiny — set a flag, return. No `print` from inside the handler (signal-safety).
- Sliced sleep keeps responsiveness without polling tightly. 0.5 s slices: 5 iterations × max 60 polls = 300 polls per session; trivially cheap.
- Exit 0 (not non-zero) because the worker did exactly what was asked of it; the daemon distinguishes "operator stop" from "natural completion" by the presence of `FINAL <i> operator_stop` (vs `FINAL <N> natural`).

**Alternatives rejected**:
- *No cooperative handler — rely on SIGTERM ladder*: violates US3's "flush a final status before exiting".
- *Use `os.kill(pid, signal.SIGUSR1)` from the worker itself for self-cleanup*: pointless indirection — just exit cleanly.

---

## R7. Grace window value

**Decision**: **5 seconds** between SIGUSR1 and the SIGTERM escalation. Configurable via a new optional field `agent.operator_stop_grace_seconds` (default 5, range 1..30) in `core/config.py`. **Not a separate field if it adds friction** — see Alternatives.

**Rationale**:
- The placeholder worker has nothing to checkpoint; it just needs to flush one stdout line.
- 5 s gives slack for a slow `print + flush + exit` on a loaded laptop without making forced-kill feel laggy.
- Real agent workloads will need a longer window (likely tens of seconds); that's a separate feature's concern. Making it configurable today means the single value works for tests (override to 0.5 s) and demos (5 s default).

**Alternatives considered**:
- *Hard-coded 5 s, no config field*: simpler; can be added later if real-agent feature wants it. **Final decision: keep it configurable now** — adding a pydantic field is two lines and tests want it short.
- *Reuse `agent.session_timeout_seconds`*: that's a per-task timeout, semantically different.

---

## R8. Audit event taxonomy

**Decision**: Two new event-type constants in `daemon/audit.py`:

| Constant | Bound to session? | Where written |
|---|---|---|
| `EV_TELEGRAM_TERMINATION_RECEIVED` | yes (the affected session) | `session_events` row |
| `EV_TELEGRAM_TERMINATION_REJECTED` | no | `audit.log` only (V0001's NOT NULL FK) |

**Rationale**:
- Mirrors 002's pattern: `telegram_message_received` (session-bound) vs `telegram_unauthorized` (unbound).
- Rejected commands include the rejection reason in payload (`unauthorized` / `wrong_topic` / `no_active_session` / `malformed`).

**Alternatives rejected**:
- *One generic `telegram_termination_attempted` event with status field*: harder to filter audit logs ("show me only accepted stops"); two types is clearer.

---

## R9. Quickstart manual recipe

**Decision**: `quickstart.md` covers, in order:

1. Configure + start daemon (002 step, just for completeness).
2. Trigger `ZXTL-DEMO` and observe (a) topic creation, (b) `Session starting`, (c) progress lines at i=1..N.
3. Mid-run, post `done` and observe (a) `FINAL <i> operator_stop` line in topic, (b) `Session stopped by operator` line, (c) DB row `status=canceled, error_message=operator_stop`.
4. Negative case: a non-whitelisted account posts `done` → no UI response, audit-log shows the rejection.
5. Negative case: post `done` in the main chat → no response.

**Rationale**:
- The quickstart is the SC-005 acceptance test ("operator can demonstrate the full loop using only their phone").
- Including negative cases in the quickstart catches whitelisting / topic-scoping regressions early.

**Alternatives**: none considered — this is the verification flow the spec mandates.

---

## R10. Test strategy

**Decision**:
- **Unit**: parser cases for the termination grammar; dispatcher cases for the four termination outcomes (accept, unauthorized, wrong-topic, no-active-session); demo_worker semantics (iteration count, env-var override, signal handler sets the flag).
- **Integration**: four scenarios — natural completion, graceful operator stop, forced operator stop (worker ignores SIGUSR1), termination rejection paths. All run with the *real* `agent.demo_worker` subprocess (not a fake) using shortened env-var iterations/interval, since the worker is itself the production code.

**Rationale**:
- Avoiding a separate `fake_agent` for 003 means tests exercise the real production module — fewer moving parts than 002 needed because 002's "real worker" was the SDK call we couldn't run in CI.
- The integration tests need only ~5 seconds each because of env-var overrides.

**Alternatives rejected**:
- *Mock the subprocess entirely*: loses end-to-end value; we already have 002's worker tests doing this kind of mock at lower fidelity.

---

## Summary

All 10 items resolved; no `NEEDS CLARIFICATION` markers remain. Phase 1 (data-model, contracts, quickstart) proceeds.
