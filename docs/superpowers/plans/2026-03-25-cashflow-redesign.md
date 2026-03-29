# Cashflow Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현금흐름 페이지를 목업(`docs/cashflow-redesign-mockup.html`) 기준 3탭 구조로 재설계 — 실제 현금흐름, 예상 현금흐름(시차 보정 포함), 비용(카드 사용)

**Architecture:** 백엔드 3개 API (실제/예상/카드비용) + 기초잔고 역산 로직 + forecasts CRUD. 프론트엔드는 기존 cashflow/page.tsx를 3탭 구조로 교체하고, 탭별 컴포넌트를 분리. 차트는 Recharts 유지.

**Tech Stack:** FastAPI (Python), Next.js 14, Recharts, shadcn/ui, PostgreSQL (Neon)

**Design Reference:** `docs/cashflow-redesign-mockup.html` (v4)

**예상 기말 공식 (목업 448-453행 그대로):**
```
예상 기말 = 전월 확정 기말
  + 예상 입금
  - 예상 출금
  - 예상 카드 사용액
  + (전월 카드 사용액 - 당월 예상 카드 사용액) ← 시차 보정
```
> **주의:** `예상 출금`은 forecasts에서 type='out'인 항목만 합산 (card는 별도).
> `예상 카드 사용액`은 당월 카드 사용 예상 (forecasts에서 type='card' 항목 합산, 없으면 전월 실적 fallback).
> 시차 보정 = 전월 카드 사용 확정액 - 당월 카드 사용 예상액.

**SQL 규칙:** 모든 날짜 필터는 `date >= make_date(y,m,1) AND date < make_date(y,m,1) + interval '1 month'` 사용 (EXTRACT 금지 — 인덱스 활용).

**Decimal 규칙:** psycopg2가 NUMERIC을 Decimal으로 반환하므로, API 응답에 포함되는 모든 금액 필드는 `float()`으로 변환.

---

## 리뷰 확정 사항

### 1. 카드 설정 테이블 분리 ✅ 확정
카드 결제일(롯데 15일, 우리 25일), 카드사 정보는 forecasts가 아닌 별도 테이블로 관리.
```sql
CREATE TABLE card_settings (
  id          SERIAL PRIMARY KEY,
  entity_id   INTEGER NOT NULL REFERENCES entities(id),
  card_name   TEXT NOT NULL,          -- '롯데카드', '우리카드'
  source_type TEXT NOT NULL,          -- 'lotte_card', 'woori_card'
  payment_day INTEGER NOT NULL,       -- 결제일 (15, 25 등)
  card_number TEXT,                   -- 마지막 4자리 (****1234)
  is_active   BOOLEAN DEFAULT TRUE,
  UNIQUE(entity_id, source_type)
);
```
→ 예상 현금흐름 차트의 결제일 마커, 시차 보정 카드별 분리에 사용.

**API 응답 변경:** forecast API의 `card_timing`이 현재 하드코딩 구조인데, card_settings에서 카드사 목록/결제일을 동적으로 조회하여 구성해야 함.
- 시차 보정을 카드별로 분리 (card_settings의 각 카드마다 전월/당월 사용액 계산)
- 차트의 결제일 마커 위치도 card_settings.payment_day에서 가져옴
- 카드가 추가/삭제되어도 코드 수정 없이 동작

**Task 1에 포함:** card_settings CREATE TABLE 마이그레이션 + seed 데이터 (entity_id=2: 롯데카드 payment_day=15, 우리카드 payment_day=25). card-expense SQL에서 하드코딩 `IN ('lotte_card', 'woori_card')` 대신 card_settings 조회로 변경.

### 2. forecasts 테이블 컬럼 보강 ✅ 확정
type='card' 추가 확정. 카드 사용 예상을 별도 type으로 구분.
- `type`에 'card' 추가 — 카드 사용 예상을 'in'/'out'과 분리
- `forecast_expense`는 type='out'만 합산 (card는 별도)
- `forecast_card`는 type='card'로 필터

### 3. 예상 카드 사용액 기본값
- 기본값 = 전월 카드 사용 실적 (transactions에서 자동 계산)
- forecasts에 카드 사용 예상이 없으면 전월 실적을 fallback으로 사용
- 별도 예측 공식은 추후 정의

---

## File Structure

### Backend (신규/수정)
| 파일 | 역할 |
|---|---|
| `backend/routers/cashflow.py` (신규) | 현금흐름 전용 라우터 — 실제/예상/카드비용 3 API |
| `backend/routers/forecasts.py` (신규) | forecasts CRUD API |
| `backend/services/cashflow_service.py` (신규) | 기초잔고 역산, 일별 잔고 계산, 시차 보정 로직 |
| `backend/routers/dashboard.py` (수정) | `/cashflow`, `/cashflow/detail` 엔드포인트 제거 (cashflow.py로 이동) |
| `backend/main.py` (수정) | 새 라우터 등록 |

### Frontend (신규/수정)
| 파일 | 역할 |
|---|---|
| `frontend/src/app/cashflow/page.tsx` (교체) | 3탭 레이아웃 + 탭 전환 |
| `frontend/src/app/cashflow/actual-tab.tsx` (신규) | 탭1: 실제 현금흐름 (차트 + KPI + 거래리스트) |
| `frontend/src/app/cashflow/forecast-tab.tsx` (신규) | 탭2: 예상 현금흐름 (예상vs실제 차트 + 이벤트리스트 + 시차보정) |
| `frontend/src/app/cashflow/expense-tab.tsx` (신규) | 탭3: 비용 카드 사용 (카드/회원별 드릴다운) |

### Tests
| 파일 | 역할 |
|---|---|
| `backend/tests/test_cashflow.py` (신규) | 기초잔고 역산, 시차 보정, API 응답 검증 |

---

## Task 1: 기초잔고 역산 + 실제 현금흐름 API

**Files:**
- Create: `backend/services/cashflow_service.py`
- Create: `backend/routers/cashflow.py`
- Modify: `backend/main.py` — 라우터 등록
- Migration: `card_settings` CREATE TABLE
- Test: `backend/tests/test_cashflow.py`

### card_settings 마이그레이션 + seed

- [ ] **Step 0a: card_settings CREATE TABLE 마이그레이션**

Alembic 마이그레이션 생성:
```sql
CREATE TABLE card_settings (
  id          SERIAL PRIMARY KEY,
  entity_id   INTEGER NOT NULL REFERENCES entities(id),
  card_name   TEXT NOT NULL,
  source_type TEXT NOT NULL,
  payment_day INTEGER NOT NULL,
  card_number TEXT,
  is_active   BOOLEAN DEFAULT TRUE,
  UNIQUE(entity_id, source_type)
);
```

- [ ] **Step 0b: seed 데이터 (entity_id=2 한아원코리아)**

```sql
INSERT INTO card_settings (entity_id, card_name, source_type, payment_day)
VALUES
  (2, '롯데카드', 'lotte_card', 15),
  (2, '우리카드', 'woori_card', 25);
```

- [ ] **Step 0c: card-expense SQL에서 card_settings 조회로 변경**

하드코딩 `IN ('lotte_card', 'woori_card')` 대신:
```sql
AND t.source_type IN (SELECT source_type FROM card_settings WHERE entity_id = %s AND is_active = TRUE)
```

### 주의: 기존 업로드 기능 유지
데이터 입력은 기존 Excel/CSV 업로드(`/api/upload`)가 담당 — 절대 제거하지 않음.
Task 1의 API는 업로드된 transactions/balance_snapshots 데이터를 **조회/계산**하는 읽기 전용 API.

### 기초잔고: 업로드 시 opening_balance도 저장
우리은행 파서(`WooriBankParser.parse_with_balance`)가 이미 opening_balance(마지막 행 잔고에서 역산)를 반환함.
현재 upload.py는 closing_balance만 balance_snapshots에 저장 → **opening_balance도 함께 저장하도록 수정**.

```
우리은행 Excel (역순):
  행1: 12/31 잔고 ₩161,050,376 ← closing (first_balance)
  ...
  행N: 12/01 잔고 ₩211,500,000, 입금 +₩500K ← opening (last_balance - 첫 거래 반영 전)
```

파서가 반환하는 opening_balance를 balance_snapshots에 저장하면,
cashflow에서는 스냅샷 조회만으로 기초잔고를 바로 가져올 수 있음 → 별도 역산 불필요.

### 핵심 로직 (단순화)
기초잔고: balance_snapshots에서 해당 월 시작일 기준 opening 스냅샷 조회.
기말잔고: balance_snapshots에서 해당 월 말일 기준 closing 스냅샷 조회.
없으면 전월 기말에서 체이닝.
- 12월 기초잔고 = 기말잔고 - 12월 순거래(입금-출금)
- 1월 기초잔고 = 12월 기말잔고 (= balance_snapshot 값)
- 이후 월은 running balance로 계산

