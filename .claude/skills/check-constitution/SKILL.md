---
name: check-constitution
description: 이미 작성된 remotask spec 파일이 7개 헌법 원칙(I External SoT / II Daemon-Centric / III Strict Session Isolation / IV MVP-First / V Spec-Driven / VI Security by Default / VII Observability & Auditability)을 모두 평가했는지, 영향 ARD 결정이 인라인 D번호로 인용됐는지, waiver의 3줄 형식(위반 / 왜 / 단순 대안 거부)이 채워졌는지를 검사하는 머지 게이트 스킬. `create-spec`의 chain에서 `validate-spec` 직후 자동 호출되며, 단독 호출도 가능 (헌법 amend 후 기존 spec 재검토, 외부 PR 리뷰). 정적 룰 검사는 `validate-spec`이 별도로 처리하고, 모호 지점 좁히기는 `sharpen-spec`이 별도로 처리한다 — 이 스킬은 *7원칙 + ARD 인용*만 본다. 트리거 예 — 한국어: "헌법 검사해줘", "헌법 체크", "Constitution check 돌려줘", "7원칙 평가", "ARD 인용 누락 있나 봐줘", "008 헌법"; 영어: "check-constitution", "constitution check", "/check-constitution".
---

# check-constitution

`specs/NNN-<name>.md` 한 파일을 입력으로 받아, `## Constitution check` 섹션 + spec 전반의 ARD 인용 패턴을 평가한다. 머지 게이트 — 7원칙 평가가 한 슬롯이라도 비어있거나 waiver 형식이 틀어져 있으면 PR이 머지 차단되어야 한다 (`CONSTITUTION.md` L266 / L307).

## 파이프라인 위치

```
[create-spec] → [validate-spec] → [check-constitution] ← 여기 → [sharpen-spec] → 완성
```

전체 그림은 `.claude/skills/spec-pipeline.md` 참조.

## 언제 쓰나

- `create-spec` chain의 두 번째 게이트로 자동 호출.
- 단독 호출: 헌법 amend (새 원칙 추가, 기존 원칙 wording 수정) 직후 기존 spec들 재검토. 외부 PR 리뷰 시 7원칙 적합성만 빠르게 보고 싶을 때.

## 입력

- spec 파일 경로.
- (선택) 헌법 amend 컨텍스트 — 단독 호출 시 어떤 amend로 인해 재검토하는지 한 줄.

## 사전 컨텍스트 로드

이 스킬은 도메인 추론을 한다 — 정적 grep만으로는 불가능하다. 다음을 먼저 읽는다:

- `CONSTITUTION.md` — 7원칙 본문 + 각 원칙의 NON-NEGOTIABLE 표시 / 단서.
- `docs/ARD.md` — D1..DNN 결정 본문. 어떤 D가 어떤 §원칙과 직접 닿는지 매핑.
- `docs/ARCHITECTURE.md` — 시스템 shape을 본다. spec의 변경이 ARCHITECTURE의 어느 절을 건드리는지 추론할 때 필요.
- spec 파일 자체.

## 평가 룰

### C1. 7원칙 슬롯 채워짐

- `## Constitution check` 섹션 안에 7원칙 모두 등장 — `I` / `II` / `III` / `IV` / `V` / `VI` / `VII`.
- 각 슬롯에 PASS / waiver 명시. "(영향 없음)" 같이 비어있는 한 줄도 OK이지만, 영향 있는 원칙이 한 줄짜리 PASS로 끝나면 FAIL (왜 PASS인지 한 단어라도 보강 필요).
- 슬롯 누락 시 FAIL + 어떤 원칙이 빠졌는지.

### C2. waiver 형식 (있을 경우)

waiver를 선언한 슬롯은 **3줄**이 모두 채워져야 한다 (`CONSTITUTION.md` L268~L271):

```
- (a) 어떤 원칙을 위반하는가
- (b) 왜 이 waiver가 필요한가
- (c) 더 단순한 대안을 왜 거부했는가
```

세 줄 중 한 줄이라도 비어있으면 FAIL. (c)줄이 *왜* 단순 대안이 안 되는지 명시 (예: "현재 Phase 머무르기는 사용자 페인 X를 해소하지 못하므로 거부").

### C3. 영향 ARD 인용 누락

이게 이 스킬의 핵심 추론. 다음을 매핑:

- spec의 변경 영역 (Behavior / Tasks 섹션)
- 헌법 원칙 (§I~§VII)
- 관련 ARD 결정 (D1..DNN)

자주 나오는 매핑 (참조용 — 실제로는 spec 본문을 보고 판단):

| 변경 영역 | 직결 원칙 | 직결 ARD |
|---|---|---|
| Tracker / 외부 SoT 변경 | §I | `D1` |
| Daemon ↔ client / IPC | §II | `D14`, `D15` |
| Worktree / branch / 격리 모델 | §III | `D8`, `D19` |
| Multi-session / 동시성 | §IV | `D16` |
| Phase 5 옵션 (Slack, Tauri, 외부 노출) | §IV | `D3`, `D10` |
| Spec 형식 / 작성 절차 | §V | `D18` (superseded), `D23` |
| 토큰 저장 / 노출 정책 | §VI | `D6` |
| Audit / observability 구조 | §VII | (현재 ARD에 직결 없음, §VII 본문 직접 인용) |
| Channel mapping (Telegram topic / DM / Slack) | §III 단서 (presentation layer) | `D8`, `D19` |
| Agent 대체 (Codex 등) / SDK 정책 | (없음, ARCHITECTURE level) | `D4`, `D5`, `D22` |

