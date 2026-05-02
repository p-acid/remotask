# Phase 0 Research — Remove Deprecated Termination Aliases (006)

**Feature**: 006-remove-termination-aliases
**Date**: 2026-05-02

이 문서는 plan의 NEEDS CLARIFICATION을 0으로 만들기 위한 8개 결정 사항을 기록한다. 모든 결정은 005에서
이미 확정된 contract 위에서 이뤄지며, 새로운 외부 의존성·새로운 데이터 모델·새로운 운영자 동작을 도입하지 않는다.

---

## R1 — `/done` 슬래시 명령의 거부 경로

**Decision**: `/done`은 dispatcher의 슬래시 분기에서 별도 분기를 가지지 않고, 004가 정의한 표준 unknown-command
거부 경로로 떨어진다. 거부 시 발행되는 감사 이벤트는 `slash_command_rejected reason=unknown_command`이다.

**Rationale**:
- 004의 슬래시 명령 dispatcher는 `commands.CURATED_COMMANDS`에 없는 `name`에 대해 일관된
  `slash_command_rejected reason=unknown_command` 경로를 이미 가지고 있다.
- 005가 `name == "done"` 분기를 추가한 이유는 deprecation 경고와 termination ladder를 동시에 실행해야 했기
  때문이다. 별칭이 제거되면 그 분기는 더 이상 존재 이유가 없으므로, 004의 fall-through에 자연스럽게 흡수된다.
- 운영자에게 보이는 응답 메시지(있다면)는 004의 표준이 정의한 동작이며 별도 변경하지 않는다.

**Alternatives considered**:
- "별도 안내 메시지 송출" — 거부됨. 005가 한 릴리스 동안 안내했고, 운영자는 이미 `/cancel`로 이전 완료 가정.
  추가 안내는 운영자 인지 부담만 늘리고 deprecation 종결 의도와 충돌.
- "`/done` 분기 유지하되 silent reject" — 거부됨. 004 unknown_command 처리와 같은 효과를 두 분기에서 중복 구현하게
  됨. dead code 유발.

---

## R2 — 평문 `done`/`stop`/`finish`의 비-제어화

**Decision**: parser의 `match_termination_command` 함수를 제거하고, dispatcher의 평문 처리 분기에서 그 함수를
호출하던 부분(현재 `dispatcher.py` line 126의 `if thread_id is not None and match_termination_command(text) is not None:`
및 라인 161 부근의 alias warning 발송)을 함께 제거한다. 결과적으로 토픽 안 평문 `done`/`stop`/`finish`는
일반 텍스트와 구분되지 않는 경로로 떨어지고, 일반 채팅과 마찬가지로 dispatcher가 어떤 audit 이벤트도 기록하지 않는다.

**Rationale**:
- `match_termination_command`는 003의 평문 종료 grammar 전용 함수다. 005에서 이미 deprecated 표시되어 있고,
  외부 모듈에서 import하는 곳은 dispatcher 단 한 곳이다(grep 검증 완료).
- 평문 처리 fall-through는 2025-11 이전 003에 존재하던 "operator chat is non-control" 의미와 동일하며, 운영자 측면에서
  자연스러운 동작이다.

**Alternatives considered**:
- "함수는 남기고 호출만 제거" — 거부됨. dead code. 삭제가 더 깨끗하고 SC-001 grep 0 hits 기준에도 부합.
- "평문 매칭은 지우되 audit 이벤트는 남김(`alias_deprecation_used` 1회 발송)" — 거부됨. FR-007이
  "어떤 alias_deprecation_used 이벤트도 기록되지 않는다"를 명시함.

---

## R3 — Runtime의 alias-deprecation set 제거 안전성

**Decision**: `Runtime._alias_deprecation_warned` 셋과 세 메서드(`has_/record_/clear_alias_deprecation_*`)를 제거한다.
이는 `DispatchContext`의 동명 콜백 3개를 함께 제거함을 의미한다.