일별 거래 리스트: 은행 거래만 날짜순 + 잔고 누적. 카드대금 결제는 `description LIKE '%카드%'` 또는 `counterparty`로 감지하여 유형 태깅.

- [ ] **Step 1: 테스트 작성 — 기초잔고 역산**

`backend/tests/test_cashflow.py`:
```python
"""현금흐름 서비스 테스트."""
import pytest
from unittest.mock import MagicMock
from backend.services.cashflow_service import calc_opening_balance


class TestOpeningBalance:
    def test_reverse_calc_from_snapshot(self):
        """스냅샷 기말잔고에서 거래를 빼서 기초잔고 역산."""
        # 12/31 스냅샷: 161,050,376
        # 12월 은행 거래: 입금 200M, 출금 250M → 순 -50M
        # 따라서 12월 기초 = 161,050,376 - (-50,000,000) = 211,050,376
        snapshot_balance = 161_050_376
        month_net = -50_000_000  # 입금 - 출금
        opening = calc_opening_balance(snapshot_balance, month_net)
        assert opening == 211_050_376

    def test_no_transactions_opening_equals_snapshot(self):
        """거래 0건이면 기초 = 기말."""
        opening = calc_opening_balance(100_000, 0)
        assert opening == 100_000
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_cashflow.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.cashflow_service'`

- [ ] **Step 3: cashflow_service.py 구현**

`backend/services/cashflow_service.py`:
```python
"""현금흐름 계산 서비스 — 기초잔고 역산, 일별 잔고, 시차 보정."""

from psycopg2.extensions import connection as PgConnection


def calc_opening_balance(closing_balance: float, month_net: float) -> float:
    """기말잔고와 월 순거래에서 기초잔고 역산.
    기초 = 기말 - 순거래 (순거래 = 입금 - 출금)
    """
    return round(closing_balance - month_net, 2)


def get_actual_cashflow(conn: PgConnection, entity_id: int, year: int, month: int) -> dict:
    """실제 현금흐름 — 은행 거래 기반 월별 데이터.

    Returns:
        opening_balance, closing_balance, income, expense, net,
        transactions (일별 거래 + running balance)
    """
    cur = conn.cursor()

    # 1. 해당 월 은행 거래 (날짜순)
    cur.execute(
        """
        SELECT id, date, type, amount, description, counterparty, source_type
        FROM transactions
        WHERE entity_id = %s
          AND source_type IN ('woori_bank', 'mercury_api', 'manual')
          AND date >= make_date(%s, %s, 1)
          AND date < make_date(%s, %s, 1) + interval '1 month'
        ORDER BY date, id
        """,
        [entity_id, year, month, year, month],
    )
    cols = [d[0] for d in cur.description]
    raw_txns = [dict(zip(cols, r)) for r in cur.fetchall()]

    # 2. 해당 월 합계
    income = sum(float(t["amount"]) for t in raw_txns if t["type"] == "in")
    expense = sum(float(t["amount"]) for t in raw_txns if t["type"] == "out")
    net = round(income - expense, 2)

    # 3. 기초잔고 — balance_snapshots에서 직접 조회
    #    업로드 시 opening/closing 모두 저장되므로 스냅샷 조회만으로 충분
    #    opening: 해당 월 이전의 가장 최근 closing (= 전월 기말)
    cur.execute(
        """
        SELECT balance FROM balance_snapshots
        WHERE entity_id = %s AND account_type = 'bank'
          AND date < make_date(%s, %s, 1)
        ORDER BY date DESC LIMIT 1
        """,
        [entity_id, year, month],
    )
    snap = cur.fetchone()
    opening_balance = float(snap[0]) if snap else 0.0

    closing_balance = round(opening_balance + net, 2)

    # 4. 일별 거래에 running balance 추가
    running = opening_balance
    transactions = []
    for t in raw_txns:
        delta = t["amount"] if t["type"] == "in" else -t["amount"]
        running = round(running + delta, 2)

        # 카드대금 감지
        desc = (t["description"] or "").lower()
        cp = (t["counterparty"] or "").lower()
        tx_subtype = "in" if t["type"] == "in" else "out"
        if any(kw in desc or kw in cp for kw in ["카드", "롯데카드", "우리카드", "선결제"]):
            tx_subtype = "card"

        transactions.append({
            "id": t["id"],
            "date": str(t["date"]),
            "type": t["type"],
            "subtype": tx_subtype,
            "amount": t["amount"],
            "description": t["description"],
            "counterparty": t["counterparty"],
            "balance": running,
        })

    # 5. 카드대금 드릴다운 — subtype='card'인 거래의 해당 월 카드 상세
    #    카드대금 행은 전월 카드 사용분이 결제된 것이므로, 전월 카드 거래를 회원별로 그룹핑
    card_drilldown = {}
    card_txns = [t for t in transactions if t["subtype"] == "card" and t["type"] == "out"]
    if card_txns:
        # 전월 카드 거래를 회원별로 가져옴
        card_prev_month = month - 1 if month > 1 else 12
        card_prev_year = year if month > 1 else year - 1
        cur.execute(
            """
            SELECT t.source_type, t.member_id, COALESCE(m.name, '미지정') AS member_name,
                   SUM(CASE WHEN t.type = 'out' THEN t.amount ELSE 0 END) AS expense,
                   SUM(CASE WHEN t.type = 'in' THEN t.amount ELSE 0 END) AS refund,
                   COUNT(*) AS tx_count
            FROM transactions t
            LEFT JOIN members m ON t.member_id = m.id
            WHERE t.entity_id = %s
              AND t.source_type IN (SELECT source_type FROM card_settings WHERE entity_id = %s AND is_active = TRUE)
              AND t.date >= make_date(%s, %s, 1)
              AND t.date < make_date(%s, %s, 1) + interval '1 month'
            GROUP BY t.source_type, t.member_id, m.name
            ORDER BY t.source_type, expense DESC
            """,
            [entity_id, entity_id, card_prev_year, card_prev_month, card_prev_year, card_prev_month],
        )
        cols_cd = [d[0] for d in cur.description]
        for r in cur.fetchall():
            row = dict(zip(cols_cd, r))
            key = row["source_type"]
            if key not in card_drilldown:
                card_drilldown[key] = []
            card_drilldown[key].append({
                "member_id": row["member_id"],
                "member_name": row["member_name"],
                "expense": float(row["expense"]),
                "refund": float(row["refund"]),
                "net": round(float(row["expense"]) - float(row["refund"]), 2),
                "tx_count": row["tx_count"],
            })

    cur.close()

    return {
        "year": year,
        "month": month,
        "opening_balance": opening_balance,
        "closing_balance": closing_balance,
        "income": income,
        "expense": expense,
        "net": net,
        "transactions": transactions,
        "tx_count": len(transactions),
        "card_drilldown": card_drilldown,
    }


def get_monthly_summary(conn: PgConnection, entity_id: int, months: int = 6) -> list[dict]:
    """월별 요약 — 기초/기말잔고 포함 (차트용)."""
    cur = conn.cursor()

    # 가장 오래된 스냅샷 찾기
    cur.execute(
        """
        SELECT date, balance FROM balance_snapshots
        WHERE entity_id = %s AND account_type = 'bank'
        ORDER BY date DESC LIMIT 1
        """,
        [entity_id],
    )
    snap_row = cur.fetchone()
    snap_date = snap_row[0] if snap_row else None
    snap_balance = float(snap_row[1]) if snap_row else 0.0

    # 월별 은행 거래 합계
    cur.execute(
        """
        SELECT
            to_char(date_trunc('month', date), 'YYYY-MM') AS month_str,
            COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0) AS income,
            COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0) AS expense
        FROM transactions
        WHERE entity_id = %s
          AND source_type IN ('woori_bank', 'mercury_api', 'manual')
          AND date >= (%s - interval '1 month')
        GROUP BY date_trunc('month', date)
        ORDER BY month_str
        """,
        [entity_id, snap_date],
    )
    rows = cur.fetchall()
    cur.close()

    if not rows:
        return []

    # 스냅샷 기준으로 기초잔고 역산
    # 스냅샷 월을 찾고, 그 월의 기말 = snap_balance
    # 이전 월들은 역순으로 기초 = 기말 - net
    # 이후 월들은 순방향으로 기초 = 전월 기말

    from datetime import date as dt_date

    month_data = []
    for r in rows:
        month_str = r[0]
        y, m = int(month_str[:4]), int(month_str[5:7])
        inc, exp = float(r[1]), float(r[2])
        month_data.append({
            "month": month_str,
            "year": y,
            "m": m,
            "income": inc,
            "expense": exp,
            "net": round(inc - exp, 2),
        })

    # 스냅샷 월 인덱스 찾기
    snap_month_idx = None
    if snap_date:
        snap_month_str = snap_date.strftime("%Y-%m")
        for i, md in enumerate(month_data):
            if md["month"] == snap_month_str:
                snap_month_idx = i
                break

    if snap_month_idx is not None:
        # 스냅샷 월의 기말 = snap_balance
        month_data[snap_month_idx]["closing_balance"] = snap_balance
        month_data[snap_month_idx]["opening_balance"] = calc_opening_balance(
            snap_balance, month_data[snap_month_idx]["net"]
        )

        # 이전 월 역산 (역순)
        for i in range(snap_month_idx - 1, -1, -1):
            next_opening = month_data[i + 1]["opening_balance"]
            month_data[i]["closing_balance"] = next_opening
            month_data[i]["opening_balance"] = calc_opening_balance(
                next_opening, month_data[i]["net"]
            )

        # 이후 월 순방향
        for i in range(snap_month_idx + 1, len(month_data)):
            prev_closing = month_data[i - 1]["closing_balance"]
            month_data[i]["opening_balance"] = prev_closing
            month_data[i]["closing_balance"] = round(prev_closing + month_data[i]["net"], 2)
    else:
        # 스냅샷 없으면 0부터 시작
        running = 0.0
        for md in month_data:
            md["opening_balance"] = running
            md["closing_balance"] = round(running + md["net"], 2)
            running = md["closing_balance"]

    # 최근 N개월만 반환
    result = month_data[-months:] if len(month_data) > months else month_data
    return [
        {
            "month": md["month"],
            "opening_balance": md["opening_balance"],
            "income": md["income"],
            "expense": md["expense"],
            "net": md["net"],
            "closing_balance": md["closing_balance"],
        }
        for md in result
    ]
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_cashflow.py -v`
Expected: PASS

