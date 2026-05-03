---
name: validate-spec
description: 이미 작성된 remotask spec 파일에 정적 룰을 적용해 머지 게이트로 작동하는 스킬. SPEC.md 템플릿 7개 섹션 존재, 파일명 형식, NNN 충돌, 본문 영어 여부, AT가 Given/When/Then 형식인지, Tasks 첫 항목이 test-first인지, ARCHITECTURE/PRD 영향이 Notes에 명시됐는지 같은 룰 기반 검사를 수행하고 PASS/FAIL 보고서를 반환한다. `create-spec`의 chain에서 풀 드래프트 작성 직후 자동 호출되며, 단독 호출도 가능 (남이 쓴 spec의 PR 리뷰, 외부 spec 인계 시 게이트). 7원칙 평가는 `check-constitution`이 별도로 처리하므로 이 스킬은 정적 룰만 본다. 트리거 예 — 한국어: "스펙 검증해줘", "스펙 lint", "스펙 게이트 돌려줘", "스펙 형식 체크", "008 검증"; 영어: "validate-spec", "spec lint", "/validate-spec".
---

# validate-spec

`specs/NNN-<name>.md` 한 파일을 입력으로 받아, 정적 룰 셋을 적용한다. 이 스킬은 *형식 / 구조 게이트*만 본다 — 7원칙 평가는 `check-constitution`이 별도로 한다. 두 게이트를 분리한 이유는 룰의 성격이 다르기 때문 (정적 grep vs. 도메인 추론).

## 파이프라인 위치

```
[create-spec] → [validate-spec] ← 여기 → [check-constitution] → [sharpen-spec] → 완성
```

전체 그림은 `.claude/skills/spec-pipeline.md` 참조.

## 언제 쓰나

- `create-spec` chain의 첫 게이트로 자동 호출.
- 단독 호출: PR 리뷰 시 spec이 형식을 지키는지 빠르게 체크. 외부에서 인계받은 spec.

## 입력

- spec 파일 경로 (예: `specs/008-dm-channel-mode.md`).
- 명시되지 않으면 `specs/`에서 가장 최근 변경 파일을 후보로 제시.

## 룰 셋

각 룰은 **PASS / FAIL** 둘 중 하나를 반환하고, FAIL이면 한 줄 짜리 evidence (어디가 어긋났는지)를 함께 낸다. 룰 목록:

### R1. 파일명 형식

- 패턴: `NNN-<kebab-name>.md`. NNN은 zero-pad 3자리, name은 영문 kebab-case 2~5단어.
- 예: `008-dm-channel-mode.md` ✓ / `008_dmChannelMode.md` ✗ / `8-dm.md` ✗.

### R2. NNN 충돌 / 누락

- `CHANGELOG.md` 마지막 `## NNN — ...` 헤더와 `specs/` 하위 NNN-prefix 중 max를 본다.
- 새 spec의 NNN이 max + 1이 아니면 FAIL (충돌하거나 건너뜀).
- 단독 호출 시: 동일 NNN이 `specs/` 또는 CHANGELOG에 이미 등장하면 FAIL.

### R3. 7개 섹션 존재

다음 헤더가 모두 등장:

- `## Motivation`
- `## Behavior`
- `## Acceptance tests`
- `## Tasks`
- `## Out-of-scope`
- `## Constitution check`
- `## Notes`

하나라도 빠지면 FAIL + 누락된 섹션 이름.

### R4. 본문 영어

- 한글 문자 비율이 임계값 (2%) 초과면 FAIL. durable docs 영어 통일 (ARD D23).
- spec 본문에 쓰인 식별자(`/cancel`, `[KEY]`, `audit.log` 등)는 영어로 간주.

### R5. AT 형식 — Given/When/Then

- `## Acceptance tests` 섹션에 `AT1`..`ATn` 번호가 있고, 각 항목이 `Given <state>, when <action>, then <observable>` 패턴 또는 명백한 동등 표현 (예: "On startup, when ..., then ...").
- 행동 변화 없는 변경이라면 "기존 X 테스트가 이미 이 변경을 커버한다, 그래서 추가 테스트 없음" 한 줄이면 PASS.
- "make X work" / "ensure Y works" 같은 goal-form은 FAIL.

### R6. Tasks test-first

