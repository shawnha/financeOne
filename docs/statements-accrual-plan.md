# 재무제표 K-GAAP 발생주의 모드 — 설계 plan

**Date:** 2026-05-08
**Phase:** Statements / Accrual mode
**Owner:** shawn

## 1. 목적

`/pnl` 페이지가 운영자 직관 view (현금주의 OpEx + 발생주의 매출) 라면, `/statements` 는 회계법인 base 결산자료와 일치하는 **K-GAAP 정합 view**.

검증 base: 26년 1-3월 가결산 PDF (한아원홀세일) — FinanceOne 대비 매출 99.7% / 매입 99.2% / VAT 99.7% 정확도 이미 확보 (`project_resume.md` lines 36-43).

## 2. 현 상태

- `/statements` 페이지: `journal_entries` (현금주의 base, transactions 직접 매핑)
- 5종 재무제표: BS / IS / 현금흐름 / 시산표 / 결손금처리
- 단일 source: `bookkeeping_engine.get_all_account_balances()`
- 항목 PDF 양식 일치 (Ⅰ. 매출액 / Ⅱ. 매출원가 / ...)

## 3. Gap 분석 (PDF 정답 대비)

| 항목 | 현 (현금주의) | 발생주의 정답 | 차이 |
|---|---|---|---|
| 매출 | journal_entries (입금만) | wholesale_sales.supply_amount | 외상 미회수 누락 |
| 매출원가 | journal_entries (출금만) | wholesale_sales.quantity × cogs_unit_price | 외상 미지급 누락 |
| 판관비 | journal_entries OpEx | + 외상/정산 base | 91% 정확 (₩11.5M gap) |
| 외상매출금 (자산) | 없음 | wholesale_sales 미회수 잔액 | 누락 |
| 외상매입금 (부채) | 없음 | wholesale_purchases 미지급 잔액 | 누락 |
| 부가세예수금/대급금 | 없음 | wholesale_*.vat | 누락 |

## 4. 설계 결정

### 4.1 토글 vs 별도 페이지

**채택: `/statements` 페이지 내 [기준: 현금주의 / 발생주의] 셀렉트 토글.**

- 이유: 5종 재무제표 양식/UI 동일, 데이터 소스만 분기. 페이지 분리 비용 ↓
- 1개 entity × 1개 fiscal_year × 1개 (start, end) × **1개 basis** = 1 statement record (basis 컬럼 추가)
- VAT 토글 (포함/제외) 통합

### 4.2 데이터 소스 (entity 13 — 한아원홀세일 우선)

| 항목 | basis='cash' (기존) | basis='accrual' (신규) |
|---|---|---|
| 매출 | journal_entries | `wholesale_sales` (4,690건, 1-4월) |
| 매출원가 | journal_entries | `wholesale_sales.quantity × cogs_unit_price` |
| 판관비 | journal_entries SGA | journal_entries SGA (현 단계, 동일) |
| 영업외 | journal_entries | journal_entries (동일) |
| 법인세등 | journal_entries | journal_entries (동일) |
| 외상매출금 | 없음 | `wholesale_sales − 매칭된 입금 transactions` |
| 외상매입금 | 없음 | `wholesale_purchases − 매칭된 출금 transactions` |
| 부가세예수금 | 없음 | `SUM(wholesale_sales.vat)` |
| 부가세대급금 | 없음 | `SUM(wholesale_purchases.vat)` |

### 4.3 다른 entity 대응

- **entity 13 (한아원홀세일):** `wholesale_sales`/`wholesale_purchases` 우선
- **entity 2 (한아원코리아) / 3 (한아원리테일):** `invoices` 테이블 fallback (현재 데이터 없음 → 발생주의 모드 = 현금주의 모드와 동일하게 표시 + 경고 배너)
- **entity 1 (HOI, US GAAP):** US GAAP phase, journal_entries 유지 (이번 phase 제외)

### 4.4 VAT 처리 (옵션 ② already merged)

- `is_vat_taxable=true` (default): /1.1 처리 (임차료/통신비 등)
- `is_vat_taxable=false`: as-is (인건비/이자/공과금)
- 발생주의 매출/매입은 `supply_amount` 컬럼이 이미 VAT 제외 base
- VAT 토글 ON: 위 적용 / OFF: 원금액