- [ ] **Step 5: cashflow 라우터 작성**

`backend/routers/cashflow.py`:
```python
"""현금흐름 API — 실제/예상/카드비용."""

from fastapi import APIRouter, Query, Depends
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db
from backend.services.cashflow_service import get_actual_cashflow, get_monthly_summary

router = APIRouter(prefix="/api/cashflow", tags=["cashflow"])


@router.get("/actual")
def actual_cashflow(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """실제 현금흐름 — 특정 월의 은행 거래 일별 리스트 + 잔고."""
    return get_actual_cashflow(conn, entity_id, year, month)


@router.get("/summary")
def cashflow_summary(
    entity_id: int = Query(...),
    months: int = Query(6, ge=1, le=24),
    conn: PgConnection = Depends(get_db),
):
    """월별 요약 — 기초/기말잔고 포함 (차트용)."""
    return {"months": get_monthly_summary(conn, entity_id, months)}


@router.get("/card-expense")
def card_expense(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """카드 사용 월별 상세 — 카드별/회원별 그룹핑."""
    cur = conn.cursor()

    # 카드 거래 (회원별 그룹핑)
    cur.execute(
        """
        SELECT t.source_type, t.type, t.amount, t.description, t.counterparty,
               t.date, t.member_id, m.name AS member_name
        FROM transactions t
        LEFT JOIN members m ON t.member_id = m.id
        WHERE t.entity_id = %s
          AND t.source_type IN ('lotte_card', 'woori_card')
          AND t.date >= make_date(%s, %s, 1)
          AND t.date < make_date(%s, %s, 1) + interval '1 month'
        ORDER BY t.source_type, t.member_id, t.date
        """,
        [entity_id, year, month, year, month],
    )
    cols = [d[0] for d in cur.description]
    txns = [dict(zip(cols, r)) for r in cur.fetchall()]

    # 카드별 합계
    cur.execute(
        """
        SELECT source_type,
               SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END) AS total_out,
               SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END) AS total_refund,
               COUNT(*) AS tx_count
        FROM transactions
        WHERE entity_id = %s
          AND source_type IN ('lotte_card', 'woori_card')
          AND date >= make_date(%s, %s, 1)
          AND date < make_date(%s, %s, 1) + interval '1 month'
        GROUP BY source_type
        """,
        [entity_id, year, month, year, month],
    )
    summary = []
    total_out = 0.0
    total_refund = 0.0
    total_count = 0
    for r in cur.fetchall():
        out, refund = float(r[1]), float(r[2])
        total_out += out
        total_refund += refund
        total_count += r[3]
        summary.append({
            "source_type": r[0],
            "total_expense": out,
            "total_refund": refund,
            "net": round(out - refund, 2),
            "tx_count": r[3],
        })

    # 내부계정별 그룹핑 (목업 521-531행)
    cur.execute(
        """
        SELECT COALESCE(sa.name, '기타') AS account_name,
               SUM(CASE WHEN t.type = 'out' THEN t.amount ELSE 0 END) AS expense,
               SUM(CASE WHEN t.type = 'in' THEN t.amount ELSE 0 END) AS refund
        FROM transactions t
        LEFT JOIN standard_accounts sa ON t.standard_account_id = sa.id
        WHERE t.entity_id = %s
          AND t.source_type IN ('lotte_card', 'woori_card')
          AND t.date >= make_date(%s, %s, 1)
          AND t.date < make_date(%s, %s, 1) + interval '1 month'
        GROUP BY COALESCE(sa.name, '기타')
        ORDER BY expense DESC
        """,
        [entity_id, year, month, year, month],
    )
    account_breakdown = [
        {"account": r[0], "expense": float(r[1]), "refund": float(r[2]),
         "net": round(float(r[1]) - float(r[2]), 2)}
        for r in cur.fetchall()
    ]

    # 전월 카드 합계 (월별 비교용)
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    cur.execute(
        """
        SELECT
            SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END) -
            SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END)
        FROM transactions
        WHERE entity_id = %s
          AND source_type IN ('lotte_card', 'woori_card')
          AND date >= make_date(%s, %s, 1)
          AND date < make_date(%s, %s, 1) + interval '1 month'
        """,
        [entity_id, prev_year, prev_month, prev_year, prev_month],
    )
    prev_net = float(cur.fetchone()[0] or 0)

    cur.close()

    net_total = round(total_out - total_refund, 2)
    change_pct = round((net_total - prev_net) / prev_net * 100, 1) if prev_net else None

    return {
        "year": year,
        "month": month,
        "total_expense": total_out,
        "total_refund": total_refund,
        "net": net_total,
        "tx_count": total_count,
        "cards": summary,
        "transactions": txns,
        "account_breakdown": account_breakdown,
        "prev_month_net": prev_net,
        "change_pct": change_pct,
    }
```

- [ ] **Step 6: main.py에 라우터 등록**

`backend/main.py`에 추가:
```python
from backend.routers.cashflow import router as cashflow_router
app.include_router(cashflow_router)
```

- [ ] **Step 7: API 수동 테스트**

Run: `curl -s "http://localhost:8000/api/cashflow/actual?entity_id=2&year=2026&month=1" | python3 -m json.tool | head -20`
Expected: opening_balance, closing_balance, transactions 배열이 있는 JSON

Run: `curl -s "http://localhost:8000/api/cashflow/summary?entity_id=2&months=6" | python3 -m json.tool`
Expected: months 배열에 opening_balance, closing_balance 포함

Run: `curl -s "http://localhost:8000/api/cashflow/card-expense?entity_id=2&year=2026&month=1" | python3 -m json.tool | head -15`
Expected: cards 배열, net, total_expense 등

- [ ] **Step 8: 통합 테스트 작성**

`backend/tests/test_cashflow.py`에 추가:
```python
class TestActualCashflowIntegration:
    def test_actual_cashflow_normal_month(self, test_db):
        """정상 월: 기초잔고 + 거래 → 기말잔고 검증."""
        # entity_id=2, 2026년 1월 — 스냅샷과 거래가 있는 월
        result = get_actual_cashflow(test_db, entity_id=2, year=2026, month=1)
        assert result["opening_balance"] > 0
        assert result["closing_balance"] == round(
            result["opening_balance"] + result["net"], 2
        )
        assert result["tx_count"] == len(result["transactions"])

    def test_actual_cashflow_empty_month(self, test_db):
        """거래 0건 월: 기초 = 기말, transactions 빈 배열."""
        result = get_actual_cashflow(test_db, entity_id=2, year=2020, month=1)
        assert result["tx_count"] == 0
        assert result["income"] == 0
        assert result["expense"] == 0
```

- [ ] **Step 9: 커밋**

```bash
git add backend/services/cashflow_service.py backend/routers/cashflow.py backend/main.py backend/tests/test_cashflow.py
git commit -m "feat: cashflow service — 기초잔고 역산 + 실제/카드비용 API"
```

---

## Task 2: Forecasts CRUD API

**Files:**
- Create: `backend/routers/forecasts.py`
- Modify: `backend/main.py` — 라우터 등록

### forecasts 테이블 구조 (이미 존재)
```
id, entity_id, year, month, category, subcategory, type,
forecast_amount, actual_amount, is_recurring, note
```

- [ ] **Step 1: forecasts 라우터 작성**

