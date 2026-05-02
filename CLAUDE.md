<!-- SPECKIT START -->
Active feature plan: `specs/006-remove-termination-aliases/plan.md`

Related artifacts (read alongside the plan):
- `specs/006-remove-termination-aliases/spec.md` — feature specification (deprecation cleanup: `/done` slash + plain `done`/`stop`/`finish` removed; `/cancel` canonical preserved)
- `specs/006-remove-termination-aliases/research.md` — Phase 0 decisions (8 items: dispatch fall-through, parser deletion, runtime set removal, audit constants removal, worker on_terminal removal, quickstart redesign, 003 test migration, regression test layout)
- `specs/006-remove-termination-aliases/data-model.md` — V0001 schema unchanged; runtime `_alias_deprecation_warned` set + 3 methods + DispatchContext callbacks + 2 audit constants explicitly removed; worker `on_terminal` removed
- `specs/006-remove-termination-aliases/contracts/alias-removal-protocol.md` — `/done` → unknown_command rejection; plain text fall-through; audit invariants A1-A3
- `specs/006-remove-termination-aliases/quickstart.md` — manual verification: `/cancel` regression guard + `/done` rejection + plain-text ignore + `[KEY]` prefix preservation

Prior features (foundational; still authoritative):
- `specs/005-dm-channel/plan.md` — `/cancel` rename, `[KEY]` prefix chokepoint, alias deprecation (the time-box that 006 closes)
- `specs/004-slash-commands/plan.md` — setMyCommands, /run grammar, /status, slash-command dispatch
- `specs/003-e2e-demo/plan.md` — placeholder worker, operator-stop loop, FINAL line protocol
- `specs/002-telegram-trigger/plan.md` — listener, dispatcher, topic, audit, worker scaffolding
- `specs/001-cli-bootstrap/plan.md` — paths, schema V0001, daemon shell

Always-applies:
- `.specify/memory/constitution.md` — project principles (v1.1.0; Principle III amended)
- `PRD.md` — product-level context
<!-- SPECKIT END -->
