# Process Overhaul

Working document. Retire `specs/`'s 7-file pattern and switch to single-file
spec + append-only `CHANGELOG.md`. Adopt Karpathy-style behavioural guidelines
in `CLAUDE.md` §1–§4, with project conventions in §5. **This file is
disposable** and is removed in the final task.

> Diagnosis: the 7-file folders under `specs/` were heavy relative to the
> change size (006 was the clearest case). The durable value lives in the
> four top layers (CONSTITUTION / PRD / ARCHITECTURE / ARD). History fits in
> a single short `CHANGELOG.md`, one section per feature.

## Decisions (locked in)

- **Branch**: `chore/process-overhaul`, branched from `main` after PR #6
  merged. Single PR (#7), draft.
- **Existing `specs/` folders**: extracted into `CHANGELOG.md` sections
  (already done in Phase 1), then the entire `specs/` folder is removed.
- **speckit residue**: removed entirely. `.claude/skills/speckit-*` (14
  packages), `.specify/` everything except `memory/constitution.md` (which
  is promoted, see below).
- **Doc layout**:
  - root: `CONSTITUTION.md` (after promotion), `CLAUDE.md`, `CHANGELOG.md`,
    `README.md`. CHANGELOG stays at root by Keep-a-Changelog convention.
  - `docs/`: `PRD.md`, `ARCHITECTURE.md`, `ARD.md`.
  - `docs/templates/SPEC.md`: single-file spec template (TDD-explicit).
- **Language**: every durable doc is English. §1–§4 of `CLAUDE.md` are a
  verbatim copy of forrestchang/andrej-karpathy-skills — **never drift**;
  only §5 is project-specific.
- **Workflow**: phase-by-phase, stop and verify on user request. Each phase
  lands as one or more commits in PR #7.

## Phase 1 — Discovery (non-destructive) ✅ done

- [X] T1 Rewrite `CLAUDE.md` — Karpathy verbatim §1–§4 + project §5.
- [X] T2 Single-file spec template at `docs/templates/SPEC.md` (TDD-explicit:
  Acceptance tests written before implementation, Tasks default to test-first
  ordering, escape hatch for non-behavioural changes).
- [X] T3 Initial `CHANGELOG.md` — 001–007 ported as 5–15-line sections each,
  ascending order, TOC + per-section explicit `<a id>` anchors.
- [X] T4 Translate every durable doc to English: `CLAUDE.md`,
  `CHANGELOG.md`, `docs/templates/SPEC.md`, `docs/PRD.md`,
  `docs/ARCHITECTURE.md`, `OVERHAUL.md`. (`docs/ARD.md` and `README.md`
  pending — moved to Phase 2.)
- [X] T5 Move durable docs into `docs/`: `PRD.md` / `ARCHITECTURE.md` /
  `ARD.md`. Spec template → `docs/templates/SPEC.md`. All cross-references
  updated (CLAUDE.md, README.md, sibling-relative paths inside `docs/`).
- [X] T11 (early) `.coderabbit.yaml` path filters cleaned —
  `specs/**` / `.specify/**` lines removed; `!docs/**` and the root markdown
  files (`!CONSTITUTION.md` / `!CLAUDE.md` / `!CHANGELOG.md` / `!README.md`
  / `!OVERHAUL.md`) added.

## Phase 2 — Apply (destructive, in this PR)

> Recommended ordering: T6 → T7 → T12 → T8 / T9 / T10 (parallel-safe) → T13.
> Reason: translate ARD before appending D23 (T12); deletion tasks run after
> all references and the `D23` entry are settled, so a stale link never sits
> in committed state.

- [ ] T6 Translate `docs/ARD.md` and `README.md` to English.
  - `docs/ARD.md`: 22 entries (D1–D22) + the format guide at the bottom.
    Keep section headers (`## DNN — title`) and decisions append-only —
    do NOT renumber, do NOT reorder. The `**근거 spec**` rows already
    reference `../specs/<feature>/`; in this commit, change them to point
    to the relevant `CHANGELOG.md#vNNN` anchor instead (since `specs/`
    will disappear in T8). Translate body prose only.
  - `README.md`: install / quickstart / CLI surface / Telegram surface /
    development / documentation map / branch+spec workflow. Korean prose
    → English; preserve code blocks, command examples, identifiers.
- [ ] T7 `.specify/memory/constitution.md` → `CONSTITUTION.md` (root) via
  `git mv` so rename detection survives.
  - Translate body to English (currently Korean+English mixed).
  - Soften §V wording so "spec-driven" allows the lightweight single-file
    form (don't require plan/research/contracts/quickstart split). Keep
    the seven NON-NEGOTIABLE principles intact and the "30-min trivial fix
    exemption" wording as-is.
  - Update the `<!-- SYNC IMPACT REPORT -->` block at the top: bump
    version to `1.2.0` (MINOR — additive relaxation of §V form), add a
    note about the move + English translation + spec-form softening.
  - Update cross-refs: `.specify/memory/constitution.md` → `CONSTITUTION.md`
    in any remaining file (`docs/PRD.md`, `docs/ARCHITECTURE.md`,
    `docs/ARD.md`, `README.md`, `CHANGELOG.md` historical mention is
    fine to leave as historical pointer).
- [ ] T8 `git rm -r specs/` (information already in `CHANGELOG.md`).
  No follow-up cross-ref work expected — Phase 1 / T6 already replaced
  spec-folder references with CHANGELOG anchors.
- [ ] T9 `git rm -r .specify/` entirely, after confirming
  `.specify/memory/constitution.md` was promoted in T7. Also touches
  `.specify/extensions*`, `.specify/scripts/`, `.specify/templates/`,
  `.specify/integrations*`, `.specify/workflows/`, `.specify/feature.json`,
  `.specify/init-options.json`, etc.
- [ ] T10 `git rm -r .claude/skills/speckit-*` (14 packages):
  speckit-analyze / -checklist / -clarify / -constitution / -git-commit /
  -git-feature / -git-initialize / -git-remote / -git-validate / -implement
  / -plan / -specify / -tasks / -taskstoissues.
- [ ] T12 Append `D23 — process overhaul` to `docs/ARD.md`. Body in English
  (the rest of ARD will be English after T6). Reference: PR #7,
  `CHANGELOG.md#v-process-overhaul`. Constitution impact: §V wording
  softened (additive — invariant relaxation, MINOR bump v1.1.0 → v1.2.0).
- [ ] T13 Final commit: `git rm OVERHAUL.md` and remove the dangling
  `!OVERHAUL.md` line from `.coderabbit.yaml`.

## Validation gates per task

- After T6: `grep -rn "한국어\|specs/<feature>" docs/` — should be empty
  (or only intentional historical references).
- After T7: file at `CONSTITUTION.md` exists, opens in English, version
  header reads `1.2.0`. `grep -rn ".specify/memory/constitution.md" --include="*.md"`
  returns only Phase-history mentions in CHANGELOG/OVERHAUL/D-entry.
- After T8/T9/T10: `ls specs/ .specify/ .claude/skills/ 2>&1 | grep -i
  speckit\|specs\|specify` is empty for relevant prefixes.
- After T12: `docs/ARD.md` ends with D23 and the format guide.
- After T13: `OVERHAUL.md` no longer exists, PR diff shows it removed.

## Intentional retention

- `docs/PRD.md` / `docs/ARCHITECTURE.md` / `docs/ARD.md` (relocated, but
  preserved).
- ARD entries D1–D22 (append-only — D23 added).
- All execution assets (code, tests, `pyproject.toml`, …) untouched.
- `.gitignore` (no change), `.coderabbit.yaml` (only path filters changed).

## Non-goals

- No source / test code is touched in this PR.
- The constitution body keeps its 7 principles; only §V wording is softened
  in T7.
- Existing 22 ARD entries are not edited (only D23 appended in T12).

## How to resume from a cold start

1. **Read this file first**: `OVERHAUL.md` describes the entire plan and
   current Phase 1 ✅ / Phase 2 pending status.
2. **Skim the new convention**: `CLAUDE.md` (§1–§4 universal, §5 project)
   + `docs/templates/SPEC.md` (TDD-explicit single-file spec format) +
   `CHANGELOG.md` intro (append-only, ascending, TOC).
3. **Branch state**: `chore/process-overhaul`, PR #7 (draft). Last commit
   was `336888c` (move into `docs/` + cross-refs). Run `git log --oneline
   chore/process-overhaul ^main` for the full overhaul commit list.
4. **Resume Phase 2 at T6** (translate `docs/ARD.md` + `README.md`).
   Recommended order is in the Phase 2 section above. Stop and ask the
   user to verify after each task or small group.
5. **Don't drift on the verbatim sections**. `CLAUDE.md` §1–§4 must remain
   the exact text from
   forrestchang/andrej-karpathy-skills/main/CLAUDE.md — verify with a
   `curl` if uncertain.
6. **Verification rule**: phase-by-phase. Do NOT chain T6→T13 in one shot
   unless explicitly told to. Default is "land one task or natural cluster,
   push, ask user to check on GitHub, await sign-off, continue."