`backend/routers/forecasts.py`:
```python
"""Forecasts CRUD API."""

from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from psycopg2.extensions import connection as PgConnection

from backend.database.connection import get_db

router = APIRouter(prefix="/api/forecasts", tags=["forecasts"])


class ForecastCreate(BaseModel):
    entity_id: int
    year: int
    month: int
    category: str
    subcategory: Optional[str] = None
    type: str  # 'in', 'out', or 'card'
    forecast_amount: float
    is_recurring: bool = False
    note: Optional[str] = None


class ForecastUpdate(BaseModel):
    forecast_amount: Optional[float] = None
    actual_amount: Optional[float] = None
    note: Optional[str] = None


@router.get("")
def list_forecasts(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, entity_id, year, month, category, subcategory, type,
               forecast_amount, actual_amount, is_recurring, note
        FROM forecasts
        WHERE entity_id = %s AND year = %s AND month = %s
        ORDER BY type DESC, category
        """,
        [entity_id, year, month],
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return {"items": rows}


@router.post("")
def create_forecast(
    body: ForecastCreate,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO forecasts (entity_id, year, month, category, subcategory,
                               type, forecast_amount, is_recurring, note)
        VALUES (%s, %s, %s, %s, COALESCE(%s, ''), %s, %s, %s, %s)
        ON CONFLICT (entity_id, year, month, category, subcategory, type)
        DO UPDATE SET forecast_amount = EXCLUDED.forecast_amount,
                      is_recurring = EXCLUDED.is_recurring,
                      note = EXCLUDED.note,
                      updated_at = NOW()
        RETURNING id
        """,
        [body.entity_id, body.year, body.month, body.category,
         body.subcategory, body.type, body.forecast_amount,
         body.is_recurring, body.note],
    )
    forecast_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    return {"id": forecast_id}


@router.put("/{forecast_id}")
def update_forecast(
    forecast_id: int,
    body: ForecastUpdate,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    updates = []
    params = []
    if body.forecast_amount is not None:
        updates.append("forecast_amount = %s")
        params.append(body.forecast_amount)
    if body.actual_amount is not None:
        updates.append("actual_amount = %s")
        params.append(body.actual_amount)
    if body.note is not None:
        updates.append("note = %s")
        params.append(body.note)
    if not updates:
        raise HTTPException(400, "수정할 항목이 없습니다.")

    updates.append("updated_at = NOW()")
    params.append(forecast_id)

    cur.execute(
        f"UPDATE forecasts SET {', '.join(updates)} WHERE id = %s RETURNING id",
        params,
    )
    if not cur.fetchone():
        raise HTTPException(404, "예측 항목을 찾을 수 없습니다.")
    conn.commit()
    cur.close()
    return {"id": forecast_id, "updated": True}


@router.delete("/{forecast_id}")
def delete_forecast(
    forecast_id: int,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    cur.execute("DELETE FROM forecasts WHERE id = %s RETURNING id", [forecast_id])
    if not cur.fetchone():
        raise HTTPException(404, "예측 항목을 찾을 수 없습니다.")
    conn.commit()
    cur.close()
    return {"deleted": True}
```

- [ ] **Step 2: main.py에 등록**

```python
from backend.routers.forecasts import router as forecasts_router
app.include_router(forecasts_router)
```

- [ ] **Step 3: 통합 테스트 작성**

`backend/tests/test_forecasts.py`:
```python
class TestForecastsCRUD:
    def test_create_and_list(self, test_client):
        """forecast 생성 후 목록 조회 — 생성한 항목이 포함되어야 함."""
        resp = test_client.post("/api/forecasts", json={
            "entity_id": 2, "year": 2026, "month": 3,
            "category": "매출", "type": "in", "forecast_amount": 100000000,
        })
        assert resp.status_code == 200
        forecast_id = resp.json()["id"]
        list_resp = test_client.get("/api/forecasts?entity_id=2&year=2026&month=3")
        assert any(f["id"] == forecast_id for f in list_resp.json()["items"])

    def test_upsert_same_category(self, test_client):
        """같은 category+type 재등록 시 UPSERT — 금액 업데이트."""
        test_client.post("/api/forecasts", json={
            "entity_id": 2, "year": 2026, "month": 4,
            "category": "SaaS", "type": "out", "forecast_amount": 2000000,
        })
        resp2 = test_client.post("/api/forecasts", json={
            "entity_id": 2, "year": 2026, "month": 4,
            "category": "SaaS", "type": "out", "forecast_amount": 2500000,
        })
        assert resp2.status_code == 200
        list_resp = test_client.get("/api/forecasts?entity_id=2&year=2026&month=4")
        saas_items = [f for f in list_resp.json()["items"] if f["category"] == "SaaS"]
        assert len(saas_items) == 1
        assert saas_items[0]["forecast_amount"] == 2500000
```

- [ ] **Step 4: 커밋**

```bash
git add backend/routers/forecasts.py backend/main.py backend/tests/test_forecasts.py
git commit -m "feat: forecasts CRUD API"
```

---

## Task 3: 예상 현금흐름 API (시차 보정 포함)

**Files:**
- Modify: `backend/routers/cashflow.py` — forecast 엔드포인트 추가
- Modify: `backend/services/cashflow_service.py` — 시차 보정 로직
- Test: `backend/tests/test_cashflow.py` — 시차 보정 테스트

- [ ] **Step 1: 시차 보정 테스트 작성**

`backend/tests/test_cashflow.py`에 추가:
```python
from backend.services.cashflow_service import calc_card_timing_adjustment


class TestCardTimingAdjustment:
    def test_positive_adjustment(self):
        """전월 카드 > 당월 카드 → 양수 보정."""
        # 1월 카드 17.7M, 2월 카드 12.3M → 보정 +5.4M
        adj = calc_card_timing_adjustment(17_720_895, 12_300_000)
        assert adj == 5_420_895

    def test_negative_adjustment(self):
        """전월 카드 < 당월 카드 → 음수 보정."""
        adj = calc_card_timing_adjustment(10_000_000, 15_000_000)
        assert adj == -5_000_000

    def test_zero_when_equal(self):
        adj = calc_card_timing_adjustment(10_000_000, 10_000_000)
        assert adj == 0
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_cashflow.py::TestCardTimingAdjustment -v`
Expected: FAIL

- [ ] **Step 3: 시차 보정 함수 구현**

