---
name: create-spec
description: remotask 프로젝트에 새 기능을 추가하거나 기존 동작을 의미 있게 바꿀 때, `specs/NNN-<name>.md` 단일 파일 spec의 풀 드래프트를 작성하는 스킬. CONSTITUTION → PRD → ARCHITECTURE → ARD 네 계층의 source-of-truth와 `docs/templates/SPEC.md`를 직접 읽어 모든 섹션을 채운다. 작성 직후 `validate-spec` → `check-constitution` → `sharpen-spec`을 차례로 chain해 정적 룰 / 7원칙 / 모호함을 닫는다. 사용자가 'spec' 또는 '스펙'이라는 단어를 쓰지 않더라도 새 기능을 정리하거나 변경을 계획하려는 의도가 보이면 적극적으로 사용한다. 트리거 예 — 한국어: "스펙 만들어줘", "스펙 작성해줘", "스펙 짜줘", "스펙 초안", "008 스펙", "새 기능 스펙 작성", "이 변경 스펙으로 정리해줘", "기능 추가 정리해줘"; 영어: "create-spec", "write a feature spec", "draft a spec", "/create-spec". 단, 30분 미만이고 ≤1 파일만 건드리는 사소한 버그 픽스에는 사용하지 말 것 (Constitution §V 예외).
---

# create-spec

remotask 프로젝트의 새 기능 / 비-사소한 변경에 대해 단일 파일 spec의 **풀 드래프트**를 `specs/NNN-<name>.md`에 작성한다. 이 스킬은 작성까지만 책임진다 — 정적 룰 검증·헌법 평가·모호함 좁히기는 작성 직후 자동으로 다음 스킬에 위임한다.

## 파이프라인 위치

```
사용자 자연어
    ↓
[create-spec] ← 여기
    ↓
[validate-spec]       (정적 룰 게이트)
    ↓
[check-constitution]  (7원칙 게이트)
    ↓
[sharpen-spec]        (사용자 Q&A로 모호함 좁히기)
    ↓
머지 가능한 spec
```

전체 그림은 `.claude/skills/spec-pipeline.md` 참조.

## 언제 쓰지 않나

- **CONSTITUTION §V 예외** — 30분 미만 + ≤1 파일만 건드리는 사소한 버그 픽스. 사용자가 그런 류라고 명시하면 spec 없이 곧장 코드로 가도 된다.
- **헌법 자체의 수정** — `CONSTITUTION.md`를 직접 고치는 작업은 별도 PR로 처리하라는 §V 규칙이 있다. 이 스킬로 만들지 말 것.

## 워크플로우

### 1. 컨텍스트 로드 (한 번에)

스펙은 4계층 위에 얹는다. 다음을 먼저 모두 읽는다 (병렬로 읽으면 빠르다):

- `CONSTITUTION.md` — 7원칙 본문.
- `docs/PRD.md` — Phase / MVP scope / 페르소나 시나리오.
- `docs/ARCHITECTURE.md` — 현재 시스템 shape.
- `docs/ARD.md` — D1..DNN. 과거 결정과의 충돌·정합성 판단.
- `CHANGELOG.md` — 최근 feature 흐름과 마지막 NNN 헤더.
- `docs/templates/SPEC.md` — 템플릿 그 자체.
- `specs/` 디렉토리 (있으면) — 기존 NNN-prefix 패턴 / 작성 톤.

이 7개를 미리 읽지 않으면 풀 드래프트 채울 때 다시 돌아가야 해서 비싸다. 한 번에 끝내라.

읽으면서 — **이 변경과 직접 다투거나 정당화의 근거가 되는 ARD 번호** (D1..DNN)를 한 줄짜리 메모로 모아둔다. 보통 2~4개 나온다. 3단계 Constitution check / Notes에서 인라인 D번호로 다시 쓴다. 풀 드래프트 단계에서 이걸 잘 심어두면 `check-constitution` 게이트를 한 번에 통과한다.

### 2. 다음 NNN 결정

마지막 NNN을 두 곳에서 찾아 max + 1을 쓴다:

- `CHANGELOG.md`의 마지막 `## NNN — ...` 섹션 헤더.
- `specs/NNN-*.md` 파일 중 가장 큰 prefix.

두 값이 다르면 더 큰 쪽 + 1. 항상 zero-pad 3자리 (`008`, `012`).

### 3. 풀 드래프트

`docs/templates/SPEC.md`의 모든 섹션을 채운다. 빈 섹션을 남기지 말고, 추론으로 채운 곳이나 단정 짓기 어려운 곳은 `[NEEDS CLARIFICATION: <짧은 질문>]` 마커를 그 자리에 둔다 — 이 마커는 다음 스킬 (`sharpen-spec`)에서 사용자와 Q&A로 닫는다. **이 단계에서는 마커를 닫으려고 사용자에게 묻지 마라.**

섹션별 가이드:

**Motivation** — 왜 / 왜 지금. PRD §1 Background나 §3 시나리오에 닿으면 명시적으로 인용. 1~3 문단.

**Behavior** — operator / 시스템 관점에서 무엇이 바뀌는가. 구현 detail (스키마, 함수 시그니처, 디렉토리 트리)은 여기에 넣지 않는다 — `CLAUDE.md` §5 규칙 4. before/after나 시나리오 형식이 잘 맞는다.

**Acceptance tests** — 각 항목은 **failing-now / passing-when-done** assertion. "make X work" goal이 아니라 Given/When/Then 또는 동등한 name+assert 형태여야 1:1로 테스트 함수에 매핑된다. 행동 변화가 없는 변경 (순수 리팩터, docs-only, rename)이면 리스트 대신 한 줄로 "기존 X 테스트가 이미 이 변경을 커버한다"라고 쓰고, Tasks의 test-first 단계도 생략한다.

