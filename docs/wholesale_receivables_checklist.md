# 홀세일 외상매출(미수/수금율) 정확화 — 체크리스트

한아원홀세일(entity 13) `/receivables` 의 수금 소스를 은행 입금 이름매칭 → **SIMS `customer_collections` 코드(=이름) 조인**으로 전환. 미수·수금율 정확화 + 추가 지표.

## 배경 (읽기전용 진단으로 확정)
- 기존 `/receivables` 는 수금을 `transactions`(상품매출 40100/10800) + `payee_aliases` 이름매칭으로 계산 → 은행 입금 ₩3.93B 미매칭(카드정산·점주개인명) → **수금 과소·미수 과대**.
- SIMS `customer_collections`(io_gu='입금', 1872건) 는 거래처 코드 100% 채움. `wholesale_sales.payee_code`(100%)와 코드 교집합 238/238.
- 검증: 코드별 `customer_name` == `payee_name` 불일치 0 → **이름(canonical) 조인 그대로 정합**. 기초(ar_opening_balances)도 payee_name 키 → 그대로 합산.
- 정확 그룹 미수 = 기초 ₩150.36M + 매출 ₩12,659.5M − 수금 ₩12,526.86M = **₩283.0M** (수금율 ~99%). 이수마트 ₩71.7M 지난 대사와 원단위 일치.
- "과수금"으로 보였던 거래처(바르다임·우주약국 등)는 **2025 기초잔고 무시 아티팩트** — 기초 포함하면 정상. → 미수 = 기초+매출−수금 필수.

## 구현 ✅ 완료 (2026-06-06)
### Backend `receivables_service.py`
- [x] `_WHOLESALE_ENTITIES = {13}` 상수
- [x] `get_receivables_summary` — entity∈wholesale 이면 `collected` CTE 를 `customer_collections`(io_gu='입금', GROUP BY customer_name) 로 분기. sales/opening/조인/합계 동일. (CTE 동적 조립)
- [x] `get_receivables_summary` — wholesale 이면 `collection_methods`(method 별 금액·건수·비중) 응답 추가. 그 외 빈 배열.
- [x] `get_receivables_monthly` — collected 소스 분기 (customer_collections trans_date)
- [x] `get_receivables_daily` — collected 소스 분기

### Frontend `receivables-content.tsx`
- [x] `ReceivablesSummary` 에 `collection_methods`(+ `CollectionMethod` 인터페이스) 추가
- [x] 수금방식 분해 카드 (isWholesale) — 보통예금/카드결제/더샵몰/중외몰/새로팜 비중 바
- [x] 과수금/선수금 섹션 — detail 중 outstanding < 0 필터 (빈 상태 메시지 포함)
- [x] 홀세일일 때 부제/문구 갱신 (수금 = SIMS 입금 코드 기준 + 2025 기초)

### 검증 ✅
- [x] pytest 회귀 없음
- [x] API 수치 일치 — 미수 ₩283,001,087(원단위), 수금율 97.79%(기초 포함), 수금방식 보통예금 80.9%·카드 17.4% 등
- [x] 브라우저 확인 (localhost entity 13) — KPI·월별·일별·수금방식·과수금·거래처테이블 전부 정상
- [x] entity 2(코리아) 회귀 없음 (빈 결과, methods=[], 에러 없음)

## 결과
- 기존 `/receivables` 는 수금을 은행 이름매칭으로 잡아 ₩3.93B 미매칭 → 수금 과소·미수 과대. SIMS 코드조인으로 전환해 **정확**해짐.
- 과수금으로 보이던 거래처(바르다임·우주약국 등)는 전부 2025 기초채무 상환분 → 기초 포함 시 정상(전체기간 선수금 0건).
