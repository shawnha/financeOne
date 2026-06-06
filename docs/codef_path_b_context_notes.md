# CODEF 경로 B — 컨텍스트 노트 (결정·근거)

## 배경
새 프로덕션 CODEF 키 검증 결과 (2026-06-06, `scripts/codef_probe_gates.py` 라이브):
- 토큰 ✅ / transaction-list·approval-list = CF-04015(권한OK) / account-list·card-list = CF-00401(미신청) / 데모서버 = CF-00005(프로덕션 전용).
- 즉 거래내역·승인내역은 connectedId 만 붙이면 되지만, 목록 API 두 개는 미신청.

## 왜 B (콘솔 추가신청 A 대신)
- 사장님이 목록 상품을 원래 신청 안 함 + 월 상품비 추가 회피.
- 카드번호가 `transactions.card_number` 에 **CODEF 조회 포맷 그대로** 이미 저장돼 있음 → 도출 가능.
  - 우리카드 `5275********1840`, 롯데 `5105*********059`(14장), 신한 `941064******3779` 등 실측 확인.
- 은행 계좌번호만 미저장 → 설정으로 공급(소수, 회사 본인 계좌).

## 현재 코드가 목록 API 에 의존하던 지점 (수정 대상)
- `sync_bank_transactions`: account 미지정 시 `get_bank_account_list`(account-list) 자동탐색 (codef.py:539). 라우터가 account 안 넘김.
- `sync_card_approvals`: 항상 `get_card_list`(card-list) 로 카드 나열 (codef.py:1002). 우회 없음 → **핵심 수정**.

## 설계 결정
1. **하위호환 우선**: 번호 미보유 시 기존 fallback 유지. 데모/구독 환경 동작 0 영향. (CLAUDE.md #3 surgical)
2. **카드번호 해석 우선순위**: `codef_cards_{env}_{org}` 설정 override → `transactions.card_number` distinct → None(card-list fallback).
3. **은행 계좌**: `codef_account_{env}_{org}` 설정. 없으면 account-list fallback. set 시 digits-only 정규화.
4. **신규 카드**: 현재 거래에 없는 카드는 distinct 에 안 잡힘. 사장님 지적("거래/승인내역에서 확인되지 않냐") → 라이브 connectedId 확보 후 **approval-list 를 cardNo 없이 호출 시 전체 카드 반환되는지** 검증. 되면 그걸 1차 소스로 승격(신규 자동발견). 안 되면 신규 카드는 설정 추가. (지금은 미검증 코드 안 넣음 — 검증 후 결정. CLAUDE.md #1·#10)

## 안전
- .env·DB prod 무변경 (코드만). 설정 쓰기(계좌/카드번호)는 엔드포인트로, 사장님 입력/승인 시.
- secret transcript 노출 → 로테이션 후 .env 기입 권장.
- entity 13 shinhan: 현재 수동 import(shinhan_bank.py) 중 → CODEF 재개 시 이중계상. 재sync 전 기존 분 정리 필요(별도).