**Rationale**:
- 셋의 유일한 작성자는 dispatcher의 `_emit_alias_warning`이다. 별칭 분기가 사라지면 셋에 쓸 일이 없다.
- 셋의 유일한 cleanup 경로는 worker의 `on_terminal` 콜백을 거쳐 `clear_alias_deprecation_for_session`을 호출하는
  것이다. R5에서 `on_terminal`도 제거하므로 cleanup 경로가 자연 소멸한다.
- in-memory 상태이므로 deploy 마이그레이션·DB 변경이 필요 없다. daemon 재시작 시 셋은 이미 비어 있으니 부수효과 없음.

**Alternatives considered**:
- "셋과 메서드만 남기고 미사용으로 둠" — 거부됨. dead code.
- "DispatchContext에 콜백 필드만 보존(`Optional[None]` 기본값)" — 거부됨. spec FR-015가 명시 제거 요구.

---

## R4 — Audit 모듈에서 두 상수 제거의 영향 범위

**Decision**: `audit.EV_ALIAS_DEPRECATION_USED`와 `audit.REASON_MAIN_CHAT_DONE`을 제거한다. 과거 audit 로그 라인에
들어 있는 문자열 리터럴 `"alias_deprecation_used"`와 `"main_chat_done"`은 정정하지 않는다(append-only).

**Rationale**:
- 두 상수의 production 참조 위치는 `dispatcher.py` 두 곳(별칭 사용 시 audit row 작성, main_chat에서 `/done` 처리 시
  reason 기록)이고, 그 두 분기 모두 본 feature에서 함께 제거된다. 외부 import 없음.
- audit 로그 reader는 internal-only이며, 현재 reader 중 두 이벤트/사유를 case match하는 코드는 없다(grep 확인).
- 과거 로그 라인 immutability는 헌법 VII("Observability & Auditability")의 append-only 원칙에 부합한다. 정정하면
  무결성이 무너짐.

**Alternatives considered**:
- "상수 보존하고 deprecated 주석만 추가" — 거부됨. SC-001 grep 0 hits 기준 위배.
- "과거 로그 라인을 일괄 sed로 새 reason으로 교체" — 거부됨. audit 무결성 위배. 과거는 과거로 둔다.

---

## R5 — Worker의 `on_terminal` 콜백 제거의 안전성

**Decision**: `worker.run_worker`의 `on_terminal: Callable[[str], None] | None = None` 파라미터와 종료 경로의
콜백 호출(`worker.py` line 266-270)을 제거한다. dispatcher의 `_on_terminal` 정의와 worker 호출 시 인자 전달도 함께
제거한다.

**Rationale**:
- 콜백의 호출자는 dispatcher 내부 한 곳뿐이다(`_on_terminal(sid)` → `clear_alias_deprecation_for_session(sid)`).
  R3에서 set이 제거되면 호출 자체가 무의미해진다.
- worker는 005 이전부터 종료 경로마다 명확한 audit·status 처리를 가지고 있고, alias cleanup은 005에서 일회성으로
  추가된 책임이다. 제거 시 worker 종료 책임이 005 이전 상태로 정리된다.
- 호출 실패 시 warning만 로깅하던 try/except도 함께 제거한다(필요성 사라짐).

**Alternatives considered**:
- "콜백 슬롯만 남기고 dispatcher가 noop을 전달" — 거부됨. dead API surface. SC-001 grep 0 hits 기준 위배.
- "콜백을 다른 cleanup 용도로 재활용 (예: 향후 metrics)" — 거부됨. YAGNI. 필요해질 때 명시적으로 다시 추가.

---

## R6 — 005 quickstart의 alias 단계 처리

