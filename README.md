# remotask

Remote agent trigger for Claude Code via Telegram. The first feature
(`001-cli-bootstrap`) ships the foundation:

- `remotask` CLI with subcommands (init, install, uninstall, daemon,
  config, login, sessions, projects).
- XDG-compliant data layout under `~/.config/remotask` and
  `~/.local/share/remotask`.
- SQLite schema for sessions, projects, session_events, locks (V0001).
- Stub daemon with PID file + flock + signal handlers (single-instance).
- macOS launchd registration via `install` / `uninstall`.
- Project mapping CRUD (`projects add/list/remove`) ready for the next
  feature (`002-telegram-trigger`).

> Spec, plan, contracts, and tasks for this feature live under
> `specs/001-cli-bootstrap/`. The project follows the spec-kit workflow.

## Install

```bash
uv tool install .
```

## Quickstart

See `specs/001-cli-bootstrap/quickstart.md` for the full step-by-step
verification procedure.

```bash
remotask init                                  # bootstrap config + DB + token
remotask config set agent.max_concurrent 1
remotask projects add ZXTL ~/Developments/zextool
remotask install                               # register macOS launchd agent
remotask daemon status                         # ✓ running
```

## Development

```bash
uv sync
uv run pytest                          # full test suite (~25s)
uv run ruff check src/ tests/
uv run mypy src/remotask/core/
```

Tests are organised under `tests/unit/` and `tests/integration/`. The
opt-in `local_only` marker is reserved for tests that mutate real
launchctl state — run them with `pytest -m local_only`.

## Project structure

See `PRD.md` and `.specify/memory/constitution.md` for product- and
governance-level context.
