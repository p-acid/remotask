# Process Overhaul

목적: speckit 7-file 패턴을 폐기하고, 단일 spec 파일 + 누적 CHANGELOG 모델로
전환한다. 행동 가이드는 Karpathy-style 4 원칙을 베이스로 우리 프로젝트 컨벤션을
§5에 융합한다. 본 문서는 일회용이며 작업 완료 후 삭제된다.

> 결정 근거: specs/ 7개 폴더가 변경 무게에 비해 비대했고 (006 같은 사례),
> 진짜 가치는 (헌법 / PRD / ARCHITECTURE / ARD) 4개 상위 layer에 누적된다.
> 진행 history는 약식 CHANGELOG 한 파일에 섹션 단위로 모으면 충분하다.

## 결정 (사전 확정)

- **브랜치**: `chore/process-overhaul`. PR #6 머지 후 main에서 분기.
- **기존 specs/ 운명**: 각 spec → CHANGELOG.md의 한 섹션으로 약식 이식 후
  `specs/` 폴더 자체 삭제.
- **speckit 잔재**: 완전 삭제. `.claude/skills/speckit-*` (7개 skill),
  `.specify/templates/`, `.specify/scripts/`, `.specify/extensions*`,
  `.specify/init-options.json`, `.specify/feature.json` 모두 제거.
  **헌법(`.specify/memory/constitution.md`)만 보존** — 루트의
  `CONSTITUTION.md`로 이동하여 PRD/ARCHITECTURE/ARD와 같은 위치에 둔다.

## Phase 1 — Discovery (no destructive change)

- [ ] T1 신규 `CLAUDE.md` 초안 — Karpathy 4 원칙(§1~§4) + §5 프로젝트 컨벤션
  (layer 우선순위, 단일 spec 정책, CHANGELOG 정책, behavioral 강조점)
- [ ] T2 단일 spec 템플릿 — `specs/NNN-<name>.md` (폴더 X, 한 파일에
  motivation + behavior + acceptance + tasks 인라인). 첫 사용은 다음 feature
  부터.
- [ ] T3 `CHANGELOG.md` 초안 — feature 단위 append-only, PR + ARD 링크.
  001~007 각각의 short summary를 섹션으로 이식 (각 5~15줄).

## Phase 2 — Apply (destructive, single PR)

- [ ] T4 `.specify/memory/constitution.md` → `CONSTITUTION.md` (루트)로 이동.
  내용은 동일, 5-layer SoT 표 갱신(§V "spec-driven" 표현은 유지하되 형태
  자유로 완화).
- [ ] T5 `specs/` 폴더 전체 삭제 (T3의 CHANGELOG로 이미 정보 이식 완료).
- [ ] T6 `.specify/` 폴더 전체 삭제.
- [ ] T7 `.claude/skills/speckit-*` 7개 삭제.
- [ ] T8 `.coderabbit.yaml` path_filters에서 `specs/**`, `.specify/**` 제거
  (해당 디렉토리가 사라지므로 의미 없음). 새 보호 대상 (`CONSTITUTION.md`,
  `CHANGELOG.md`, `OVERHAUL.md`) 추가 검토.
- [ ] T9 `PRD.md` / `ARCHITECTURE.md` 본문에서 speckit 흐름 / specs/<feature>/
  언급을 새 모델로 갱신. ARD에 `D23 — process overhaul` entry 추가.
- [ ] T10 `OVERHAUL.md` 자체 삭제 (작업 완료의 마지막 commit).

## 의도적 보존

- `PRD.md` / `ARCHITECTURE.md` / `ARD.md` (이름·위치 그대로)
- ARD entries D1~D22 (append-only 정책 — D23만 새로 추가)
- 코드 / 테스트 / `pyproject.toml` 등 모든 실행 자산
- `.gitignore`, `.coderabbit.yaml` 등 메타 (필요 시 path_filters만 갱신)

## 비-목표

- 이 PR에서 구현·테스트 코드는 한 줄도 건드리지 않는다.
- 헌법 본문은 §V의 "형태 자유" 표현만 패치, 7 원칙 자체는 유지.
- ARD 기존 22개 entry는 손대지 않는다.
