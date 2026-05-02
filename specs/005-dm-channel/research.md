# Phase 0 Research: `/cancel` Rename + `[KEY]` Prefix + Alias Deprecation

**Feature**: 005-dm-channel (narrowed scope — see spec.md "Scope decision")
**Date**: 2026-05-02

Each entry resolves an open decision raised in `plan.md`. After this phase, no `NEEDS CLARIFICATION` markers remain in Technical Context.

The initial draft of this file (rev 1) included 10 items covering 1:1 DM channel transition, chat-type detection, migration handling, and reply-to threading. All of those are dropped from rev 2 because the scope no longer includes a channel transition. The rev 2 list below is a focused subset.

---

## R1. `/cancel` slash-command grammar

**Decision**: Regex `^/cancel(?:@<botname>)?\s*$` applied to the slash-command entity body (after offset-0 + length normalisation from 004). No arguments accepted in 005 — the topic context (`message_thread_id`) is the authoritative session resolver, identical to how 004's `/done` resolved.

**Rationale**:
- Topic resolution is already the cleanest disambiguation mechanism — it carries the session identity in the chat structure itself, so adding an arg form would be redundant.
- Keeping `/cancel` arg-less in 005 minimises diff vs 004's `/done`. The handler is renamed; the resolution path is the same.
- A future feature with explicit-key cancel (e.g. when a single-channel surface is added) is a separate decision; not introduced here.

**Alternatives rejected**:
- *Permissive `/cancel <key>` form*: extra parser code + extra failure modes (unknown key, key not in active set) for zero user-visible benefit when the topic is the obvious resolver.
- *Reuse `/done` as canonical*: rejected by the operator — `done` semantically implies natural completion, the rename is the whole point of 005.

---

## R2. Deprecation-warning idempotency

