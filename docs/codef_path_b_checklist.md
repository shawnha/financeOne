# CODEF 경로 B (목록 API 없이 번호 직접공급) — 체크리스트

새 프로덕션 키는 거래내역/승인내역 ✅, 보유계좌목록(account-list)/보유카드목록(card-list) ❌ 미신청.
현재 코드는 sync 때 내부적으로 account-list/card-list 를 호출 → 새 키로는 CF-00401 실패.
→ 목록 API 없이 계좌/카드번호를 직접 공급하도록 하위호환 수정.

## 범위
- 현재 데모로 돌리는 entity/org 전부: entity 2(woori_bank·woori_card·lotte_card·ibk_bank), entity 3(woori_bank·woori_card·lotte_card), entity 13(shinhan_bank·shinhan_card).

## 설계 원칙
- **하위호환**: 번호가 없으면 기존 account-list/card-list fallback 그대로 (데모 동작 0 영향).
- **카드 자동도출**: card-list 대신 `transactions.card_number`(이미 CODEF 포맷 저장됨) distinct 사용 → 기존 카드 수동입력 0.
- **은행 계좌**: 거래에 계좌번호 미저장 → 설정(`codef_account_{env}_{org}`)으로 공급. 사장님이 회사 본인 계좌번호 입력.
- **신규 카드**: 등록 후 라이브 connectedId 로 "cardNo 없이 일괄 승인조회" 가능 여부 검증 → 되면 자동발견 완성.

## 구현 작업 (✅ 완료 2026-06-06, 미커밋)
- [x] codef.py: 설정 helper `get/set_codef_account`, `get/set_codef_cards`, `resolve_codef_card_numbers`
- [x] codef.py: `sync_card_approvals(card_numbers=None)` — 주어지면 card-list 건너뜀 (하위호환 fallback 유지)
- [x] integrations.py: sync-bank 에서 account 해석·전달, sync-card 에서 card_numbers 해석·전달
- [x] integrations.py: `POST/GET /codef/account-numbers` 설정 엔드포인트
- [x] scheduler.py: cron `_sync_one_sync` 에서 account/card_numbers 해석·전달
- [x] tests: card_numbers 주면 get_card_list 미호출 / fallback / resolve 우선순위 / account helper (8 신규, 전부 PASS)
- [x] pytest: 495 passed. 남은 9 fail 은 전부 사전실패(cockpit발·멤버매칭 prior 미커밋)·내 변경 무관
- [x] FastAPI 앱 로드 + 새 라우트 등록 확인

## 검증/배포 (사장님 액션 필요)
- [ ] secret 로테이션(노출) 후 .env `CODEF_PROD_*` 기입
- [ ] active env=production 전환
- [ ] connectedId 등록(법인 은행=공동인증서, 카드=id/pw) — 사장님만
- [ ] 은행 계좌번호 설정 입력
- [ ] 라이브 1줄 end-to-end 검증 + cardNo-없이 일괄조회 가능 여부 확인
- [ ] ⚠️ entity 13 shinhan 은 수동 import 중복계상 위험 — 재sync 전 기존 수동 import 분 정리
