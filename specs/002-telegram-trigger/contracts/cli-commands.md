# CLI Contract: `remotask telegram`

**Feature**: 002-telegram-trigger
**Status**: Phase 1 design

This document defines the user-facing CLI surface added by this feature. Behaviour deltas to the existing CLI from 001-cli-bootstrap are minimal (one new subcommand group registered in `cli.py`).

## `remotask telegram` (subcommand group)

Group help: `Control the Telegram listener subsystem of the running daemon.`

All subcommands assume the daemon is running. If the daemon is not running, each subcommand exits with code 3 and prints a clear "daemon not running" message pointing at `remotask daemon start`.

---

## `remotask telegram start`

**Purpose**: Tell the running daemon to begin polling Telegram (if not already polling).

**Flags**: none.

**Side effects**:
- Writes a fresh command record to `~/.local/share/remotask/listener.cmd` with `command="start"` and a monotonically increasing `seq`.
- Sends `SIGUSR1` to the daemon process (PID read from the existing `~/.local/share/remotask/remotask.pid`).
- Polls `~/.local/share/remotask/listener.state` for up to 5 seconds, expecting `running == true`.

**Exit codes**:
| Code | Meaning |
|------|---------|
| 0 | Listener is now running. |
| 3 | Daemon not running. |
| 4 | Daemon did not start the listener within the timeout (state file did not flip). |
| 5 | Configuration prevents start (e.g., empty whitelist, missing bot token). The CLI prints a precise error including the missing field. |

**Output (stdout)** on success:
```
listener started (whitelist=2, last_poll=just now)
```

---

## `remotask telegram stop`

**Purpose**: Tell the running daemon to stop accepting new triggers.

**Flags**: none.

**Side effects**:
- Writes `command="stop"` to `listener.cmd`.
- Sends `SIGUSR1` to the daemon.
- Waits up to 5 seconds for `listener.state` to show `running == false`.
- **Does not** cancel in-flight worker sessions; those continue to terminal state.

**Exit codes**: 0 (stopped), 3 (daemon not running), 4 (state file did not flip).

**Output**:
```
listener stopped (active sessions left running: 1)
```

---

## `remotask telegram status`

**Purpose**: Show listener state.

**Flags**:
- `--json` — emit machine-readable JSON instead of the human table.

**Side effects**: read-only on `listener.state`.

**Exit codes**: 0 always (informational), unless the state file is missing or unparseable, then 1.

**Output (default)**:
```
listener:        running
since:           2026-05-01T08:00:00 (45 minutes ago)
last poll:       2026-05-01T08:44:55 (5 seconds ago)
degraded:        no
active sessions: 1
whitelist size:  2
```

**Output (`--json`)**: the raw JSON from `listener.state` (see `data-model.md`).

---

## Failure UX rules (apply to all three subcommands)

- If the daemon's PID file points at a process that does not exist or cannot be signalled, the CLI prints `daemon process X not responding` and exits 3.
- If `listener.state` is older than 30 seconds when read, the status command prints a `(stale)` annotation but does not fail.
- All errors are printed to stderr; stdout is reserved for the human table or JSON.

## Help-text quality bar

- All subcommands include a one-line summary, an example, and the relevant config keys (`telegram.bot_token`, `telegram.allowed_user_ids`).
- `remotask telegram --help` lists `start`, `stop`, `status` only.

## Auth model

These commands inspect/modify only **local** files and signal the **local** daemon. There is no network call. No additional authentication beyond filesystem permissions on the state/command files (already 0600 inside `~/.local/share/remotask/`).