`backend/services/cashflow_service.py`에 추가:
```python
def calc_card_timing_adjustment(prev_month_card: float, current_month_card: float) -> float:
    """카드 시차 보정 = 전월 카드 사용액 - 당월 카드 사용액.

    카드 사용은 다음 달에 은행에서 결제됨.
    전월 카드가 더 많으면 → 당월 카드대금 결제가 늘어남 (보정값 양수).
    전월 카드가 더 적으면 → 당월 카드대금 결제가 줄어듦 (보정값 음수).
    """
    return round(prev_month_card - current_month_card, 2)


def get_closing_balance(conn: PgConnection, entity_id: int, year: int, month: int) -> float:
    """balance_snapshots에서 해당 월의 기말잔고를 직접 조회.

    해당 월 내의 가장 최근 스냅샷을 반환. 없으면 0.0.
    get_actual_cashflow 전체를 호출하는 것보다 가볍다.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT balance FROM balance_snapshots
        WHERE entity_id = %s AND account_type = 'bank'
          AND date >= make_date(%s, %s, 1)
          AND date < make_date(%s, %s, 1) + interval '1 month'
        ORDER BY date DESC LIMIT 1
        """,
        [entity_id, year, month, year, month],
    )
    row = cur.fetchone()
    cur.close()
    return float(row[0]) if row else 0.0


def get_forecast_cashflow(conn: PgConnection, entity_id: int, year: int, month: int) -> dict:
    """예상 현금흐름 — forecasts 기반 + 시차 보정 + 실제 진행 비교."""
    cur = conn.cursor()

    # 1. 기초잔고 = 전월 확정 기말 (balance_snapshots 직접 조회)
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    opening_balance = get_closing_balance(conn, entity_id, prev_year, prev_month)

    # 2. forecasts 항목
    cur.execute(
        """
        SELECT id, category, subcategory, type, forecast_amount, actual_amount,
               is_recurring, note
        FROM forecasts
        WHERE entity_id = %s AND year = %s AND month = %s
        ORDER BY type DESC, category
        """,
        [entity_id, year, month],
    )
    cols = [d[0] for d in cur.description]
    items = [dict(zip(cols, r)) for r in cur.fetchall()]

    forecast_income = sum(f["forecast_amount"] for f in items if f["type"] == "in")
    forecast_expense = sum(f["forecast_amount"] for f in items if f["type"] == "out")  # card is separate

    # 3. 실제 진행 (당월 은행 거래 합산)
    actual_data = get_actual_cashflow(conn, entity_id, year, month)
    actual_income = actual_data["income"]
    actual_expense = actual_data["expense"]

    # 4. 카드 시차 보정
    #    전월 카드 사용 합계 (확정)
    cur.execute(
        """
        SELECT COALESCE(
            SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END) -
            SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0
        )
        FROM transactions
        WHERE entity_id = %s
          AND source_type IN ('lotte_card', 'woori_card')
          AND date >= make_date(%s, %s, 1)
          AND date < make_date(%s, %s, 1) + interval '1 month'
        """,
        [entity_id, prev_year, prev_month, prev_year, prev_month],
    )
    prev_card_net = float(cur.fetchone()[0])

    #    당월 카드 사용 (진행 중이면 현재값, 아니면 예상)
    cur.execute(
        """
        SELECT COALESCE(
            SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END) -
            SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0
        )
        FROM transactions
        WHERE entity_id = %s
          AND source_type IN ('lotte_card', 'woori_card')
          AND date >= make_date(%s, %s, 1)
          AND date < make_date(%s, %s, 1) + interval '1 month'
        """,
        [entity_id, year, month, year, month],
    )
    current_card_net = float(cur.fetchone()[0])

    # 예상 카드 사용액 (forecasts에서 type='card' 항목 합산, 없으면 전월 기준)
    forecast_card = sum(
        f["forecast_amount"] for f in items
        if f["type"] == "card"
    )
    if forecast_card == 0:
        forecast_card = prev_card_net  # 예상 없으면 전월과 동일 가정

    timing_adjustment = calc_card_timing_adjustment(prev_card_net, forecast_card)

    # 5. 예상 기말 = 기초 + 예상입금 - 예상출금 - 예상카드사용 + 시차보정
    forecast_closing = round(
        opening_balance + forecast_income - forecast_expense
        - forecast_card + timing_adjustment, 2
    )

    # 6. 실제 진행 기준 기말
    actual_closing = actual_data["closing_balance"]

    # 7. daily_series — 일별 예상 잔고 추이 (차트용)
    #    기초잔고에서 시작, forecast 항목을 일별로 분배, 카드 결제일에 결제 반영
    import calendar
    from datetime import date as dt_date, timedelta

    days_in_month = calendar.monthrange(year, month)[1]

    # card_settings에서 결제일 조회
    cur2 = conn.cursor()
    cur2.execute(
        "SELECT source_type, card_name, payment_day FROM card_settings WHERE entity_id = %s AND is_active = TRUE",
        [entity_id],
    )
    card_settings_rows = cur2.fetchall()
    cur2.close()

    # 카드 결제일별 금액 (전월 카드 사용 확정액을 결제일에 반영)
    card_payment_map = {}  # day -> amount
    for cs_row in card_settings_rows:
        cs_source, cs_name, cs_day = cs_row
        # 해당 카드의 전월 사용 확정액 조회
        cur3 = conn.cursor()
        cur3.execute(
            """
            SELECT COALESCE(
                SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END) -
                SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0
            )
            FROM transactions
            WHERE entity_id = %s AND source_type = %s
              AND date >= make_date(%s, %s, 1)
              AND date < make_date(%s, %s, 1) + interval '1 month'
            """,
            [entity_id, cs_source, prev_year, prev_month, prev_year, prev_month],
        )
        card_amount = float(cur3.fetchone()[0])
        cur3.close()
        pay_day = min(cs_day, days_in_month)
        card_payment_map[pay_day] = card_payment_map.get(pay_day, 0) + card_amount

    # forecast 항목을 균등 분배 (일별)
    daily_forecast_income = forecast_income / days_in_month if days_in_month else 0
    daily_forecast_expense = forecast_expense / days_in_month if days_in_month else 0

    # 실제 일별 잔고 (은행 거래 기준)
    actual_daily = {}
    for t in actual_data["transactions"]:
        actual_daily[t["date"]] = t["balance"]

    daily_series = []
    projected = opening_balance
    for d in range(1, days_in_month + 1):
        dt = dt_date(year, month, d)
        projected += daily_forecast_income - daily_forecast_expense
        # 카드 결제일이면 결제액 차감
        if d in card_payment_map:
            projected -= card_payment_map[d]
        projected = round(projected, 2)
        daily_series.append({
            "date": str(dt),
            "day": d,
            "projected_balance": projected,
            "actual_balance": actual_daily.get(str(dt)),
            "card_payment": card_payment_map.get(d),
        })

    cur.close()

    return {
        "year": year,
        "month": month,
        "opening_balance": opening_balance,
        "forecast_closing": forecast_closing,
        "actual_closing": actual_closing,
        "diff": round(actual_closing - forecast_closing, 2),
        "forecast_income": forecast_income,
        "forecast_expense": forecast_expense,
        "actual_income": actual_income,
        "actual_expense": actual_expense,
        "card_timing": {
            "prev_month_card": prev_card_net,
            "current_card_actual": current_card_net,
            "current_card_forecast": forecast_card,
            "adjustment": timing_adjustment,
        },
        "items": items,
        "daily_series": daily_series,
    }
```

- [ ] **Step 4: cashflow 라우터에 forecast 엔드포인트 추가**

`backend/routers/cashflow.py`에 추가:
```python
from backend.services.cashflow_service import get_forecast_cashflow

@router.get("/forecast")
def forecast_cashflow(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """예상 현금흐름 — forecasts + 시차 보정 + 실제 비교."""
    return get_forecast_cashflow(conn, entity_id, year, month)
```

- [ ] **Step 5: 테스트 실행**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_cashflow.py -v`
Expected: ALL PASS

- [ ] **Step 6: 통합 테스트 작성**

`backend/tests/test_cashflow.py`에 추가:
```python
class TestForecastCashflowIntegration:
    def test_forecast_with_items(self, test_db):
        """forecasts 항목이 있는 월 — 예상 기말 = 기초 + 입금 - 출금 - 카드 + 시차보정."""
        result = get_forecast_cashflow(test_db, entity_id=2, year=2026, month=2)
        expected_closing = round(
            result["opening_balance"]
            + result["forecast_income"]
            - result["forecast_expense"]
            - result["card_timing"]["current_card_forecast"]
            + result["card_timing"]["adjustment"], 2
        )
        assert result["forecast_closing"] == expected_closing

    def test_forecast_no_items(self, test_db):
        """forecasts 항목 0건 — 예상 입출금 0, 카드 시차만 반영."""
        result = get_forecast_cashflow(test_db, entity_id=2, year=2030, month=1)
        assert result["forecast_income"] == 0
        assert result["forecast_expense"] == 0
        assert result["items"] == []