**Decision**: 005 quickstart의 alias-deprecation 검증 단계는 본 feature의 quickstart에서 negative-case 단계로 대체된다.
"alias가 발동되며 경고가 한 번 노출됨"을 검증하던 step은 "alias가 발동되지 않으며 경고가 한 번도 노출되지 않음" + "/cancel
정상 동작"을 검증하는 step으로 바뀐다.

**Rationale**:
- 005 quickstart 자체는 release 자료로 이미 보존되어야 한다(`specs/005-dm-channel/quickstart.md`).
- 006 quickstart는 본 feature의 contract 변화만 검증한다. 5번 step 정도로 컴팩트하게 정리한다.

**Alternatives considered**:
- "005 quickstart를 in-place 편집" — 거부됨. 005 spec/quickstart는 그 시점 상태의 release 증거. 헌법 V Spec-Driven에서
  spec과 구현은 함께 보존된다.

---

## R7 — 003 평문 통합 테스트 마이그레이션 패턴

**Decision**: `tests/integration/test_operator_stop.py`와 `tests/integration/test_operator_stop_forced.py`의 트리거를
"평문 `done`/`stop`/`finish` 메시지" 대신 `/cancel` 슬래시 명령으로 교체한다. 검증 대상(graceful ladder, forced
ladder, `Session canceled by operator.`/force-canceled 템플릿, `[KEY]` prefix)은 그대로 유지한다.

**Rationale**:
- 두 테스트는 003에서 도입된 종료 ladder의 기능 검증이지, "평문 매칭" 자체의 검증이 아니다. 트리거 채널만 바꾸면
  검증 의도는 보존된다.
- `/cancel` 트리거는 005의 `tests/integration/test_cancel_canonical.py`에서 이미 검증된 헬퍼 패턴(슬래시 메시지 dict
  생성기 + dispatcher invoke)을 재사용 가능하다.
- 마이그레이션 후 두 파일은 평문 종료에 대한 의존을 끊고 본 feature 후에도 유효하다.

**Alternatives considered**:
- "두 파일 삭제 후 `test_cancel_canonical.py`에 케이스 통합" — 거부됨. 검증 단위가 다르다(005의 `cancel_canonical`은
  dispatch path 검증, 003 두 파일은 ladder 동작 검증). 별도 파일 유지가 가독성·정확성 측면에서 우월.

---

## R8 — 회귀 테스트 두 건의 위치와 형태

**Decision**:
- `tests/integration/test_done_command_removed.py` — `/done` 슬래시(메인 챗 / 토픽 / `@<bot>` 형) 세 시나리오에서
  `slash_command_rejected reason=unknown_command` 발행 + 세션 미변동 검증.
- `tests/integration/test_plain_termination_dead.py` — 토픽 안 평문 `done`/`stop`/`finish`(각각) 발송 시 세션 상태
  미변동 + dispatcher가 어떤 audit row도 추가하지 않음 + 어떤 outbound message도 보내지 않음을 검증.

**Rationale**:
- 두 파일을 분리한 이유는 두 회귀가 서로 다른 분기(슬래시 vs 평문)를 보호하기 때문이다. 한 파일에 합치면 어느 한쪽
  실패 시 디버깅 시야가 좁아진다.
- 검증 메커니즘은 005 통합 테스트 인프라(`tests.fakes.fake_telegram.FakeTelegram`, `tests.fakes.fake_agent`)를 그대로
  사용 가능. 새 의존성 0건.

**Alternatives considered**:
- "단위 테스트(parser/dispatcher 직접 invoke)만으로 충분" — 거부됨. parser 함수가 사라지므로 단위 테스트로
  검증 자체가 불가능한 영역(평문 메시지가 dispatcher 어디서도 잡히지 않음)이 존재. 통합 테스트가 더 정확.
- "기존 `test_dispatcher.py`에 케이스 추가" — 거부됨. 본 파일은 단위 테스트이고, audit row·message 부재 검증은
  Telegram fake와 DB connection 픽스처가 있는 통합 환경에서 더 자연스럽다.
