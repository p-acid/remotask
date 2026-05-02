# Contract: Worker Stdout Line Protocol

**Feature**: 003-e2e-demo
**Status**: Phase 1 design

This document defines the (small, line-oriented) protocol the daemon expects from worker subprocess stdout. 002 already established a single line shape (`PR_URL=…`); 003 extends the contract with two more.

## Line shapes

The worker writes plain UTF-8 text lines to stdout, one record per line, terminated by `\n`. The daemon's `_stream_subprocess_output` reads them as they arrive.

| Pattern (`re.match` against the trimmed line) | Daemon action |
|---|---|
| `^PR_URL=(\S+)\s*$` | Capture the URL on the session row; post `Draft PR opened: <url>` to the bound topic. (002, unchanged.) |
| `^PROGRESS (\d+)/(\d+) (\S+)\s*$` | Format and post `Status: iteration <i>/<N> @ <ts>` to the bound topic. |
| `^FINAL (\d+) (\S+)\s*$` | Capture (`iteration`, `reason`); post `Status: final iteration <i> (<reason>)` to the bound topic. `reason` is taken verbatim. |
| _(anything else)_ | Append to the per-session log file only; do **not** post to Telegram. |

## Formal grammar

```text
PROGRESS <iteration> "/" <total> SP <iso8601_timestamp>
FINAL <iteration> SP <reason>

# PROGRESS iteration is 1-based — emitted at the start of each iteration.
progress_iteration := positive integer (1..1_000_000)

# FINAL iteration may be 0 — meaning a stop arrived before the first PROGRESS
# line had a chance to emit. Otherwise it is the index of the most recent
# PROGRESS line.
final_iteration   := non-negative integer (0..1_000_000)

total             := positive integer (>= progress_iteration)
iso8601_timestamp := ISO-8601 in UTC, e.g. 2026-05-02T08:30:15Z
reason            := bareword in {natural, operator_stop}
```

The grammar is deliberately strict so accidental stdout (a debug `print("done")`) doesn't reach Telegram.

## Worker-side responsibilities (placeholder demo worker, 003 production module)

The placeholder worker MUST:

1. At startup, install a SIGUSR1 handler that sets a "stop requested" flag (no I/O inside the handler — Python signal-safety).
2. Loop `iterations` times. At the *start* of each iteration:
   a. If the stop flag is set, emit `FINAL <i> operator_stop`, flush stdout, exit 0.
   b. Otherwise emit `PROGRESS <i>/<iterations> <iso8601>`, flush stdout.
   c. Sleep `interval_seconds`, but *break the sleep into ≤ 0.5-second slices* so a stop request mid-sleep is observed within ≤ 0.5 s.
3. After the loop completes naturally, emit `FINAL <iterations> natural`, flush stdout, exit 0.

Read configuration from the environment:

| Variable | Required | Default | Type |
|---|---|---|---|
| `REMOTASK_DEMO_ITERATIONS` | no | `5` | int |
| `REMOTASK_DEMO_INTERVAL_SECONDS` | no | `30.0` | float |

## Daemon-side responsibilities (extended `_stream_subprocess_output`)

The daemon MUST:

1. Match each line against the four patterns in priority order.
2. For matches against `PROGRESS` / `FINAL`, post the corresponding template to the **session-bound topic** (never the main chat).
3. For matches against `PR_URL=`, capture and apply as 002 does.
4. For non-matches, write to the per-session log file ONLY.
5. Be resilient to malformed lines: a line like `PROGRESS not-a-number/5 today` MUST NOT crash the streamer; it falls through to the log-only path.
6. Apply the **state-transition mapping** from `data-model.md` once the worker exits, using:
   - exit code (0 vs non-zero vs killed-by-signal),
   - whether the runtime had set `operator_stop_in_flight` for this session,
   - the most recent `FINAL` line observed (if any).

## Backward compatibility with 002

- The `PR_URL=` shape is **unchanged**. The 002 worker tests (success-with-pr / success-no-pr / exit-nonzero) continue to pass without modification.
- The placeholder worker emits `FINAL` but never emits `PR_URL=` — consistent with the reality that this workload never opens a PR. If a future *real* agent worker emits both, the daemon honours both: the PR URL is captured and the FINAL line drives the natural-vs-operator distinction.

## Out-of-band channels

There is no other communication channel between worker and daemon for the placeholder workload:

- No file write-back (other than per-session log already in 002).
- No HTTP / unix socket (constitution forbids extra IPC anyway — D14).
- No DB writes from the worker (it has no DB connection; the daemon owns the connection on its thread).

## Why not JSON lines?

A line-based grammar with positional fields was chosen over JSON because:

1. The daemon parses three fixed line shapes; a JSON parser per line is overhead with no extra utility.
2. The set of fields is closed and tiny — no extension story is needed for 003.
3. The line shapes are visually obvious in the per-session log, which is also human-readable.

If a future feature genuinely needs structured payloads (e.g., real agent emits long status objects), it can add a fourth shape `EVENT {<json>}` without breaking the existing three.