```

- [ ] **Step 7: 커밋**

```bash
git add backend/services/cashflow_service.py backend/routers/cashflow.py backend/tests/test_cashflow.py
git commit -m "feat: forecast cashflow API — 시차 보정 공식 적용"
```

---

## Task 4: 프론트엔드 — 3탭 레이아웃 + 실제 현금흐름 탭

**Files:**
- Rewrite: `frontend/src/app/cashflow/page.tsx` — 3탭 셸
- Create: `frontend/src/app/cashflow/actual-tab.tsx` — 탭1

### UI 상세 — page.tsx (3탭 셸)

**목업 참조:** 101-108행

```
┌─ 현금흐름 — {법인명} ───────────────────────────┐
│  우리은행 법인통장  (subtitle, text-muted)         │
├─────────────────────────────────────────────────┤
│ [실제 현금흐름]  [예상 현금흐름]  [비용 (카드 사용)] │
│  ↑ active=green    amber          purple          │
└─────────────────────────────────────────────────┘
```

- 탭 바: `flex gap-0 border-b border-border` — 클릭 시 하단 색상 바 전환
  - "실제 현금흐름": 활성 시 `text-green-500 border-b-2 border-green-500`
  - "예상 현금흐름": 활성 시 `text-amber-500 border-b-2 border-amber-500`
  - "비용 (카드 사용)": 활성 시 `text-purple-500 border-b-2 border-purple-500`
  - 비활성: `text-muted-foreground`
- `useState<"actual" | "forecast" | "expense">("actual")`로 탭 전환
- EntityTabs 상단 유지

### UI 상세 — actual-tab.tsx (실제 현금흐름)

#### 1. 월 선택 버튼 (목업 115행)
```
월: [12월] [1월●] [2월]
```
- `flex items-center gap-2` — 데이터가 있는 월만 버튼 생성
- 선택된 월: `bg-green-500 text-black font-semibold border-green-500 rounded-lg px-3.5 py-1.5 text-xs`
- 비선택 월: `bg-card border border-border text-muted-foreground rounded-lg px-3.5 py-1.5 text-xs`
- 월 목록은 `GET /api/cashflow/summary` 응답의 months 배열에서 추출

#### 2. 차트 (목업 117-165행)
```
┌─ Recharts ComposedChart ─────────────────────┐
│   ■ 입금 bar (green gradient)                  │
│   ■ 출금 bar (red gradient)                    │
│   ─ 순현금흐름 line (amber) + area fill        │
│   선택된 월은 bar가 더 굵고 불투명도 높음         │
└──────────────────────────────────────────────┘
범례: ● 입금  ● 출금  ● 순현금흐름
```
- `Card` + `CardContent` 래퍼, `rounded-2xl border border-border bg-card p-6`
- Recharts `ComposedChart` (기존 코드 활용):
  - `Bar` x2: income(green), expense(red) — gradient fill
  - `Area` + `Line`: net(amber) — gradient fill + solid line
  - 선택된 월의 bar에 `opacity: 1, strokeWidth: 1`, 나머지는 `opacity: 0.35-0.5`
- Y축: `abbreviateAmount` 포맷 (₩300M, ₩150M, ₩0)
- Legend: 하단, flex gap-4, dot(8x8 rounded-full) + 라벨

#### 3. 4 KPI 카드 (목업 168-173행)
```
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│기초 잔고   │ │총 입금    │ │총 출금    │ │기말 잔고   │
│₩161.0M   │ │+₩236.0M  │ │-₩289.9M  │ │₩107.2M   │
│           │ │           │ │           │ │순 -₩53.9M │
└──────────┘ └──────────┘ └──────────┘ └──────────┘
```
- `grid grid-cols-4 gap-3`
- 각 카드: `bg-card border border-border rounded-xl p-3.5`
  - 라벨: `text-[10px] text-muted-foreground uppercase tracking-wider`
  - 값: `text-[17px] font-semibold font-mono` — 입금은 `text-green-500`, 출금은 `text-red-500`
  - 기말잔고 하단: `text-[11px]` — 순현금흐름 (pos/neg 색상)
- 반응형: `md:grid-cols-4 grid-cols-2`

#### 4. 거래 리스트 (목업 176-208행)
```
┌────────┬───────┬──────────────────────┬───────────┬───────────┐
│ 날짜    │ 유형   │ 항목                  │ 금액       │ 잔고       │
├────────┼───────┼──────────────────────┼───────────┼───────────┤
│12-31   │       │ 시작 잔고              │ —         │₩161.0M   │ ← 배경 green/3%
│01-02   │ 입금   │ 스마트스토어정산        │+₩1.2M    │₩162.3M   │
│01-04   │ 출금   │ NICE_통신판매          │-₩235K    │₩162.0M   │
│01-08   │ 선결제  │ 롯데카드(주) 선결제     │-₩3.0M    │₩159.0M   │
│01-15   │ 카드대금│ 롯데카드 12월분 ▾      │-₩25.3M   │₩xxx      │ ← 클릭시 드릴다운
│        │ 회원   │   하선우 (****1234) ▾  │-₩5.7M    │           │ ← 2단계
│        │       │     [SaaS] Anthropic   │           │           │ ← 3단계
│        │       │     [교통비] 카카오T     │           │           │
│01-30   │ 입금   │ 스마트스토어정산        │+₩613K    │₩107.2M   │
│        │       │ ... 전체 119건         │           │           │
│01-30   │       │ 기말 잔고              │ —         │₩107.2M   │ ← 배경 green/3%, 상단 green 보더
└────────┴───────┴──────────────────────┴───────────┴───────────┘
```

**레이아웃:**
- 전체 컨테이너: `bg-card border border-border rounded-2xl overflow-hidden`
- 헤더 행: `grid grid-cols-[90px_70px_1fr_120px_130px] px-4 py-2.5 bg-muted/30 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider`
- 일반 행: `grid grid-cols-[90px_70px_1fr_120px_130px] px-4 py-2 border-t border-border text-[13px] items-center hover:bg-white/[0.02] transition-colors`
- 시작잔고 행: `font-semibold bg-green-500/[0.03] border-b border-border`
- 기말잔고 행: `font-semibold bg-green-500/[0.03] border-t-2 border-green-500/15`

**유형 배지:**
- 입금: `bg-green-500/12 text-green-500 text-[10px] font-semibold px-2 py-0.5 rounded`
- 출금: `bg-red-500/12 text-red-500`
- 카드대금: `bg-purple-500/12 text-purple-500`
- 선결제: `bg-purple-500/12 text-purple-500`

**금액:**
- `text-right font-mono text-xs`
- 입금: `text-green-500`, 출금: `text-red-500`

**잔고:**
- `text-right font-mono text-xs font-medium`

**드릴다운 (카드대금):**
- 카드대금 행은 `cursor-pointer` + 항목 텍스트에 ▾ 표시
- 클릭 시 하위 행 toggle (useState)
- 2단계 (회원): `pl-7 bg-black/[0.12] text-xs` — 회원명 + 카드번호 마지막 4자리
- 3단계 (내부계정): `pl-12 bg-black/[0.18] text-[11px]`
  - 내부계정 배지: `text-[9px] font-semibold px-1.5 py-0.5 rounded-sm mr-1`
    - SaaS: `bg-cyan-500/12 text-cyan-500`
    - 교통비: `bg-blue-500/12 text-blue-500`
    - 수수료: `bg-purple-500/12 text-purple-500`
    - 기타: `bg-slate-500/12 text-muted-foreground`

**"전체 N건 펼치기" 행:** (목업 206행)
- 거래가 많을 때 중간 생략 → 클릭 시 전체 표시
- `text-center text-xs text-muted-foreground py-2`

- [ ] **Step 1: page.tsx 3탭 레이아웃으로 교체**

`frontend/src/app/cashflow/page.tsx` — 전체 교체:
- 제목 + subtitle ("우리은행 법인통장")
- 3탭 바 (green/amber/purple 색상 체계)
- `useState`로 탭 전환, 각 탭 컴포넌트를 직접 import (lazy 불필요)
- EntityTabs 상단 유지

- [ ] **Step 2: actual-tab.tsx 구현**

`frontend/src/app/cashflow/actual-tab.tsx`:
- API 2개 호출: `GET /api/cashflow/summary` (차트용) + `GET /api/cashflow/actual` (선택 월 상세)
- 월 선택 시 actual API 재호출
- 위에서 정의한 UI 구조 그대로 구현
- 카드대금 드릴다운: actual API 응답의 `card_drilldown` 필드를 사용하여 카드사별/회원별 그룹핑 표시 (별도 detail API 호출 불필요)
- **5 states 필수 구현** (기존 cashflow/page.tsx 패턴 참조):
  - LOADING: 스켈레톤 UI (카드/테이블 형태에 맞게)
  - EMPTY: 따뜻한 메시지 + CTA 버튼 (예: "데이터를 업로드해보세요")
  - ERROR: 구체적 에러 메시지 + 재시도 버튼
  - SUCCESS: 정상 데이터 표시
  - PARTIAL: 경고 배너 + 가용 데이터 표시

- [ ] **Step 3: 커밋**

```bash
git add frontend/src/app/cashflow/
git commit -m "feat: cashflow 실제 탭 — 3탭 구조 + 기초잔고 역산 + 거래 드릴다운"
```

---

## Task 5: 프론트엔드 — 예상 현금흐름 탭

**Files:**
- Create: `frontend/src/app/cashflow/forecast-tab.tsx`

### UI 상세 — forecast-tab.tsx

#### 1. 월 선택 (목업 216행)
```
예상 월: [2월●] [3월] [4월]
```
- 선택 월: `bg-amber-500 text-black font-semibold` (amber 테마)
- 현재 월 이후의 월만 표시 (미래 예측용)

#### 2. 안내 배너 (목업 218행)
```
┌─ ⚠ 2026년 2월 예상 현금흐름 ──────────────────────────┐
│ 카드/은행 데이터 업로드마다 "실제 진행" 컬럼이              │
│ 업데이트됩니다. 월말에 예상↔실제를 비교합니다.             │
└───────────────────────────────────────────────────────┘
```
- `bg-amber-500/[0.06] border border-amber-500/15 rounded-lg px-4 py-3 text-xs text-amber-500`
- `<strong>` 제목 + 본문

#### 3. 차트 — 예상 vs 실제 잔고 (목업 220-278행)
```
┌─ Recharts AreaChart ──────────────────────────────────┐
│  --- 예상 잔고 (amber dashed + area fill)               │
│  ─── 실제 잔고 (green solid + area fill, 현재까지만)     │
│  │  │  카드 결제일 마커 (purple dashed vertical line)     │
│  │롯데│                                    │우리│          │
└───────────────────────────────────────────────────────┘
범례: ● 예상 잔고 (시차보정 포함)  ● 실제 잔고  ● 카드 결제일
```
- Recharts `ComposedChart`:
  - `Area` #1: 예상 잔고 — `stroke="#F59E0B" strokeDasharray="8 4" fill="amber gradient"`
  - `Area` #2: 실제 잔고 — `stroke="#22C55E" strokeWidth={2.5} fill="green gradient"`
    - 실제 데이터가 있는 날까지만 표시 (이후는 null)
  - `ReferenceLine` x2: 카드 결제일 (롯데 15일, 우리 25일)
    - `stroke="rgba(139,92,246,0.3)" strokeDasharray="3 3"`
    - 상단에 라벨 박스: `bg-purple-500/15 text-purple-500 text-[8px] px-2 py-0.5 rounded`
- X축: 일별 (2/1, 2/7, 2/14, 2/21, 2/28)
- Y축: ₩ 잔고 (abbreviateAmount)
- 실제 잔고의 마지막 점에 glow 효과 + "← 현재" 라벨

#### 4. 4 KPI 카드 (목업 281-286행)
```
┌──────────────┐ ┌──────────────┐ ┌──────────────────┐ ┌──────────────────┐
│기초 (1월 확정) │ │예상 기말      │ │실제 진행 기준 기말  │ │2월 카드 사용 (진행)│
│₩107,168,640  │ │₩95,400,000   │ │₩96,200,000       │ │₩5,200,000       │
│              │ │  (amber)     │ │차이: +₩800K ■■■■  │ │예상 ₩12.3M 중 42%│
└──────────────┘ └──────────────┘ └──────────────────┘ └──────────────────┘
```
- `grid grid-cols-4 gap-3`
- 예상 기말: `text-amber-500`
- 실제 진행: `text-green-500` + diff bar
  - diff bar: `inline-block h-1 rounded-sm ml-1.5`
    - ±5% 이내: `bg-green-500 w-7` (diff-ok)
    - ±10% 이내: `bg-amber-500 w-5` (diff-warn)
    - 그 외: `bg-red-500 w-3.5` (diff-bad)
- 카드 진행: `text-amber-500` + 예상 대비 진행률 표시

#### 5. "실제 비교 펼치기" 토글 (목업 289-291행)
```
                                        [실제 비교 펼치기 ▸]
