# Spec pipeline

remotask 프로젝트에서 spec 한 건을 작성·검증·확정하는 데 쓰는 스킬들의 인덱스. 모든 스킬은 동사 우선 네이밍 (`<verb>-<object>`).

## 현재 파이프라인 (4 스킬)

```
사용자 자연어
    │
    ▼
[create-spec]
  ├─ SoT 4계층 + CHANGELOG + 템플릿 읽기
  ├─ 다음 NNN 결정
  └─ 풀 드래프트 작성 (`[NEEDS CLARIFICATION]` 마커 그대로 둠)
    │
    ▼
[validate-spec]                  ← 정적 룰 lint (게이트)
  ├─ 7개 SPEC.md 섹션 존재
  ├─ AT가 GWT 형식 (failing-now / passing-when-done)
  ├─ Tasks가 test-first (T1 = red 테스트 작성)
  ├─ 마커 외 NNN 충돌 / 파일명 형식 / 본문 영어
  └─ ARCHITECTURE/PRD 영향이 Notes에 명시되었는지 (시스템 shape 변경 시)
    │
    ▼
[check-constitution]             ← 7원칙 평가 (게이트)
  ├─ 7원칙 모두 PASS / waiver 슬롯 채움
  ├─ 영향 ARD 결정의 인라인 D번호 인용
  ├─ waiver 적정성 (3줄 형식 + 단순 대안 검토)
  └─ 새 ARD 후보가 Notes에 기재됐는지
    │
    ▼
[sharpen-spec]                   ← Q&A 인터랙션 (사용자와 좁히기)
  ├─ 남은 `[NEEDS CLARIFICATION]` 마커 수집
  ├─ validate / check가 발견한 추가 모호 지점 수집
  └─ 한 번에 batch로 사용자에게 묻고 답변으로 마커 치환
    │
    ▼
머지 가능한 spec
```

각 스킬은 단독으로도 호출 가능. `create-spec`은 흐름의 마지막에 다음 단계를 자동으로 chain한다 (사용자 yes/no 게이트 포함).

| 스킬 | 입력 | 출력 | 인터랙션 |
|---|---|---|---|
| `create-spec` | 자연어 변경 설명 | `specs/NNN-<name>.md` (마커 포함 가능) | 모델 단독 |
| `validate-spec` | spec 파일 경로 | PASS/FAIL 보고 + 위반 항목 리스트 | 모델 단독 |
| `check-constitution` | spec 파일 경로 | PASS/FAIL 보고 + 원칙별 평가 + ARD 인용 누락 지적 | 모델 단독 |
| `sharpen-spec` | spec 파일 경로 | 같은 파일 (마커/모호 지점 해소) | **사용자와 Q&A** |

## 백로그 (다음 라운드 후보)

이번 단계에서는 만들지 않음. 실제 spec을 몇 건 작성해 본 뒤 ROI 판단.

### `append-ard` — spec → ARD entry 작성 (머지-시점)

- 책임: spec의 Notes에 D 후보가 있으면 머지 직후 `docs/ARD.md`에 새 entry 작성·append.
- 트리거 표현 후보: "ARD 추가해줘", "D24 작성", "/append-ard".
- 합칠 대상 후보: **`work-done` 파이프라인** (PR 생성 + Jira 업데이트 + 알림 묶음). 머지-시점에 함께 발화하는 게 자연스러움.
- 보류 사유: 스킬 작성과 시점이 다르고 빈도 낮음. 실제 운영에서 분리 가치를 느낄 때 만든다.

### `append-changelog` — CHANGELOG 5–15줄 섹션 추가 (머지-시점)

- 책임: 머지 직후 `CHANGELOG.md` 하단에 5–15줄 섹션 append (motivation + key outcome + PR/ARD refs).
- 트리거 표현 후보: "CHANGELOG 정리해줘", "/append-changelog".
- 합칠 대상 후보: **`work-done` 파이프라인**. PR 머지 흐름 안에 자연스럽게 들어감.
- 보류 사유: 머지-시점 작업이라 spec 작성 도메인 밖. work-done이 이미 머지-시점 파이프라인이라 거기 흡수하는 게 일관.

### `scan-impact` — ARCHITECTURE/PRD/CONSTITUTION 영향 식별

- 책임: spec을 보고 어느 절이 함께 변해야 하는지 자동 식별 (`CLAUDE.md` §5 규칙 3).
- 보류 사유: false positive 위험이 큰 작업. 우선 `validate-spec`의 한 룰 ("Notes에 ARCHITECTURE/PRD 영향 명시가 있는가?")로 흡수해서 결과를 본 뒤, 만족스럽지 않으면 별도 스킬로 승격.
- 흡수 위치: `validate-spec`의 정적 룰 셋 안.

## 결정 근거

- **머지-시점 도메인은 별도 라인** (work-done): spec 작성과 머지 후 처리(append-ard, append-changelog)는 시점·맥락이 달라 한 파이프라인에 섞으면 트리거 모호성이 커진다. 머지-시점은 work-done 쪽에 놓는 것이 일관.
- **scan-impact는 lint 룰부터**: 별도 스킬로 빼면 정확도/false positive 부담을 짊어지지만, validate-spec의 한 룰로는 "Notes에 명시되었나" 여부만 보면 되어 가볍다. 그 정도가 부족할 때 분리한다.
- **동사 우선 네이밍 일관성**: `create-spec` / `sharpen-spec` / `validate-spec` / `check-constitution`. 미래 스킬도 같은 패턴 (`append-ard`, `append-changelog`, `scan-impact`).