### 4.5 외상 잔액 계산 알고리즘

**외상매출금** (자산):
```
SUM(wholesale_sales.total_amount WHERE sales_date <= as_of_date)
- SUM(transactions.amount WHERE type='in' AND payee_alias 매칭 AND date <= as_of_date)
```
- payee_aliases (51건) + canonical_name 활용
- 회수율 36.1% (현재) — alias 추가 + 4월 매출 5-6월 회수 가정

**외상매입금** (부채):
```
SUM(wholesale_purchases.total_amount WHERE purchase_date <= as_of_date)
- SUM(transactions.amount WHERE type='out' AND counterparty 매칭 AND date <= as_of_date)
```

## 5. 구현 단계 (Software Architect 리뷰 반영 — A → D-1Q → B → D-2Q → C)

### Phase 0 — DB 마이그레이션 + 인터페이스 ADR (선행)
- Alembic: `financial_statements.basis VARCHAR(16) NOT NULL DEFAULT 'cash'`
- **UNIQUE 제약 재정의:**
  ```sql
  -- ① 기존 row basis='cash' backfill (DEFAULT 자동)
  -- ② DROP UNIQUE(entity_id, fiscal_year, ki_num, start_month, end_month)
  -- ③ CREATE UNIQUE(entity_id, fiscal_year, ki_num, start_month, end_month, basis)
  ```
- **net_income 인터페이스:** `generate_balance_sheet_accrual(net_income_override: Decimal)` — accrual IS 가 계산한 net_income 을 명시 전달

### Phase A — 발생주의 손익계산서 (entity 13)
- `backend/services/statements/income_statement_accrual.py` 신규
- 시그니처:
  ```python
  def generate_income_statement_accrual(
      conn, cur, stmt_id, entity_id, start_date, end_date,
      vat_excluded: bool = True
  ) -> dict:  # returns {"net_income", "total_revenue", "total_cogs", ...}
  ```
- **이중 카운팅 방지 (🔴 위험 2):**
  - 매출 (수익 카테고리): `wholesale_sales` ONLY — journal_entries 의 수익 카테고리 EXCLUDE
  - 매출원가: `wholesale_sales.quantity × cogs_unit_price` ONLY — journal_entries 매출원가 EXCLUDE
  - 판관비 / 영업외 / 법인세: journal_entries (기존 income_statement.py 와 동일)
- statements router `/generate`: `basis: Literal["cash","accrual"] = "cash"` body 파라미터

### Phase D-1Q — IS 검증 (Phase A 직후, 즉시)
- 26년 1-3월 한아원홀세일 IS_accrual generate → PDF 매출/매출원가/VAT 비교
- 99%+ PASS 시 Phase B 진입. FAIL 시 데이터 매핑 재검토.
- 보고서: `docs/statements-accrual-validation-2026-05-08-IS.md`

### Phase B — 발생주의 재무상태표
- `backend/services/statements/balance_sheet_accrual.py` 신규
- 시그니처:
  ```python
  def generate_balance_sheet_accrual(
      conn, cur, stmt_id, entity_id, fiscal_year, as_of_date, start_date,
      net_income_override: Decimal,  # 🔴 IS_accrual 에서 전달
      vat_excluded: bool = True
  ) -> dict
  ```
- **🔴 위험 1 대응:** balance_sheet.py:209-213 의 journal_entries net_income 계산 안 함 → `net_income_override` 를 결손금에 가산
- 외상매출금 / 외상매입금 / 부가세예수금 / 부가세대급금 line_items 추가

### Phase D-2Q — BS+IS 통합 검증
- IS_accrual.net_income == BS_accrual 결손금 가산분 (Decimal 동일)
- 자산 = 부채 + 자본 (오차 < 1)
- 외상매출금/매입금 PDF 대비 ±5% (KPI 추가 — 🟡 우려 3)

### Phase C — UX 토글
- 페이지: [기준: 현금주의 / 발생주의 (K-GAAP)] 셀렉트
- list API filter 에 basis 추가
- 카드 헤더 basis badge

