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

- **Branch**: `chore/process-overhaul`, branched from `main` after PR #6.
- **Existing `specs/` folders**: extracted into `CHANGELOG.md` sections, then
  the entire `specs/` folder is removed.
- **speckit residue**: removed entirely. `.claude/skills/speckit-*` (7 skill
  packages), `.specify/templates/`, `.specify/scripts/`, `.specify/extensions*`,
  `.specify/init-options.json`, `.specify/feature.json`. The constitution
  (`.specify/memory/constitution.md`) is the only file preserved — promoted
  to the root as `CONSTITUTION.md`.
- **Doc layout**: the four durable docs split between root and `docs/`:
  - root: `CONSTITUTION.md`, `CLAUDE.md`, `CHANGELOG.md`, `README.md`
  - `docs/`: `PRD.md`, `ARCHITECTURE.md`, `ARD.md`
  - `docs/templates/SPEC.md`: single-file spec template

## Phase 1 — Discovery (non-destructive) ✅

- [X] T1 Rewrite `CLAUDE.md` — Karpathy verbatim §1–§4 + project §5.
- [X] T2 Single-file spec template at `docs/templates/SPEC.md` (TDD-explicit).
- [X] T3 Initial `CHANGELOG.md` — 001–007 ported as 5–15-line sections each.
- [X] T4 Translate all durable docs to English (CLAUDE / CHANGELOG / SPEC
  template / PRD / ARCHITECTURE so far; ARD / README pending).
- [X] T5 Move `PRD.md` / `ARCHITECTURE.md` / `ARD.md` into `docs/`; move
  `.spec-template.md` → `docs/templates/SPEC.md`. Cross-references updated.

## Phase 2 — Apply (destructive, in this PR)

- [ ] T6 Translate `docs/ARD.md` and `README.md` to English (in their new
  homes).
- [ ] T7 `.specify/memory/constitution.md` → `CONSTITUTION.md` (root). Content
  preserved. §V wording softened so "spec-driven" allows the lightweight form.
- [ ] T8 Delete `specs/` (information already in `CHANGELOG.md`).
- [ ] T9 Delete `.specify/` entirely.
- [ ] T10 Delete `.claude/skills/speckit-*` (7 packages).
- [ ] T11 `.coderabbit.yaml` path filters cleaned up — drop `specs/**` and
  `.specify/**` entries; review `CONSTITUTION.md` / `CHANGELOG.md` /
  `OVERHAUL.md` / `docs/**`.
- [ ] T12 Append `D23 — process overhaul` entry to `docs/ARD.md`.
- [ ] T13 Delete `OVERHAUL.md` itself (final commit of this PR).

## Intentional retention

- `docs/PRD.md` / `docs/ARCHITECTURE.md` / `docs/ARD.md` (relocated, but
  preserved).
- ARD entries D1–D22 (append-only — D23 added).
- All execution assets (code, tests, `pyproject.toml`, …) untouched.
- `.gitignore`, `.coderabbit.yaml` etc. — only path filters updated.

## Non-goals

- No source / test code is touched in this PR.
- The constitution body keeps its 7 principles; only §V wording is softened.
- Existing 22 ARD entries are not edited (only D23 appended).