- `## Tasks` 섹션에 `T1`..`Tn` 번호가 있고, **T1이 테스트 작성 / red 단계**여야 한다 — 키워드: "test", "red", "failing".
- 행동 변화 없는 변경이면 R5 면제 조건과 같이 면제 (Acceptance tests 섹션의 면제 한 줄과 paired).

### R7. NEEDS CLARIFICATION 마커

- `[NEEDS CLARIFICATION:` 문자열이 spec 본문에 남아있는지 grep.
- 남아있으면 **FAIL이 아니라 WARN** — `sharpen-spec`이 닫을 책임이지 형식 룰의 책임은 아니다. 다만 보고에 마커 개수를 표시해 다음 단계가 이걸 닫아야 한다는 신호.

### R8. Notes — ARCHITECTURE/PRD 영향 명시

- spec이 시스템 shape을 바꾸는 변경이라면 (`Behavior` / `Tasks` 섹션에 새 컴포넌트, 새 DB 컬럼, 새 config 키, 새 stdout 라인, 새 의존성 같은 키워드가 등장) → `## Notes` 섹션에 ARCHITECTURE.md 또는 PRD.md 어느 절이 함께 변해야 하는지 한 줄 명시되어야 한다 (`CLAUDE.md` §5 규칙 3).
- 명시 안 됐으면 FAIL.
- shape 변화 신호가 없는 spec (순수 리팩터, docs-only)은 면제.

이 룰은 `scan-impact`로 분리될 후보였으나 (현재는 백로그), 일단 `validate-spec` 안의 한 룰로 흡수해 운용한다 — `.claude/skills/spec-pipeline.md` 참조.

## 워크플로우

### 1. 룰 적용

위 R1..R8을 순서대로 적용. 각 룰은 PASS / FAIL / WARN 중 하나.

룰들은 grep + 정규식 / 파일 시스템 확인으로 모두 처리 가능 — 도메인 추론은 사용하지 않는다 (그건 `check-constitution`의 역할).

### 2. 보고서

다음 형식으로 사용자에게 보고:

```
validate-spec @ specs/008-dm-channel-mode.md

PASS
- R1 파일명 형식
- R3 7개 섹션 존재
- R5 AT Given/When/Then
- R6 Tasks test-first
- R8 Notes에 ARCHITECTURE 영향 명시

FAIL
- R4 본문 영어 — 한글 비율 7.3% (임계값 2%). 본문에 한국어 단락이 섞여 있음 (line 42–48).

WARN
- R7 NEEDS CLARIFICATION 마커 3개 — sharpen-spec이 닫을 항목 (line 55, 88, 134).

결과: 1 FAIL, 1 WARN. 게이트 통과 못 함.
```

PASS 항목은 한 줄, FAIL은 두 줄 (룰 + evidence), WARN은 두 줄.

### 3. 다음 단계

- 모두 PASS (또는 FAIL 없음, WARN만): chain 다음 단계 (`check-constitution`)로 진행.
- FAIL이 있음: 사용자에게 보고하고 결정을 받는다 — (a) 스킬이 자동 수정 가능한 룰 (R1 파일명, R3 섹션 누락의 경우 빈 헤더 추가)은 사용자 동의 시 수정. (b) 도메인 판단이 필요한 룰 (R4 본문 영어, R5 AT 형식)은 `sharpen-spec`에 넘기거나 사용자가 직접 고친다.

## 흔한 실수

- **PASS만 보고하고 WARN을 빼먹기.** 마커는 FAIL이 아니지만 다음 단계 (sharpen-spec)에 신호로 넘어가야 한다.
- **R8을 무차별 적용.** 순수 리팩터 / docs-only는 ARCHITECTURE 영향이 없으므로 면제. 키워드 신호 (Behavior에 새 컴포넌트, 새 컬럼 등)가 있을 때만 강제.
- **도메인 추론 시도.** "이 spec이 §III를 위반하나?" 같은 판단은 이 스킬의 책임이 아니다. `check-constitution`이 한다.
- **자동 수정 폭주.** R1 (파일명) 같이 명백한 룰만 자동 수정 후보. R5 / R8처럼 도메인이 섞이면 사용자에게 결정을 넘긴다.

## 작성 톤

- 사용자에게 보고하는 텍스트는 **한국어**로.
- 룰 식별자 (R1..R8), 룰 이름, evidence는 짧게.
- spec 파일을 자동 수정할 때 본문 톤은 영어 유지 (durable docs 컨벤션).
