# CLAUDE.md

Behavioral guidelines for AI agents working in this repo. §1~§4 are universal
(adapted from forrestchang/andrej-karpathy-skills); §5 is project-specific —
where the truth lives in this repo and how new work is recorded.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial
tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes,
simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```text
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it
work") require constant clarification.

## 5. Project Conventions (remotask)

This project keeps four durable documents at the root. Treat each as the
**source of truth (SoT)** for its layer; in case of conflict the order is
left-to-right.

| Layer | File | What it answers |
|-------|------|-----------------|
| 원칙 | [`CONSTITUTION.md`](./CONSTITUTION.md) | 절대 어기지 않는 원칙 (NON-NEGOTIABLE) |
| 제품 | [`PRD.md`](./PRD.md) | 누가, 왜, 무엇을 만드는가 / MVP 범위 / 시나리오 |
| 시스템 정의 | [`ARCHITECTURE.md`](./ARCHITECTURE.md) | 현재 시점 시스템이 어떻게 생겼는가 |
| 결정 이력 | [`ARD.md`](./ARD.md) | 왜 이 시스템 구조를 골랐는가 (D1, D2, …) |

History of completed work lives in [`CHANGELOG.md`](./CHANGELOG.md) — one
short section per feature with PR and ARD references. Append-only.

### Working rules

1. **Constitution은 절대 우위.** 충돌 시
   `CONSTITUTION.md` > `PRD.md` > `ARCHITECTURE.md` > `ARD.md` > 일반 문서.
   헌법 amend가 필요하면 별도 PR로 진행.
2. **Spec-driven, but lightweight.** 비-trivial 변경은 `specs/NNN-<name>.md`
   **단일 파일** 한 개로 명세한다 (motivation + behavior + acceptance +
   tasks 인라인). 폴더·plan/research/contracts/quickstart 분리 금지. 30분
   미만·1파일 이내 버그 픽스는 spec 면제.
3. **ARCHITECTURE.md와 ARD.md는 같은 PR에서 갱신한다.** 시스템 모습이 변하면
   `ARCHITECTURE.md`가, 그 결정이 새로우면 `ARD.md`에 새 entry(`DNN`)가
   추가되어야 한다. 옛 entry는 덮어쓰지 않고 새 entry로 갱신/대체한다.
4. **PRD는 제품 layer**다. 디테일(스키마·API 시그니처·디렉토리 트리 등)은
   PRD가 아니라 ARCHITECTURE.md / spec / 코드 자체에서 찾는다.
5. **Feature 머지 시 CHANGELOG.md에 한 섹션 추가.** PR 링크 + 핵심 변경 요약
   + 관련 ARD entry 번호. 5~15줄.
6. **삭제·이전된 spec 파일은 git history에 남는다.** 머지 후 spec 파일은
   유지하지 않아도 무방하다 (CHANGELOG가 SoT).
