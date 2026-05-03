# NNN — short title

> Single-file spec. Lives at `specs/NNN-<short-name>.md`. After merge, the file
> need not be retained — git history and `CHANGELOG.md` carry the durable record.

> **Test-first.** The *Acceptance tests* section below is the concrete contract;
> the tests that codify it are written **before** any implementation. The
> *Tasks* section orders work as: write failing tests (red) → implement until
> green → manual smoke if applicable. Skip the test-first cycle only when the
> change has no behavioural surface to verify (pure refactor with existing
> coverage, docs-only change, infra rename) and say so explicitly under
> *Acceptance tests*.

**Status**: draft / in-review / merged
**PR**: #NN (filled in after merge)
**Related ARD**: D?? (if applicable)

## Motivation

Why this change, why now? 1–3 paragraphs.

## Behavior

What changes from the operator's / system's perspective? User scenarios or
before/after comparison. Implementation detail does not belong here.

## Acceptance tests

Each item is a concrete, observable test that will be written **before**
implementation. Frame each as a *failing-now / passing-when-done* assertion,
not as a goal. Prefer Given / When / Then or an equivalent name + assertion
shape so the intended test maps 1:1 to a future test function.

- [ ] AT1 — Given <state>, when <action>, then <observable outcome>.
- [ ] AT2 — …
- [ ] AT3 — …

For changes with no behavioural surface (pure refactor, docs, rename, etc.),
replace the list with a single line stating what existing tests already
cover the change and why no new tests are required.

## Tasks

Ordered work units. **Default ordering for behavioural changes is test-first**:

- [ ] T1 — Write tests for AT1…ATn against the desired post-state. Run the
      suite: confirm each new test fails for the expected reason (red).
- [ ] T2 — Implement the smallest change that turns AT1 green.
- [ ] T3 — Implement the smallest change that turns AT2 green.
- [ ] T4 — …
- [ ] T(last) — Run the full suite + a manual smoke (when applicable). All
      acceptance tests green; no regression.

For non-behavioural changes, order tasks as is most natural and skip the
test-first phases — but note this explicitly under *Acceptance tests*.

## Out-of-scope

Items explicitly excluded from this change. Candidates for a follow-up spec.

## Constitution check

Affected sections (e.g., none / §III, §VI). No waiver / waiver with rationale.

## Notes

Side decisions, findings, references. Free-form. If a note grows, consider
promoting it to a new ARD entry.