**Tasks** — 기본 순서는 test-first: T1 = AT 테스트 작성 + red 확인 → T2.. = AT를 하나씩 green으로 → T(last) = 전체 스위트 + 수동 smoke. 행동 변화 없는 변경이면 자연스러운 순서로.

**Out-of-scope** — 명시적으로 제외하는 것. 후속 spec 후보. 머지 시점의 scope 다툼을 줄여 준다.

**Constitution check** — 7원칙 각각에 대해 PASS / waiver 한 줄. `I. External SoT` / `II. Daemon-Centric` / `III. Strict Session Isolation` / `IV. MVP-First` / `V. Spec-Driven` / `VI. Security by Default` / `VII. Observability & Auditability`. 각 원칙 평가에 직접 영향을 주는 과거 ARD 결정이 있으면 인라인으로 D번호 인용. 자세한 평가·waiver 적정성·인용 누락은 다음 스킬 (`check-constitution`)이 한 번 더 짚어주지만, 1단계에서 모은 D번호는 여기서 미리 심어두는 게 비용 절감이다.

**Notes** — 새 ARD 항목이 필요해 보이면 여기에 명시 (예: `This change introduces D24 candidate: <one-liner>`). 시스템 shape이 바뀌는 결정이라면 ARCHITECTURE.md / PRD.md 어느 절이 함께 변해야 하는지도 한 줄 적어둔다 (`CLAUDE.md` §5 규칙 3).

### 4. 파일명 + 파일 작성

`specs/NNN-<short-kebab-name>.md`로 쓴다. `<short-kebab-name>`은 5단어 이내 영문 kebab-case (예: `008-dm-channel-mode`, `009-slack-adapter-extraction`). 후보 2~3개를 사용자에게 제시하고 고르게 한다 — 이름은 git 히스토리에 영구히 남으므로 한 번 더 묻는 비용은 작다.

이름이 정해지면 파일을 쓴다. `specs/` 디렉토리가 없으면 만든다 (현재 첫 사용 시점이라면 정상).

### 5. 다음 스킬로 chain

파일을 쓴 직후, 사용자에게 한 줄로 알리고 다음 단계로 자동 진행한다:

```
008-dm-channel-mode.md 풀 드래프트를 작성했습니다. 이어서
1) validate-spec — 정적 룰 검증
2) check-constitution — 7원칙 + ARD 인용 검토
3) sharpen-spec — 남은 모호함 Q&A로 좁히기
를 차례로 진행하겠습니다. 중간에 멈추거나 건너뛰고 싶으시면 말씀해주세요.
```

그 다음 `validate-spec` 스킬을 호출한다. validate가 PASS면 `check-constitution`. check가 PASS면 `sharpen-spec`. 한 단계라도 FAIL이면 사용자에게 보고하고 사용자 결정에 따른다 (예: 자동 수정 / 건너뛰기 / 중단).

마지막 sharpen-spec까지 끝나면 한 단락으로 마무리:

- 다음 단계: T1 (실패하는 테스트 작성) → red 확인 후 구현 진입.
- 머지 시 spec과 구현은 같은 PR (`CONSTITUTION.md` L260).
- 머지 후 `CHANGELOG.md` 하단에 5~15줄 섹션 append (`CONSTITUTION.md` L263).
- spec 파일 자체는 머지 후 disposable — `CHANGELOG.md`가 durable record다 (`CLAUDE.md` §5 규칙 6).

## 작성 톤

- spec 본문은 **영어**로. durable docs는 모두 영어로 통일됨 (ARD D23).
- 사용자와의 대화는 **한국어**로 (이 프로젝트의 working language).
- placeholder 금지. 모르는 칸은 빈칸이 아니라 `[NEEDS CLARIFICATION: ...]` 마커로 두고 sharpen 단계에서 메운다.
- "이 spec은 ..." 같은 자기 언급 헤더 금지. SPEC.md 헤더는 그냥 `# NNN — short title`로 시작한다.
- 영어로 쓸 때도 SPEC.md 템플릿이 보여주는 차분한 영문체 — 마케팅 문구 / 강한 형용사는 피한다.

## 흔한 실수

- **마커 닫겠다고 사용자에게 묻기.** 이 스킬은 작성까지만. 모호한 곳은 마커로 두고 다음 스킬에 넘긴다. 두 스킬을 묶어서 호출하지 마라.
- **Behavior에 구현 detail을 넣는다.** 함수 시그니처 / SQL 컬럼 / 디렉토리 트리는 다른 곳으로 보낸다. CLAUDE.md §5 규칙 4.
- **AT를 goal로 쓴다.** "make X work"가 아니라 "Given <state>, when <action>, then <observable>" 형태가 1:1 테스트 매핑을 가능하게 한다.
- **Phase를 무시한다.** Phase 5 변경을 Phase 1 spec으로 끼워 넣으면 §IV waiver 없이 머지가 막힌다. waiver의 무게와 단순 대안을 사용자가 인지하고 선택하게 하라 (이건 sharpen-spec이 다시 묻겠지만, 풀 드래프트에서도 짚어둔다).
- **NNN을 한 곳만 본다.** `specs/`와 `CHANGELOG.md` 양쪽을 모두 보고 max + 1을 잡지 않으면 번호가 충돌한다.
- **선행 ARD를 침묵한다.** 이 변경과 직접 다투는 과거 결정 (예: 동시성 ↔ `D16`, presentation layer ↔ `D8/D19`, audit 구조 ↔ §VII / `D23`)을 풀 드래프트에서 짚지 않으면 `check-constitution`이 잡지만 거기서 다시 채우는 비용이 든다. 1단계 ARD 메모를 본문에 미리 심어라.