**Decision**: Maintain a tiny in-memory set on `Runtime` of `(alias_token, session_id)` tuples. The first time an alias_token is used to cancel a given session_id, emit a structured-log `WARNING` and an `alias_deprecation_used` audit-log line, and record the tuple in the set. Subsequent uses on the same session are silent (worker has already exited anyway, but Telegram client double-tap or rapid-fire retries shouldn't flood the log). The set is cleared when the session reaches a terminal state.

**Rationale**:
- Per-(alias, session) keying lets the WARNING surface again on a *new* session, so the operator's overall "I keep typing `/done` after upgrading" pattern remains visible across many sessions.
- One WARNING per process lifetime would hide repeated misuse across sessions, weakening the migration signal.
- Warning on every use would be noisy on double-tap retries.

**Alternatives rejected**:
- *Per-process-lifetime idempotency*: hides cross-session repeat, weak migration signal.
- *No idempotency*: noisy logs on rapid alias retries, especially when the user hits `/done` and the worker hasn't exited yet so the user double-taps.

---

## R3. `[KEY]` prefix chokepoint

**Decision**: A single helper `topic.format_progress(issue_key, body)` returns `f"[{issue_key}] {body}"`. All status / progress / final / canceled messages flow through it. The `Session starting…` and `Draft PR opened: …` templates — which already carry the issue key in their text — do NOT pass through it (would produce stutter `[ZXTL-1234] Session starting for ZXTL-1234.`).

**Rationale**:
- Single chokepoint = no message accidentally untagged. Reviewers verify "did 005 forget to prefix?" by inspecting the worker's call sites: every prefixed message goes through the helper, every key-bearing template skips it. No third path.
- Skipping the prefix on key-bearing templates avoids visible stutter.

**Alternatives rejected**:
- *Universal prefixing*: produces visible stutter in some templates.
- *Per-template manual prefixing*: error-prone; new templates have to remember.

---

## R4. Curated command registry delta

**Decision**: `telegram/commands.py` `CURATED_COMMANDS` becomes `(run, cancel, status)`. The `done` entry is removed. The `cancel` entry uses description `"Cancel an active session"`, `requires_topic=True`, `requires_args=False`. Idempotency from 004 means the next `setMyCommands` call overwrites whatever was previously registered.

**Rationale**:
- Operators see `cancel` in their `/` autocomplete instead of `done` — that *is* the migration signal at the UI level.
- `requires_topic=True` matches FR-003 ("`/cancel` in main chat is rejected").
- `setMyCommands` is idempotent (004 R-decision); no "delete done" call needed.

**Alternatives rejected**:
- *Keep `done` in the registry temporarily*: would advertise the deprecated form, undermining the migration signal.
- *Add a fourth entry "cancel (preferred)"*: clutter; the rename is the whole point.

---

## R5. Distinguishing `/cancel` rejection from `/done` rejection in audit log

**Decision**: The `slash_command_rejected` event's `reason` field gains the value `main_chat_cancel`. The existing `main_chat_done` value is **retained** for audit lines produced by the deprecated `/done` alias path. Reviewers grepping audit.log can tell which command was attempted.

**Rationale**:
- Same gate, different command. Splitting the reason makes it possible to count "operators still using `/done`" via simple log analysis.
- Backwards-compatible — old audit lines with `main_chat_done` from 003/004 are still parseable.

**Alternatives rejected**:
- *Single shared reason value `main_chat_stop`*: loses the alias signal; harder to phase out aliases analytically.
- *Inline the command in the reason string itself*: violates the closed-set discipline 004 set up.

---

## R6. Plain-text alias scope (003 inheritance)

**Decision**: The 003 plain-text alias matcher (`done`/`stop`/`finish`, optional leading slash, case-insensitive, alone on a line, inside a topic only) is preserved unchanged. 005 adds a deprecation WARNING hook around it but does not change the matcher itself. **No plain-text `cancel` is added** — bare `cancel` in a topic is treated as casual chat and ignored.

**Rationale**:
- 003 chose a closed-set plain-text alias matcher specifically to keep the trigger / cancel grammar tight. Adding `cancel` to that set would broaden plain-text matching for marginal benefit (operators upgrading from 003/004 already typed `done`/`stop`/`finish`; nobody ever typed `cancel` in 003/004).
- The canonical `cancel` lives in slash form only. The plain-text aliases are the legacy surface.

**Alternatives rejected**:
- *Add `cancel` to plain-text matcher*: broadens matching for no operator benefit.
- *Drop plain-text matcher entirely in 005*: hard regression for 003 users on day one. The whole point of FR-006/FR-007 is one-release deprecation, not immediate removal.

---

## R7. `topic.py` rename

**Decision**: **Keep the name `topic.py`**. No rename in 005.

**Rationale**:
- The module's role (outbound message templates + small posting helpers) is unchanged. The name is accurate.
- Renaming would churn 002/003/004 history without functional benefit.
- The narrowed scope of 005 doesn't introduce a new presentation channel that would warrant the rename.

**Alternatives rejected**:
- *Rename to `channel.py`*: 30+ touch points across files; reviewers would conflate it with substantive 005 changes.

---

## R8. Should `[KEY]` prefix apply when a future single-channel surface is added?

**Decision**: **Yes** (forward-compatibility note, not a 005 implementation choice). `format_progress` is built independent of the channel — it operates on `(issue_key, body)` and returns a string. A future feature that posts into a non-topic surface (DM, web UI) reuses the same helper and gets the prefix automatically. 005 lays this groundwork at no extra cost.

**Rationale**:
- The topic separation is the dominant visual cue today, but the prefix has independent value (notification preview in "All Topics", potential future channels). Adding the prefix now is cheap and removes a future migration step.

**Alternatives rejected**:
- *Skip prefix for now, add later when needed*: forces a follow-up feature for trivial gain. The prefix is two characters of overhead per line.

---

## Summary

All 8 items resolved; no `NEEDS CLARIFICATION` markers remain. Phase 1 (data-model, contracts, quickstart) proceeds with the narrowed scope: rename `/done` → `/cancel`, add `[KEY]` prefix at one chokepoint, deprecate four alias tokens with one-release WARNING window, ship a `setMyCommands` payload delta, and otherwise change nothing.