### Phase E — 다른 entity 대응 (low priority)
- entity 2/3 invoices 데이터 검증 후 진입
- entity 1 (HOI) 별도 phase

## 6. 비-범위 (이번 phase 제외)

- HOI (entity 1) — US GAAP 별도 phase
- 한아원코리아/리테일 invoices 데이터 적재 (UI 경고만 표시)
- 판관비 외상/정산 base accrual (91% → 100% 만들기) — 별도 phase, mapping_rules settlement 활용 필요
- 외상매출금 회수 forecast 시뮬레이션
- AI 매핑 학습 강화 (`project_ai_learning_backlog.md`)

## 7. 위험 / Known limitations

- **payee_aliases 회수율 매핑 한계** (현재 36.1%) — 외상매출금 잔액 정확도 ±수억 가능. 도매업 외상 주기 정상.
- **wholesale_purchases 매칭 알고리즘 부재** — 외상매입금은 거래처 단순 매칭 (정확도 떨어질 수 있음). 결산자료 base 보정 필요.
- **판관비 91% 갭 (₩11.5M)** — 발생주의 모드에서도 자동 100% 안 됨. 외상/정산 매핑은 별도 phase.
- **4월 매출 외상** — 5-6월 입금이 일어나기 전이라 "미회수" 로 분류됨. 정상 동작.

## 8. 검증 기준 (성공 = 모두 통과)

### IS (Phase D-1Q)
- [ ] 26년 1-3월 한아원홀세일 발생주의 매출 PDF 대비 99%+ 매칭
- [ ] 26년 1-3월 매입 PDF 대비 99%+ 매칭
- [ ] 26년 1-3월 부가세예수금/대급금 PDF 대비 99%+ 매칭

### BS (Phase D-2Q)
- [ ] BS 항등식: 자산 = 부채 + 자본 (오차 < 1)
- [ ] **IS_accrual.net_income == BS_accrual 결손금 가산분** (🔴 위험 1)
- [ ] 시산표: 차변 = 대변
- [ ] 외상매출금 PDF 대비 ±5% (🟡 우려 3 — 신규 KPI)
- [ ] 외상매입금 PDF 대비 ±5%

### 회귀
- [ ] basis='cash' 모드 기존 동작 변경 없음 (golden output diff = 0)
- [ ] 기존 financial_statements record 모두 basis='cash' backfill 완료
- [ ] UNIQUE 제약 재정의 후 동일 entity/period 의 cash + accrual record 공존 가능

## 8.1 pytest invariant (`backend/tests/test_statements_accrual.py`)

```python
# 1. cash 모드 회귀: golden output diff 0
def test_cash_mode_unchanged():
    result = generate_all_statements(..., basis="cash")
    assert result == golden_cash_2603  # 기존 결과와 동일

# 2. accrual 모드 net_income 일관성
def test_accrual_net_income_consistency():
    is_result = generate_income_statement_accrual(...)
    bs_result = generate_balance_sheet_accrual(..., net_income_override=is_result["net_income"])
    assert bs_result["retained_earnings_delta"] == is_result["net_income"]

# 3. 발생주의 매출 = wholesale_sales SUM
def test_accrual_revenue_source():
    is_result = generate_income_statement_accrual(..., vat_excluded=True)
    expected = SELECT SUM(supply_amount) FROM wholesale_sales WHERE ...
    assert is_result["total_revenue"] == expected

# 4. 외상매출금 ≥ 0
def test_receivables_non_negative():
    bs = generate_balance_sheet_accrual(...)
    assert bs["accounts_receivable"] >= 0

# 5. 시산표 차변 = 대변
def test_trial_balance_balanced():
    tb = generate_trial_balance(..., basis="accrual")
    assert abs(tb["debit_total"] - tb["credit_total"]) < Decimal("0.01")
```

## 9. 산출물

1. DB 마이그레이션 1건 (`financial_statements.basis`)
2. backend 신규 모듈 2개 (income_statement_accrual, balance_sheet_accrual)
3. statements router `basis` 파라미터 추가
4. 프론트 토글 UI
5. pytest 5개 추가
6. 검증 보고서 1건 (`docs/statements-accrual-validation-2026-05-08.md`)