```
- `text-right mb-2`
- 버튼: `bg-muted/30 border border-border text-muted-foreground px-3.5 py-1.5 rounded-lg text-xs cursor-pointer`
- 클릭 시 4컬럼 ↔ 7컬럼 전환 (CSS transition)
- 상태: `useState<boolean>(false)` → `showActual`

#### 6. 이벤트 리스트 (목업 293-446행)

**접힌 상태 (4컬럼):**
```
┌────────┬───────┬──────────────────────┬───────────┬───────────┐
│ 날짜    │ 유형   │ 항목                  │ 예상 금액   │ 예상 잔고   │
├────────┼───────┼──────────────────────┼───────────┼───────────┤
│01-31   │       │ 시작 잔고              │ —         │₩107.2M   │
│02월    │ 매출   │ 스마트스토어 정산       │+₩226.7M  │₩333.9M   │
│02월    │ SaaS  │ SaaS 구독료 ▾         │-₩2.4M    │₩331.5M   │
│02-28   │시차보정│ 카드 시차 보정 ▾       │+₩5.4M    │₩318.2M   │
│02-28   │       │ 기말 잔고              │ —         │₩95.4M    │
└────────┴───────┴──────────────────────┴───────────┴───────────┘
```

**펼친 상태 (7컬럼 — 실제 비교 포함):**
```
│ 날짜 │ 유형 │ 항목 │ 예상 금액 │ 실제 진행 │ 예상 잔고 │ 실제 잔고 │
```

**레이아웃:**
- 접힌 상태: `grid grid-cols-[80px_80px_1fr_110px_110px]`
- 펼친 상태: `grid grid-cols-[80px_80px_1fr_110px_110px_110px_110px]`
- 전환: `showActual` 상태에 따라 grid-cols 변경 + 실제 컬럼 `overflow-hidden w-0` ↔ `w-auto`

**유형 배지 색상:**
- 매출: `bg-green-500/12 text-green-500`
- SaaS: `bg-cyan-500/12 text-cyan-500`
- 수수료: `bg-purple-500/12 text-purple-500`
- 교통비: `bg-blue-500/12 text-blue-500`
- 접대비: `bg-amber-500/12 text-amber-500`
- 복리후생: `bg-green-500/12 text-green-500`
- 임차료: `bg-slate-500/15 text-muted-foreground` (고정)
- 시차보정: `bg-orange-500/12 text-amber-500`
- 기타: `bg-slate-500/12 text-muted-foreground`

**시차 보정 행 (목업 409-436행):**
- 메인 행: `bg-purple-500/[0.03] cursor-pointer` + 클릭 시 하위 펼침
- 드릴다운:
  - `pl-10 bg-purple-500/[0.02] text-[11px]`
  - 롯데카드: `02-15 | [롯데] | 롯데카드 시차 (1월 확정 ₩14.7M - 2월 예상 ₩11.5M) | +₩3.2M`
  - 우리카드: `02-25 | [우리] | 우리카드 시차 (...) | +₩2.2M`

**SaaS 등 카테고리 드릴다운 (목업 331-341행):**
- 메인 행에 ▾ 표시 → 클릭 시 하위 개별 항목 펼침
- 하위 행: `pl-10 bg-black/[0.12] text-[11px] border-t border-white/[0.02]`

**시작잔고 행:** `font-semibold bg-green-500/[0.03] border-b border-border`
**기말잔고 행:** `font-semibold bg-amber-500/[0.03] border-t-2 border-amber-500/15`
- 기말잔고 값: 예상은 `text-amber-500`, 실제는 `text-green-500`

#### 7. 공식 표시 (목업 448-454행)
```
┌─ formula ─────────────────────────────────────────────┐
│ 2월 예상 기말 = 1월 확정 기말                            │
│   + 2월 예상 입금                                       │
│   - 2월 예상 출금                                       │
│   - 2월 예상 카드 사용액                                  │
│   + (1월 카드 사용액 - 2월 예상 카드 사용액) ← 시차 보정   │
└───────────────────────────────────────────────────────┘
```
- `bg-muted/30 border border-border px-4 py-3 rounded-lg font-mono text-xs leading-relaxed text-cyan-500 my-3`

#### 8. 하단 비교 박스 2개 (목업 456-471행)
```
┌─ 카드 시차 ──────────────┐  ┌─ 1월 예상 vs 실제 ────────┐
│ 1월 카드 (확정)  ₩17.7M  │  │ 예상 기말    ₩108.2M      │
│ 2월 카드 (진행)  ₩5.2M   │  │ 실제 기말    ₩107.2M      │
│ 2월 카드 (예상)  ₩12.3M  │  │ ──────────────────────── │
│ ──────────────────────  │  │ 차이        -₩1.0M       │
│ 시차 보정      +₩5.4M   │  │ 정확도 99.0% ■■■■        │
└──────────────────────────┘  └───────────────────────────┘
```
- `grid grid-cols-2 gap-4 mt-5`
- 각 박스: `bg-card border border-border rounded-xl p-4`
  - 제목: `text-[13px] font-semibold mb-3` — 카드 시차는 `text-purple-500`, 예상 vs 실제는 `text-amber-500`
  - 각 행: `flex justify-between py-1 text-xs`
  - 구분선: `border-t border-border pt-2 mt-2 font-semibold`
  - 정확도: `text-[11px] text-muted-foreground mt-1` + diff bar
- 반응형: `md:grid-cols-2 grid-cols-1`

- [ ] **Step 1: forecast-tab.tsx 구현**

위 UI 상세를 그대로 구현:
- API: `GET /api/cashflow/forecast` 호출
- 월 선택 (amber 테마)
- 안내 배너
- Recharts AreaChart (예상 vs 실제 + 카드 결제일 마커)
- KPI 카드 4개 (diff bar 포함)
- "실제 비교 펼치기" 토글
- 이벤트 리스트 (4/7컬럼 전환, 시차보정 드릴다운, 카테고리 드릴다운)
- 공식 표시
- 하단 비교 박스 2개
- **5 states 필수 구현** (기존 cashflow/page.tsx 패턴 참조):
  - LOADING: 스켈레톤 UI (카드/테이블 형태에 맞게)
  - EMPTY: 따뜻한 메시지 + CTA 버튼 (예: "예상 항목을 추가해보세요")
  - ERROR: 구체적 에러 메시지 + 재시도 버튼
  - SUCCESS: 정상 데이터 표시
  - PARTIAL: 경고 배너 + 가용 데이터 표시

- [ ] **Step 2: 커밋**

```bash
git add frontend/src/app/cashflow/forecast-tab.tsx
git commit -m "feat: cashflow 예상 탭 — 시차 보정 + 예상vs실제 비교"
```

---

## Task 6: 프론트엔드 — 비용 (카드 사용) 탭

**Files:**
- Create: `frontend/src/app/cashflow/expense-tab.tsx`

### UI 상세 — expense-tab.tsx

#### 1. 월 선택 + 안내 (목업 479-480행)
```
카드 사용 월: [12월] [1월●] [2월]
1월 카드 사용 → 2월 결제 예정
```
- 선택 월: `bg-purple-500 text-white font-semibold` (purple 테마)
- 안내 텍스트: `text-muted-foreground text-[13px] mb-4`
  - "N+1월"은 `<strong class="text-amber-500">` 강조

#### 2. 3 KPI 카드 (목업 482-486행)
```
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│총 지출        │ │환불           │ │순 사용        │
│₩21,626,970   │ │₩3,906,075    │ │₩17,720,895   │
│607건          │ │12건           │ │  (purple)    │
└──────────────┘ └──────────────┘ └──────────────┘
```
- `grid grid-cols-3 gap-3`
- 총지출: `text-red-500`, 환불: `text-green-500`, 순사용: `text-purple-500`
- 하단 건수: `text-[11px] text-muted-foreground mt-0.5`

#### 3. 카드/회원별 아코디언 (목업 488-519행)
```
┌────────────────────────────────────────────────────────┐
│ 롯데카드 ****1234 (하선우) — 순 ₩8,128,425 ▾            │  ← 클릭시 펼침
│   ┌ [SaaS] Anthropic Claude        -₩167,145          │  ← 개별 거래
│   ├ [SaaS] Cursor AI               -₩28,958           │
│   ├ [교통비] 카카오T × 12건          -₩201,600          │
│   ├ [취소] 이노페이 (취소)           +₩55,000           │  ← 녹색
│   └ ... 외 178건                                       │
│   소계: ₩10.2M / 환불 ₩2.1M / 순 ₩8.1M                │
├────────────────────────────────────────────────────────┤
│ 롯데카드 ****5678 (김선우) — 순 ₩6,599,598 ▾            │
│   ...                                                   │
├────────────────────────────────────────────────────────┤
│ 우리카드 ****9012 — 순 ₩2,992,872 ▾                     │
│   ...                                                   │
╞════════════════════════════════════════════════════════╡
│ 1월 합계                              ₩17,720,895      │
└────────────────────────────────────────────────────────┘
```

**전체 컨테이너:** `bg-card border border-border rounded-2xl p-5`

**카드/회원 그룹:**
- 그룹 제목: `text-[13px] font-semibold text-purple-500 mb-2 cursor-pointer`
  - 카드사 + 카드번호 마지막4자리 + 회원명 + 순금액 + ▾
  - 클릭 시 개별 거래 toggle
- 개별 거래 행: `flex justify-between py-1 pl-3 text-xs text-muted-foreground border-b border-white/[0.03]`
  - 내부계정 배지: Task 4와 동일한 색상 체계 (SaaS/교통비/수수료/취소/기타)
  - 취소(환불) 행: `text-green-500`
  - "... 외 N건" 행: `text-muted-foreground`
- 소계 행: `flex justify-between py-2 text-[13px] font-semibold border-t border-border mt-2`
  - `소계: ₩10.2M / 환불 ₩2.1M / 순 ₩8.1M` 형식

**합계 행:**
- `border-t-2 border-border pt-4 mt-4`
- `flex justify-between text-[15px] font-semibold`
- 금액: `text-purple-500 text-base`

#### 4. 하단 비교 박스 2개 (목업 521-538행)
```
┌─ 내부 계정별 (1월) ────────┐  ┌─ 월별 비교 ──────────────┐
│ [SaaS] 구독료    ₩2.4M    │  │ 12월          ₩29.9M     │
│ [수수료] 지급수수료 ₩6.8M   │  │ 1월           ₩17.7M     │
│ [교통비] 여비교통비 ₩890K   │  │ ─────────────────────── │
│ [접대비] 접대비    ₩1.2M   │  │ 변동           -40.8%     │
│ [복리후생] 복리후생비 ₩650K │  │   (green = 감소)          │
│ [기타] 기타       ₩5.8M   │  │                           │
│ ─────────────────────── │  │                           │
│ 합계            ₩17.7M   │  │                           │
└──────────────────────────┘  └───────────────────────────┘
```
- `grid grid-cols-2 gap-4 mt-5`
- 각 박스: `bg-card border border-border rounded-xl p-4`
- 내부계정별 박스:
  - 제목: `text-[13px] font-semibold mb-3`
  - 각 행: `flex justify-between py-1 text-xs` + 내부계정 배지
  - 합계: `border-t border-border pt-2 mt-2 font-semibold`
  - 데이터 소스: API의 `account_breakdown` 필드
- 월별 비교 박스:
  - 각 월: `flex justify-between py-1 text-xs font-mono`
  - 변동: `border-t pt-2 mt-2 font-semibold`
    - 감소(비용 줄어듦): `text-green-500`
    - 증가(비용 늘어남): `text-red-500`
  - 데이터 소스: API의 `prev_month_net`, `change_pct` 필드
- 반응형: `md:grid-cols-2 grid-cols-1`

- [ ] **Step 1: expense-tab.tsx 구현**

위 UI 상세를 그대로 구현:
- API: `GET /api/cashflow/card-expense` 호출
- 월 선택 (purple 테마)
- "N월 사용 → N+1월 결제" 안내
- KPI 3개 (총지출/환불/순사용)
- 카드/회원별 아코디언 (거래 펼침 + 내부계정 배지 + 소계)
- 하단 비교 박스 2개 (내부계정별 + 월별)
- **5 states 필수 구현** (기존 cashflow/page.tsx 패턴 참조):
  - LOADING: 스켈레톤 UI (카드/테이블 형태에 맞게)
  - EMPTY: 따뜻한 메시지 + CTA 버튼 (예: "카드 거래 데이터를 업로드해보세요")
  - ERROR: 구체적 에러 메시지 + 재시도 버튼
  - SUCCESS: 정상 데이터 표시
  - PARTIAL: 경고 배너 + 가용 데이터 표시

- [ ] **Step 2: 커밋**

```bash
git add frontend/src/app/cashflow/expense-tab.tsx
git commit -m "feat: cashflow 비용 탭 — 카드/회원별 드릴다운"
```

---

## Task 7: dashboard.py 정리 + 통합 테스트

**Files:**
- Modify: `backend/routers/dashboard.py` — `/cashflow`, `/cashflow/detail` 제거 (cashflow.py로 이전 완료)
- Add: `backend/tests/test_cashflow.py` — API 통합 테스트

- [ ] **Step 1: dashboard.py에서 중복 엔드포인트 제거**

`/dashboard/cashflow`와 `/dashboard/cashflow/detail` 삭제. 대시보드 메인 (`/dashboard`)은 유지.

- [ ] **Step 2: 프론트엔드 기존 참조 정리**

기존 cashflow page가 `/dashboard/cashflow` API를 호출했으므로 이미 Task 4에서 교체됨. 대시보드 메인 페이지의 cash_flow 차트도 새 API로 변경:
- `frontend/src/app/page.tsx`에서 `/dashboard` API의 cash_flow 필드 사용 (기존 유지 가능)

- [ ] **Step 3: 전체 테스트 실행**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: 커밋**

```bash
git add backend/routers/dashboard.py backend/tests/test_cashflow.py
git commit -m "refactor: cashflow 엔드포인트를 전용 라우터로 이전"
```

---

## Task 8: 실제 데이터로 E2E 검증

- [ ] **Step 1: 서버 시작**

```bash
source .venv/bin/activate && uvicorn backend.main:app --reload
cd frontend && npm run dev
```

- [ ] **Step 2: 실제 현금흐름 탭 검증**

- entity_id=2 (한아원코리아) 선택
- 1월 선택 → 기초잔고가 12/31 스냅샷(161,050,376)에서 역산되어 표시되는지
- 거래 리스트에 잔고가 누적 계산되는지
- 카드대금 행 드릴다운 동작

- [ ] **Step 3: 예상 현금흐름 탭 검증**

- 2월 선택 → 기초 = 1월 기말
- forecasts에 데이터가 없으면 빈 상태 표시
- 시차 보정이 카드 거래에서 자동 계산되는지

- [ ] **Step 4: 비용 탭 검증**

- 1월 선택 → 롯데카드/우리카드 거래 그룹핑
- 총지출, 환불, 순사용 합계 정확성
- 월별 비교 변동률

- [ ] **Step 5: 최종 커밋**

```bash
git add backend/ frontend/src/app/cashflow/
git commit -m "feat: cashflow redesign — 3탭 완성 (실제/예상/카드비용)"
```

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | CLEAR | 3 proposals, 3 accepted, 0 deferred |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | CLEAR | 12 findings, 9 overlap w/ eng review, 3 new addressed |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 | CLEAR | 12 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |

- **CODEX:** Formula double-counting, missing daily_series, broken cashflow/detail dependency — all fixed in eng review
- **CROSS-MODEL:** 9/12 Codex issues overlapped with Claude eng review. 3 unique Codex findings (cashflow/detail dep, daily_series gap, SQL param counts) all addressed
- **UNRESOLVED:** 0
- **VERDICT:** CEO + ENG CLEARED — ready to implement. Design review recommended before frontend tasks (4-6).
