# remotask

Remote agent trigger for Claude Code via Telegram. From your phone, one
`/run ZXTL-1234` line launches a Claude Code session on your local PC,
which works the Jira issue and opens a Draft PR on its own.

## What it does

- Trigger a session from Telegram via `/run <Jira-key>` (or a plain-text
  message containing `ZXTL-1234`).
- Only whitelisted users can trigger; sessions are isolated per forum topic.
- The daemon performs the work via `git worktree` + the Claude Agent SDK.
- Progress is reported back to the same topic in real time as
  `[ZXTL-1234] Status: …` lines.
- The first commit triggers an automatic GitHub Draft PR; the URL is
  posted back to the topic.
- If the agent goes off track, a single `/cancel` in the same topic ends
  the session gracefully (force-kill after a grace window if it doesn't
  respond).
- Merging is performed by a human, in the GitHub mobile app.

## Status

Phase 1 (MVP) complete. Phase 2 (web GUI) is planned. Detailed scope lives
in [`docs/PRD.md`](./docs/PRD.md) §2; the merged feature stack so far is
in [`CHANGELOG.md`](./CHANGELOG.md) and [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) §8.

## Install

```bash
uv tool install .
```

## Quickstart

```bash
remotask init                                  # config + DB + token bootstrap
remotask config set agent.max_concurrent 1
remotask projects add ZXTL ~/Developments/zextool
remotask install                               # register the macOS launchd agent
remotask daemon status                         # ✓ running
```

The Telegram-side setup (creating the bot, enabling supergroup forum mode,
adding the whitelist) is walked through by the `remotask init` wizard. The
latest workflow changes are tracked in [`CHANGELOG.md`](./CHANGELOG.md).

## CLI

```
remotask init                  # interactive setup wizard
remotask install / uninstall   # register / unregister the launchd plist
remotask daemon start | stop | status | logs -f
remotask daemon run-foreground # the entry point launchd invokes
remotask config get | set <key> [value]
remotask login                 # register Telegram token + group
remotask sessions list | cancel <issue-key>
remotask projects list | add <jira-key> <repo-path> | remove <jira-key>
```

## Telegram surface (operator commands)

A curated slash set (auto-completed by the BotFather UI):

| Command | Description |
|---------|-------------|
| `/run <Jira-key | free-text>` | Start a session |
| `/cancel` | End the active session (must be sent inside the topic) |
| `/status` | Active-session list (in main chat) / topic detail (inside a topic) |

Plain-text messages are also accepted as session triggers when they contain
the `[A-Z][A-Z0-9_]{1,9}-\d{1,6}` pattern (e.g. `please look at ZXTL-1234`).
Anything else in plain text is treated as ordinary chat and ignored.

## Development

```bash
uv sync
uv run pytest                          # full suite (~60s)
uv run ruff check src/ tests/
uv run mypy src/remotask/core/
```

Tests live under `tests/unit/` and `tests/integration/`. The opt-in
`local_only` marker is reserved for tests that mutate real launchctl state
— run them with `pytest -m local_only`.

## Documentation map

| Document | Question it answers |
|----------|---------------------|
| [`CONSTITUTION.md`](./CONSTITUTION.md) | Rules we never break |
| [`docs/PRD.md`](./docs/PRD.md) | Who, why, what's in scope / out of scope (product layer) |
| [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) | What the system looks like right now |
| [`docs/ARD.md`](./docs/ARD.md) | Why we picked this shape (decision history) |
| [`CHANGELOG.md`](./CHANGELOG.md) | Per-feature merge history |
| [`CLAUDE.md`](./CLAUDE.md) | AI-agent behaviour guide (Karpathy §1–§4 + §5 project conventions) |
| [`docs/templates/SPEC.md`](./docs/templates/SPEC.md) | Single-file spec template (TDD-explicit) |

New features are written by copying [`docs/templates/SPEC.md`](./docs/templates/SPEC.md)
into a single file at `specs/NNN-<name>.md` — TDD-explicit. After merge,
add a 5–15-line entry to `CHANGELOG.md`. (Constitution §V — see
[`CONSTITUTION.md`](./CONSTITUTION.md).)
