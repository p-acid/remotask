<!-- SPECKIT START -->
This project is developed and maintained against a five-layer documentation
stack. Treat each document as the **source of truth (SoT)** for its layer:

| Layer | File | What it answers |
|-------|------|-----------------|
| 원칙 | [`.specify/memory/constitution.md`](./.specify/memory/constitution.md) | 절대 어기지 않는 원칙 (NON-NEGOTIABLE 7개) |
| 제품 | [`PRD.md`](./PRD.md) | 누가, 왜, 무엇을 만드는가 / MVP 범위 / 시나리오 |
| 시스템 정의 | [`ARCHITECTURE.md`](./ARCHITECTURE.md) | 현재 시점 시스템이 어떻게 생겼는가 |
| 결정 이력 | [`ARD.md`](./ARD.md) | 왜 이 시스템 구조를 골랐는가 (D1, D2, …) |
| 변경 명세 | [`specs/<feature>/`](./specs) | 각 변경의 spec / plan / contracts / tasks / quickstart |

Working rules for AI agents:

1. **Constitution은 절대 우위.** 충돌 시 헌법 > PRD > ARCHITECTURE > ARD > spec >
   일반 문서. 헌법 amend가 필요하면 `/speckit-constitution`으로 정식 절차.
2. **모든 비-trivial 변경은 spec-driven** (헌법 §V). `/speckit-specify` → plan →
   tasks → implement 흐름을 따른다. 30분 미만 1파일 이내 버그 픽스만 예외.
3. **ARCHITECTURE.md와 ARD.md는 같은 PR에서 갱신한다.** 시스템 모습이 변하면
   ARCHITECTURE.md가, 그 결정이 새로우면 ARD.md에 새 entry(DNN)가 추가되어야
   한다. 옛 entry는 덮어쓰지 않고 새 entry로 갱신/대체한다.
4. **PRD는 제품 layer**다. 디테일(스키마·API 시그니처·디렉토리 트리 등)은 PRD가
   아니라 ARCHITECTURE.md / spec / 코드 자체에서 찾는다. PRD에 디테일을 다시 박지
   않는다.
5. **Active feature plan 포인터**(아래)는 `/speckit-plan`이 갱신한다. 다른 곳에서
   임의로 바꾸지 않는다.

Active feature plan: *(none — main 브랜치 기준 idle)*

Prior features (foundational; still authoritative):
- `specs/006-remove-termination-aliases/plan.md` — deprecation 별칭 4개 완전 제거
- `specs/005-dm-channel/plan.md` — `/cancel` 캐노니컬, `[KEY]` prefix chokepoint, 별칭 deprecation
- `specs/004-slash-commands/plan.md` — setMyCommands, `/run` grammar, `/status`, slash-command dispatch
- `specs/003-e2e-demo/plan.md` — placeholder worker, operator-stop loop, FINAL line 프로토콜
- `specs/002-telegram-trigger/plan.md` — listener, dispatcher, topic, audit, worker scaffolding
- `specs/001-cli-bootstrap/plan.md` — paths, schema V0001, daemon shell

Always-applies:
- [`.specify/memory/constitution.md`](./.specify/memory/constitution.md) — project principles (v1.1.0; Principle III amended per ARD D19)
- [`PRD.md`](./PRD.md) — product-level context
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — current system definition
- [`ARD.md`](./ARD.md) — architecture decision record
<!-- SPECKIT END -->