각 원칙 슬롯에서 — *그 원칙과 직접 닿는 ARD가 있는데 슬롯에 D번호가 인라인으로 등장하지 않으면* FAIL. 예: §III가 channel mapping 변경인데 D19 / D8이 인용되지 않았으면 FAIL.

ARD가 아예 없는 원칙 슬롯 (예: §VII는 현재 직결 D 번호가 없음)은 인용 강제 안 함 — 이 경우 헌법 본문 자체에 대한 한 줄짜리 분석 ("§VII의 'separate audit log' wording이 이 변경으로 의미가 바뀜")을 기대.

### C4. 새 ARD 후보 명시

spec이 시스템 shape을 바꾸는 결정을 도입한다면 (새 config 키 / 새 컴포넌트 / 새 stdout 라인 / 기존 ARD 결정의 *반전* 등) → `## Notes` 섹션에 새 ARD 후보가 명시되어야 한다:

```
This change introduces D24 candidate: <한 줄 요약>.
```

명시 안 됐으면 FAIL — 머지 후 reviewer가 ARD entry를 만들어야 하는데 한 줄 hint 없이는 매번 처음부터 분석하게 된다.

shape 변화 신호가 없는 spec (순수 리팩터, docs-only)은 C4 면제.

### C5. NON-NEGOTIABLE 위반 시도

`CONSTITUTION.md`에서 `(NON-NEGOTIABLE)` 마크가 붙은 원칙은 §I, §III. 이 두 원칙을 waiver로 처리하려는 spec은 **즉시 FAIL** — 헌법 amend 절차를 별도 PR로 거치지 않으면 머지 불가.

해당 spec은 사용자에게 다음을 안내:

- 헌법 amend가 진짜 의도라면 별도 PR로 진행 (`CONSTITUTION.md` L289 amendment procedure).
- 그게 아니면 spec 범위를 좁혀 NON-NEGOTIABLE을 건드리지 않는 형태로 다시 작성.

## 워크플로우

### 1. 사전 로드 + 룰 적용

위 사전 컨텍스트 4개 파일을 모두 읽고 C1..C5를 순서대로 적용.

### 2. 보고서

```
check-constitution @ specs/008-dm-channel-mode.md

PASS
- C1 7원칙 슬롯 모두 채워짐
- C2 waiver 형식 — waiver 없음, 면제
- C5 NON-NEGOTIABLE — 위반 없음

FAIL
- C3 §IV 슬롯에 D16 인용 누락. 이 변경은 multi-session 활성화이며 D16이 직결되는 결정 (Phase 3로 미룬 결정)이므로 슬롯에서 인라인 인용해야 함.
- C4 §VII 새 ARD 후보 — Notes에 D24 hint 없음. audit 통합은 §VII 본문의 'separate audit log' wording을 바꾸는 변경이므로 D24 후보 한 줄 명시 필요.

결과: 2 FAIL. 게이트 통과 못 함.
```

### 3. 다음 단계

- PASS: chain 다음 단계 (`sharpen-spec`)로 진행.
- FAIL: 사용자에게 보고하고 결정을 받는다.
  - C3 (인용 누락): `sharpen-spec`에서 한 라운드 안에 닫을 수 있는 항목으로 위임 가능 (마커처럼 처리).
  - C4 (새 ARD 후보 누락): 사용자가 D번호 후보 + 한 줄 요약을 답하면 Notes에 추가.
  - C5 (NON-NEGOTIABLE 시도): spec 자체를 재작성해야 하므로 chain 중단, 사용자가 방향을 다시 잡는다.

## 흔한 실수

- **C3을 grep으로만 본다.** "spec에 D19가 등장하는가"가 아니라 "*§III 슬롯 안에* D19가 인라인으로 인용됐는가"를 봐야 한다. 단순 등장은 충분 조건이 아님.
- **C4 면제 잘못.** 시스템 shape 변경의 신호 (새 config 키 / 새 컬럼 / 기존 결정 반전)를 놓치고 면제하면 D 번호가 없는 채로 머지된다 — 이후 reviewer가 ARD를 처음부터 분석하게 된다.
- **NON-NEGOTIABLE을 일반 waiver처럼 처리.** §I / §III는 별도 PR로 헌법 amend 안 거치면 머지 불가. C5는 즉시 FAIL.
- **사전 로드 누락.** ARD 목록을 안 읽고 인용 누락을 판단할 수 없다. 매번 4개 파일을 모두 읽는다.

## 작성 톤

- 사용자에게 보고하는 텍스트는 **한국어**로.
- spec 파일을 직접 수정하지 않는다 — 수정은 `sharpen-spec`이 책임진다. 이 스킬은 *판정만*.
- 단, C3 / C4 fail 항목은 sharpen-spec에 넘기는 형태로 보고 끝에 한 단락으로 요약 ("위 2개 항목은 sharpen 라운드에서 한 번에 처리 가능").
