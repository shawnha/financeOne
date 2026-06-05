# SsArt SIMS OpenAPI 연동 — 체크리스트

한아원홀세일(entity 13) 매출/매입/입출금/기초자료/잔고를 SIMS(신성아트컴) OpenAPI로 자동 연동. 수동 xlsx 업로드 대체.

## Phase 1 — 공통 클라이언트 + 매출/매입 (P&L 핵심) ✅ 완료 (2026-06-06)
- [x] `backend/services/integrations/ssart.py` — `SsArtClient` (인증 2단계, cp949 디코딩, 페이지네이션, 레이트리밋 인지)
- [x] 매출 transform `sales_api_to_row()` → 기존 `wholesale_service.import_wholesale_sales` dict 형태
- [x] 매입 transform `purchase_api_to_row()` → `import_wholesale_purchases` dict
- [x] **검증: 5/30 overlap 67행 amount까지 DB와 대조 → total 정확 일치(163,450,421). supply만 2행 ₩4 라운딩차(무영향).** 매입 5/29 7행도 정확 일치.
- [x] 페이지네이션 동작 검증 (PAGE_SIZE=30 → 3페이지 67줄 == PAGE_SIZE=500 1페이지)
- [x] 라우터: `POST /api/integrations/ssart/sync` + `GET /api/integrations/ssart/status`
- [x] overlap 재sync 시 dedup → inserted 0 확인 (매출 5/30, 매입 5/29)
- [x] 6월 신규분 실적용: 매출 480줄 ₩11.7억 + 매입 55줄 ₩10.3억 prod COMMIT. /pnl 6월 매출 반영 확인.
- [x] 테스트: transform 8건 PASS (면세 TAX_YN=N, VAT 역산, dedup 키)

## Phase 2 — 입출금 (AccTransState) ✅ 완료 (2026-06-06)
- [x] `/v2/AccTransState/get/` → **신규 테이블 `customer_collections`** (customer_balances 는 스냅샷이라 부적합). 마이그 `k7l8m9n0o1p2`.
- [x] `sync_acc_trans` (UPSERT, dedup `(entity, trans_date, trans_seq)`) + 라우터 types=["collections"]
- [x] prod 적용: 5~6월 565건 ₩4.58B (보통예금 ₩2.49B·카드결제 ₩2.07B). idempotency 확인.
- [x] **이수마트 수금 10건 ₩223.7M 확보** — 선결제↔매출 대사 재료 ([[project_how_refund_reclass_seonsugum]])
- [ ] (후속) 이수마트 수금 vs wholesale_sales 매출 대사 → 진짜 선수금 잔액 산출

## Phase 3 — 기초자료 + 잔고
- [ ] `/v2/customer/get/` → 거래처 마스터 (payee_aliases 연계)
- [ ] `/v2/product/get/` → 제품 마스터 (제조사·성분·보험코드)
- [ ] 잔고/재고 → inventory_snapshots 테이블 연계 (재고는 detail STOCK_*/PRODUCT_NO/TERM_DATE)

## 운영
- [ ] 자동 동기화 (GitHub Actions cron `/api/integrations/cron/auto-sync` 에 ssart 추가 검토)
- [ ] 비번 로테이션 권장 (transcript 노출)
- [ ] CHANGELOG 업데이트
