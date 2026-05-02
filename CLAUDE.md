<!-- SPECKIT START -->
Active feature plan: `specs/005-dm-channel/plan.md`

Related artifacts (read alongside the plan):
- `specs/005-dm-channel/spec.md` — feature specification (rev 2 narrowed scope: `/cancel` rename + `[KEY]` prefix + alias deprecation; folder name retained)
- `specs/005-dm-channel/research.md` — Phase 0 decisions (8 items, rev 2)
- `specs/005-dm-channel/data-model.md` — V0001 schema reuse + Runtime `alias_deprecation_warned` set + new audit event + curated-set delta
- `specs/005-dm-channel/contracts/` — `/cancel` dispatch + alias deprecation protocol
- `specs/005-dm-channel/quickstart.md` — manual end-to-end forum-topic flow with `/cancel`, alias deprecation, `[KEY]` prefix verification

Prior features (foundational; still authoritative):
- `specs/004-slash-commands/plan.md` — setMyCommands, /run grammar, /status, slash-command dispatch
- `specs/003-e2e-demo/plan.md` — placeholder worker, operator-stop loop, FINAL line protocol
- `specs/002-telegram-trigger/plan.md` — listener, dispatcher, topic, audit, worker scaffolding
- `specs/001-cli-bootstrap/plan.md` — paths, schema V0001, daemon shell

Always-applies:
- `.specify/memory/constitution.md` — project principles (v1.1.0; Principle III amended)
- `PRD.md` — product-level context
<!-- SPECKIT END -->
