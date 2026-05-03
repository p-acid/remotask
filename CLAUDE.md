# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## 5. Project Conventions (remotask)

This project keeps four durable documents at the root. Treat each as the **source of truth (SoT)** for its layer; in case of conflict, precedence runs left-to-right.

| Layer | File | What it answers |
|-------|------|-----------------|
| Principles | [`CONSTITUTION.md`](./CONSTITUTION.md) | Non-negotiable rules |
| Product | [`docs/PRD.md`](./docs/PRD.md) | Who, why, what is built / MVP scope / scenarios |
| System definition | [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) | How the system looks right now |
| Decision history | [`docs/ARD.md`](./docs/ARD.md) | Why this shape was chosen (D1, D2, …) |

Completed-work history lives in [`CHANGELOG.md`](./CHANGELOG.md) — one short section per feature with PR and ARD references. Append-only.

### Working rules

1. **Constitution wins.** Conflict order: `CONSTITUTION.md` > `docs/PRD.md` > `docs/ARCHITECTURE.md` > `docs/ARD.md` > everything else. Constitutional amendments go in their own PR.
2. **Spec-driven, but lightweight.** Non-trivial changes live in a single file at `specs/NNN-<name>.md`, derived from [`docs/templates/SPEC.md`](./docs/templates/SPEC.md) (motivation + behavior + acceptance tests + tasks inline). No folders, no plan/research/contracts/quickstart split. Bug fixes under 30 minutes touching ≤1 file are exempt.
3. **`docs/ARCHITECTURE.md` and `docs/ARD.md` move together.** When system shape changes, `docs/ARCHITECTURE.md` is updated; when the decision is new, `docs/ARD.md` gets a new entry (`DNN`). Old entries are not overwritten — supersession is recorded as a new entry.
4. **`docs/PRD.md` is the product layer.** Implementation detail (schemas, API signatures, directory trees, …) lives in `docs/ARCHITECTURE.md`, the spec, or the code itself — not in `docs/PRD.md`.
5. **Add a `CHANGELOG.md` section on feature merge.** PR link + key change summary + related ARD entry numbers. 5–15 lines.
6. **Spec files are disposable after merge.** Once merged, the spec file does not need to be retained — `CHANGELOG.md` is the durable record.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
