# 계정 트리 재설계 — 체크리스트

설계 잠김(GO-with-fixes). 리스크=마이그레이션 메커니즘. 코리아 먼저 PoC.
상세 설계 `account-tree-redesign-plan.md`, 결정 기록 `account-tree-redesign-context-notes.md`.

## Phase 0 — 운영 태그 확정 ✅ (2026-06-07)
- [x] 직교 운영 태그 3종 잠금: **cost_behavior(고정/변동) · is_subscription(구독여부) · cost_center(부문/프로젝트)**. 담당자=제외(결제 1인).

## Phase 1 — 읽기전용 사전점검 스냅샷 ✅ (2026-06-07, DB 무변경)
스크립트 `scripts/account_tree_preflight.py`(read-only 세션). 결과 `docs/account-tree-preflight-2026-06-07.md`.
- [x] 중복명칭 42그룹/96코드 + 코드별 FK 참조수(동적 FK 발견 = 8테이블, invoices 포함)
- [x] gaap_mapping 역전 발견 — 생존 82200/81400 gaap=0인데 레거시가 보유 → 이관 필수
- [x] 25300 triage — **개명 아님**: 차량할부·매입인보이스 오분류, 진짜 선수금 0건, 선수금 3코드+키워드 67
- [x] drift 실측 — e2=192·e3=5·e13=347 (총 544)
- [x] GL 유무 + 2차 drift — 홀세일 GL 0건·HOI 11/109 일치·마감장치 전무
- [x] internal std NULL — HOI 70·코리아 22·리테일 18·홀세일 19
- [x] 산출물 findings 문서 작성

## Phase 2 — 정식 설계 + 리뷰 ✅ (2026-06-07)
- [x] Software Architect 정식 설계 → `docs/account-tree-migration-mechanism.md` (기간잠금·canonical remap·GL재전기·DB트리거 sync·듀얼GAAP 경계·운영태그·감사/diff/승인·코리아 PoC, 전부 코드 grounding)
- [x] /plan-eng-review (아키텍처 4섹션 + codex outside-voice) → §14에 반영
- [x] 결정: D1 전역 차트 일원화 PoC서 분리 / A1 잠긴 재무제표 불변 아카이브 스냅샷
- [x] 판정 GO-with-fixes. **구현 전 §14.1 CRITICAL 4 + §14.2 HIGH 6 반영 필수.** 코드/DB 무변경.

## Phase 2.5 — 구현 전 잠금 (다음, 결산권위 입력 + 설계 개정)
- [ ] 결산 권위 입력(§13): 선수금 canonical(25900?)·25300 8건 건별·gaap 신규 12코드·마감 기준일·홀세일 GL 정책
- [ ] §14 반영해 §1/§3/§7 개정: GL재전기=std 라인만 in-place(C1)·잠금 가드 전 삭제경로+DB트리거(C2/C3)·잠금 입력테이블 확장(C4)·diff in-memory(H3)
- [ ] (필요시) 개정 설계 재-리뷰

## Phase 3 — 코리아 PoC
- [ ] 코리아 표준차트 정합 → 내부 재배치 → drift 정렬(전향/재분류분개) → 롤업
- [ ] 발생 + GL 두 엔진 모두 가결산 PDF 대조, 마감기간 diff=0
- [ ] 이후 리테일/홀세일/HOI

## 가드레일
- 결산자료(.xls/.pdf, `~/Documents/HanahOneAll/`) **커밋 금지**. 깃엔 설계·코드만.
- 과거 transactions.standard 일괄 UPDATE = 과거 신고 재무제표 변경 → **명시승인 없이 금지**.
- prod DB 쓰기/삭제 = 명시승인 필요. Phase 1은 전부 SELECT only.
