# 내부계정 재매핑 + 예상 현금흐름 개선 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 거래내역 내부계정 매핑 재정비 + 예상 현금흐름에서 고정비 자동 입력, 날짜 기반 그래프, 카드별 시차보정 구현

**Architecture:** 기존 forecasts/cashflow_service 확장. DB에 expected_day, is_fixed, payment_method 컬럼 추가. 카드 시차보정을 카드별로 분리. 프론트엔드 그래프는 날짜 기반 시뮬레이션으로 개선.

**Tech Stack:** Python/FastAPI, PostgreSQL (Supabase), Next.js 14, Recharts, Alembic

**Spec:** `docs/superpowers/specs/2026-03-31-remapping-forecast-design.md`

---

## File Structure

### 생성 파일
- `backend/alembic/versions/d4e5f6g7h8i9_forecast_fields.py` — DB 마이그레이션 (forecasts 확장 + card_settings seed)
- `backend/services/remapping_service.py` — 재매핑 배치 로직

### 수정 파일
- `backend/services/cashflow_service.py` — 카드별 시차보정, 일별 시뮬레이션 데이터
- `backend/routers/forecasts.py` — ForecastCreate 모델 확장, 고정비 자동 생성 API
- `backend/routers/cashflow.py` — forecast 응답에 일별 시뮬레이션 + 경고 추가
- `backend/routers/transactions.py` — 재매핑 배치 API
- `frontend/src/app/cashflow/forecast-tab.tsx` — 그래프 날짜 기반 개선, 경고 표시

---

## Phase A: DB 마이그레이션 + 카드 설정 초기화

### Task 1: forecasts 테이블 확장 + card_settings 초기 데이터

**Files:**
- Create: `backend/alembic/versions/d4e5f6g7h8i9_forecast_fields.py`
- Modify: `backend/database/schema.sql:140-162` (참고용, 실제 변경은 alembic)

- [ ] **Step 1: Alembic 마이그레이션 파일 생성**

```bash
source .venv/bin/activate && alembic revision -m "add forecast fields and card settings seed"
```

- [ ] **Step 2: 마이그레이션 코드 작성**

```python
"""add forecast fields and card settings seed

Revision ID: d4e5f6g7h8i9
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6g7h8i9"
down_revision = "c3d4e5f6g7h8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET search_path TO financeone, public")

    # forecasts 확장
    op.add_column("forecasts", sa.Column("expected_day", sa.Integer(), nullable=True))
    op.add_column("forecasts", sa.Column("is_fixed", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("forecasts", sa.Column("payment_method", sa.Text(), server_default="bank", nullable=False))

    # card_settings 확장
    op.add_column("card_settings", sa.Column("statement_day", sa.Integer(), nullable=True))
    op.add_column("card_settings", sa.Column("billing_start_day", sa.Integer(), nullable=True))

    # card_settings 초기 데이터 (한아원코리아 entity_id=2)
    op.execute("""
        INSERT INTO card_settings (entity_id, card_name, source_type, payment_day, statement_day, billing_start_day)
        VALUES
            (2, '롯데카드', 'lotte_card', 15, 2, NULL),
            (2, '우리카드', 'woori_card', 25, 16, 11)
        ON CONFLICT (entity_id, source_type, card_number) DO UPDATE
        SET payment_day = EXCLUDED.payment_day,
            statement_day = EXCLUDED.statement_day,
            billing_start_day = EXCLUDED.billing_start_day
    """)


def downgrade() -> None:
    op.execute("SET search_path TO financeone, public")
    op.drop_column("forecasts", "payment_method")
    op.drop_column("forecasts", "is_fixed")
    op.drop_column("forecasts", "expected_day")
    op.drop_column("card_settings", "billing_start_day")
    op.drop_column("card_settings", "statement_day")
```

- [ ] **Step 3: 마이그레이션 실행**

```bash
source .venv/bin/activate && alembic upgrade head
```
Expected: 3개 컬럼 추가 (forecasts) + 2개 컬럼 추가 (card_settings) + 2개 row 삽입

- [ ] **Step 4: 검증**

```bash
source .venv/bin/activate && python3 -c "
import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute('SET search_path TO financeone, public')
cur.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s', ['financeone', 'forecasts'])
print('forecasts columns:', [r[0] for r in cur.fetchall()])
cur.execute('SELECT card_name, source_type, payment_day, statement_day, billing_start_day FROM card_settings WHERE entity_id=2')
print('card_settings:', cur.fetchall())
conn.close()
"
```
Expected: `expected_day`, `is_fixed`, `payment_method` 컬럼 확인. card_settings에 롯데/우리 2건.

- [ ] **Step 5: schema.sql 동기화 + 커밋**

schema.sql의 forecasts, card_settings 정의에 새 컬럼 반영 후:
```bash
git add backend/alembic/versions/ backend/database/schema.sql
git commit -m "feat: forecasts 확장 (expected_day, is_fixed, payment_method) + card_settings seed"
```

---

## Phase B: 카드별 시차보정

### Task 2: get_card_total_net 카드별 분리

**Files:**
- Modify: `backend/services/cashflow_service.py:362-380`
- Test: `backend/tests/test_cashflow_service.py`

- [ ] **Step 1: 테스트 작성**

```python
# backend/tests/test_cashflow_service.py 에 추가

def test_get_card_total_net_by_source_type(db_conn):
    """카드별 순 사용액 조회"""
    cur = db_conn.cursor()
    # 테스트 데이터: 롯데 100만, 우리 50만
    cur.execute("""
        INSERT INTO transactions (entity_id, date, amount, type, source_type, currency, is_duplicate)
        VALUES
            (2, '2025-12-15', 1000000, 'out', 'lotte_card', 'KRW', false),
            (2, '2025-12-20', 500000, 'out', 'woori_card', 'KRW', false)
    """)
    db_conn.commit()

    from backend.services.cashflow_service import get_card_total_net
    # 전체 (기존 동작)
    total = get_card_total_net(db_conn, 2, 2025, 12)
    assert total == 1500000

    # 롯데만
    lotte = get_card_total_net(db_conn, 2, 2025, 12, source_type='lotte_card')
    assert lotte == 1000000

    # 우리만
    woori = get_card_total_net(db_conn, 2, 2025, 12, source_type='woori_card')
    assert woori == 500000
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_cashflow_service.py::test_get_card_total_net_by_source_type -v
```
Expected: FAIL (source_type 파라미터 없음)

- [ ] **Step 3: get_card_total_net에 source_type 파라미터 추가**

`backend/services/cashflow_service.py` 의 `get_card_total_net` 함수 수정 (lines 362-380):

```python
def get_card_total_net(
    conn: PgConnection,
    entity_id: int,
    year: int,
    month: int,
    source_type: str | None = None,
) -> Decimal:
    """카드 순 사용액. source_type 지정 시 해당 카드만."""
    cur = conn.cursor()
    where = [
        "entity_id = %s",
        "date >= make_date(%s, %s, 1)",
        "date < make_date(%s, %s, 1) + INTERVAL '1 month'",
        "is_duplicate = false",
    ]
    params = [entity_id, year, month, year, month]

    if source_type:
        where.append("source_type = %s")
        params.append(source_type)
    else:
        where.append("source_type IN ('lotte_card', 'woori_card')")

    where_clause = " AND ".join(where)
    cur.execute(
        f"""
        SELECT
            COALESCE(SUM(CASE WHEN type = 'out' THEN amount ELSE 0 END), 0)
            - COALESCE(SUM(CASE WHEN type = 'in' THEN amount ELSE 0 END), 0)
        FROM transactions
        WHERE {where_clause}
        """,
        params,
    )
    result = cur.fetchone()[0]
    cur.close()
    return Decimal(str(result))
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_cashflow_service.py::test_get_card_total_net_by_source_type -v
```
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/services/cashflow_service.py backend/tests/test_cashflow_service.py
git commit -m "feat: get_card_total_net 카드별 source_type 필터 추가"
```

### Task 3: get_forecast_cashflow에서 카드별 시차보정 적용

**Files:**
- Modify: `backend/services/cashflow_service.py:383-539`

- [ ] **Step 1: get_forecast_cashflow 수정**

`cashflow_service.py`의 `get_forecast_cashflow` 함수에서 카드 시차보정 부분 수정 (lines 444-461):

```python
    # 4. 카드 시차 보정 (카드별 분리)
    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12

    lotte_prev = get_card_total_net(conn, entity_id, prev_year, prev_month, source_type='lotte_card')
    woori_prev = get_card_total_net(conn, entity_id, prev_year, prev_month, source_type='woori_card')
    prev_card_net = lotte_prev + woori_prev

    lotte_curr = get_card_total_net(conn, entity_id, year, month, source_type='lotte_card')
    woori_curr = get_card_total_net(conn, entity_id, year, month, source_type='woori_card')
    curr_card_actual = lotte_curr + woori_curr

    # 당월 카드 예상: forecast에 payment_method='card' 항목 합산, 없으면 전월 fallback
    card_forecast_items = Decimal("0")
    for item in items:
        if item.get("payment_method") == "card" and item["type"] == "out":
            card_forecast_items += Decimal(str(item["forecast_amount"]))

    lotte_estimate = card_forecast_items if card_forecast_items > 0 else lotte_prev
    woori_estimate = Decimal("0")  # 우리카드는 현재 사용량 적어 별도 추정 안함
    curr_card_estimate = lotte_estimate + woori_estimate if card_forecast_items > 0 else prev_card_net

    timing_adj = calc_card_timing_adjustment(prev_card_net, curr_card_estimate)
```

- [ ] **Step 2: forecast_expense에서 카드 항목 제외 (이중 차감 방지)**

같은 함수의 forecast 합산 부분 수정 (lines 429-442):

```python
    # 3. Forecast 합산 (payment_method='card' 항목은 expense에서 제외)
    forecast_income = Decimal("0")
    forecast_expense = Decimal("0")
    forecast_card_usage = Decimal("0")

    for item in items:
        amt = Decimal(str(item["forecast_amount"]))
        if item["type"] == "in":
            forecast_income += amt
        else:  # out
            if item.get("payment_method") == "card":
                forecast_card_usage += amt  # 추적용 (잔고 차감 안함)
            else:
                forecast_expense += amt
```

- [ ] **Step 3: 응답에 카드별 정보 추가**

반환 dict의 card_timing 부분 수정:

```python
    "card_timing": {
        "prev_month_card": float(prev_card_net),
        "lotte_prev": float(lotte_prev),
        "woori_prev": float(woori_prev),
        "curr_month_card_actual": float(curr_card_actual),
        "lotte_curr": float(lotte_curr),
        "woori_curr": float(woori_curr),
        "curr_month_card_estimate": float(curr_card_estimate),
        "adjustment": float(timing_adj),
    },
```

- [ ] **Step 4: 기존 테스트 통과 확인**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/ -v -k "cashflow or forecast"
```

- [ ] **Step 5: 커밋**

```bash
git add backend/services/cashflow_service.py
git commit -m "feat: 카드별 시차보정 분리 + payment_method 기반 이중 차감 방지"
```

---

## Phase C: forecasts API 확장

### Task 4: ForecastCreate 모델 + 고정비 자동 생성 API

**Files:**
- Modify: `backend/routers/forecasts.py:17-27` (ForecastCreate), `backend/routers/forecasts.py:181-213` (copy-recurring)

- [ ] **Step 1: ForecastCreate 모델 확장**

`backend/routers/forecasts.py` lines 17-27 수정:

```python
class ForecastCreate(BaseModel):
    entity_id: int
    year: int
    month: int
    category: str
    subcategory: Optional[str] = None
    type: str  # 'in' or 'out'
    forecast_amount: float
    is_recurring: bool = False
    internal_account_id: Optional[int] = None
    note: Optional[str] = None
    expected_day: Optional[int] = None  # 1~31
    is_fixed: bool = False
    payment_method: str = "bank"  # 'bank' or 'card'
```

- [ ] **Step 2: ForecastUpdate 모델 확장**

```python
class ForecastUpdate(BaseModel):
    forecast_amount: Optional[float] = None
    actual_amount: Optional[float] = None
    is_recurring: Optional[bool] = None
    note: Optional[str] = None
    expected_day: Optional[int] = None
    is_fixed: Optional[bool] = None
    payment_method: Optional[str] = None
```

- [ ] **Step 3: create_forecast에 새 필드 반영**

POST /api/forecasts 엔드포인트의 INSERT 쿼리에 `expected_day`, `is_fixed`, `payment_method` 추가.

- [ ] **Step 4: 고정비 자동 생성 API 추가**

```python
@router.post("/generate-fixed")
def generate_fixed_forecasts(
    entity_id: int = Query(...),
    target_year: int = Query(...),
    target_month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """전월 실적 기반 고정비 자동 생성"""
    cur = conn.cursor()
    try:
        # 전월 계산
        if target_month == 1:
            src_year, src_month = target_year - 1, 12
        else:
            src_year, src_month = target_year, target_month - 1

        # 전월 is_fixed=true 항목 조회
        cur.execute(
            """
            SELECT category, subcategory, type, forecast_amount, internal_account_id,
                   expected_day, is_fixed, payment_method, note
            FROM forecasts
            WHERE entity_id = %s AND year = %s AND month = %s AND is_fixed = true
            """,
            [entity_id, src_year, src_month],
        )
        source_items = fetch_all(cur)

        if not source_items:
            return {"generated": 0, "message": "전월 고정비 항목 없음"}

        generated = 0
        for item in source_items:
            # 전월 실적이 있으면 실적 기반, 없으면 예상 금액 그대로
            actual_key = (item.get("internal_account_id"), item["type"])
            cur.execute(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM transactions
                WHERE entity_id = %s AND internal_account_id = %s AND type = %s
                  AND date >= make_date(%s, %s, 1)
                  AND date < make_date(%s, %s, 1) + INTERVAL '1 month'
                  AND is_duplicate = false
                """,
                [entity_id, item.get("internal_account_id"), item["type"],
                 src_year, src_month, src_year, src_month],
            )
            actual = cur.fetchone()[0]
            amount = float(actual) if actual and float(actual) > 0 else item["forecast_amount"]

            cur.execute(
                """
                INSERT INTO forecasts (entity_id, year, month, category, subcategory, type,
                    forecast_amount, internal_account_id, expected_day, is_fixed, payment_method, note)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (entity_id, year, month, internal_account_id, type)
                    WHERE internal_account_id IS NOT NULL
                DO UPDATE SET forecast_amount = EXCLUDED.forecast_amount,
                    expected_day = EXCLUDED.expected_day, is_fixed = EXCLUDED.is_fixed,
                    payment_method = EXCLUDED.payment_method, updated_at = NOW()
                """,
                [entity_id, target_year, target_month, item["category"],
                 item.get("subcategory"), item["type"], amount,
                 item.get("internal_account_id"), item.get("expected_day"),
                 True, item.get("payment_method", "bank"), item.get("note")],
            )
            generated += 1

        conn.commit()
        cur.close()
        return {"generated": generated}
    except Exception:
        conn.rollback()
        raise
```

- [ ] **Step 5: list_forecasts 응답에 새 필드 포함**

GET /api/forecasts의 SELECT 쿼리에 `expected_day, is_fixed, payment_method` 추가.

- [ ] **Step 6: 테스트 + 커밋**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/ -v -k forecast
git add backend/routers/forecasts.py
git commit -m "feat: forecasts API 확장 — expected_day, is_fixed, payment_method + 고정비 자동 생성"
```

---

## Phase D: 프론트엔드 그래프 개선

### Task 5: forecast-tab.tsx 일별 시뮬레이션 + 경고

**Files:**
- Modify: `frontend/src/app/cashflow/forecast-tab.tsx:123-285` (ForecastBalanceChart)

- [ ] **Step 1: ForecastData 타입 확장**

```typescript
interface CardTiming {
  prev_month_card: number
  lotte_prev: number
  woori_prev: number
  curr_month_card_actual: number
  lotte_curr: number
  woori_curr: number
  curr_month_card_estimate: number
  adjustment: number
}

interface ForecastItem {
  // 기존 필드...
  expected_day?: number | null
  is_fixed?: boolean
  payment_method?: string  // 'bank' | 'card'
}
```

- [ ] **Step 2: 일별 시뮬레이션 로직 변경**

ForecastBalanceChart의 useMemo (lines 134-178) 교체:

```typescript
const { points, alerts } = useMemo(() => {
  if (!data) return { points: [], alerts: [] }
  const daysInMonth = new Date(year, month, 0).getDate()
  const today = new Date()
  const currentDay = today.getFullYear() === year && today.getMonth() + 1 === month
    ? today.getDate() : (month < today.getMonth() + 1 || year < today.getFullYear() ? daysInMonth : 0)

  // 날짜별 지출/수입 매핑
  const dayEvents: Record<number, number> = {}  // day -> net change (negative = expense)

  // 고정비 (expected_day 있는 bank 항목)
  const bankItems = (data.items || []).filter(i => (i.payment_method || 'bank') === 'bank' && i.type === 'out' && i.expected_day)
  const incomeItems = (data.items || []).filter(i => i.type === 'in' && i.expected_day)

  for (const item of bankItems) {
    const day = Math.min(item.expected_day!, daysInMonth)
    dayEvents[day] = (dayEvents[day] || 0) - item.forecast_amount
  }
  for (const item of incomeItems) {
    const day = Math.min(item.expected_day!, daysInMonth)
    dayEvents[day] = (dayEvents[day] || 0) + item.forecast_amount
  }

  // 카드 결제일
  const lottePayment = data.card_timing?.lotte_prev || 0
  const wooriPayment = data.card_timing?.woori_prev || 0
  dayEvents[15] = (dayEvents[15] || 0) - lottePayment
  dayEvents[25] = (dayEvents[25] || 0) - wooriPayment

  // 날짜 없는 bank 항목: 균등 분배
  const undatedBankExpense = (data.items || [])
    .filter(i => (i.payment_method || 'bank') === 'bank' && i.type === 'out' && !i.expected_day)
    .reduce((sum, i) => sum + i.forecast_amount, 0)
  const undatedIncome = (data.items || [])
    .filter(i => i.type === 'in' && !i.expected_day)
    .reduce((sum, i) => sum + i.forecast_amount, 0)
  const dailyUndated = (undatedIncome - undatedBankExpense) / daysInMonth

  // 일별 잔고 계산
  let balance = data.opening_balance
  const pts: { day: number; estimated: number; actual: number | null; label?: string }[] = []
  const alertList: { day: number; message: string; deficit: number }[] = []

  for (let d = 1; d <= daysInMonth; d++) {
    const dayChange = (dayEvents[d] || 0) + dailyUndated
    balance += dayChange

    // 경고: 특정 일 지출이 잔고 초과
    if (dayEvents[d] && dayEvents[d] < 0 && balance < 0) {
      alertList.push({
        day: d,
        message: `${d}일 지출 후 잔고 부족`,
        deficit: Math.abs(balance),
      })
    }

    pts.push({
      day: d,
      estimated: Math.round(balance),
      actual: d <= currentDay ? null : null,  // actual은 별도 계산
    })
  }

  // actual line (은행 거래 기반)
  if (currentDay > 0) {
    const dailyActual = (data.actual_closing - data.opening_balance) / currentDay
    let actualBal = data.opening_balance
    for (let d = 1; d <= currentDay; d++) {
      actualBal += dailyActual
      pts[d - 1].actual = Math.round(actualBal)
    }
  }

  return { points: pts, alerts: alertList }
}, [data, year, month])
```

- [ ] **Step 3: 카드 결제일 ReferenceLine 라벨 수정 (글자 짤림)**

```typescript
{/* 카드 결제일 마커 */}
<ReferenceLine x={15} stroke="#f87171" strokeDasharray="4 4" strokeWidth={1}>
  <Label value="롯데" position="top" fill="#f87171" fontSize={10} />
</ReferenceLine>
<ReferenceLine x={25} stroke="#60a5fa" strokeDasharray="4 4" strokeWidth={1}>
  <Label value="우리" position="top" fill="#60a5fa" fontSize={10} />
</ReferenceLine>
```

- [ ] **Step 4: 경고 배너 추가**

ForecastTab 컴포넌트에 alerts 표시 추가:

```typescript
{alerts.length > 0 && (
  <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 mb-4">
    <p className="text-red-400 text-sm font-medium">⚠ 잔고 부족 예상</p>
    {alerts.map((a, i) => (
      <p key={i} className="text-red-300/80 text-xs mt-1">
        {month}월 {a.day}일: 지출 후 {Math.round(a.deficit).toLocaleString()}원 부족
      </p>
    ))}
  </div>
)}
```

- [ ] **Step 5: ForecastModal에 새 필드 추가**

expected_day, is_fixed, payment_method 입력 필드를 ForecastModal에 추가.

- [ ] **Step 6: 테스트 + 커밋**

```bash
cd frontend && npm run build
git add frontend/src/app/cashflow/forecast-tab.tsx
git commit -m "feat: 예상 현금흐름 그래프 — 날짜 기반 시뮬레이션 + 카드별 결제일 + 잔고 경고"
```

---

## Phase E: 내부계정 재매핑

### Task 6: 재매핑 배치 서비스

**Files:**
- Create: `backend/services/remapping_service.py`
- Modify: `backend/routers/transactions.py`

- [ ] **Step 1: remapping_service.py 작성**

```python
"""내부계정 재매핑 배치 서비스"""

from psycopg2.extensions import connection as PgConnection
from backend.services.mapping_service import auto_map_transaction


def remap_transactions(
    conn: PgConnection,
    entity_id: int,
    dry_run: bool = False,
) -> dict:
    """전체 재매핑 (수동 매핑 유지, mapping_rules → Slack 순서)"""
    cur = conn.cursor()

    # 재매핑 대상: mapping_source != 'manual' 이거나 internal_account_id IS NULL
    cur.execute(
        """
        SELECT id, counterparty, source_type, internal_account_id, mapping_source
        FROM transactions
        WHERE entity_id = %s
          AND (mapping_source IS NULL OR mapping_source != 'manual')
          AND counterparty IS NOT NULL AND counterparty != ''
        ORDER BY date DESC
        """,
        [entity_id],
    )
    candidates = cur.fetchall()

    results = {"total": len(candidates), "mapped": 0, "unchanged": 0, "unmapped": 0, "details": []}

    for tx_id, counterparty, source_type, current_ia, mapping_source in candidates:
        mapping = auto_map_transaction(cur, entity_id=entity_id, counterparty=counterparty)

        if mapping:
            new_ia = mapping["internal_account_id"]
            new_sa = mapping["standard_account_id"]
            confidence = mapping["confidence"]

            if new_ia == current_ia:
                results["unchanged"] += 1
                continue

            if not dry_run:
                cur.execute(
                    """
                    UPDATE transactions
                    SET internal_account_id = %s, standard_account_id = %s,
                        mapping_confidence = %s, mapping_source = 'rule',
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    [new_ia, new_sa, confidence, tx_id],
                )
            results["mapped"] += 1
            results["details"].append({
                "id": tx_id, "counterparty": counterparty,
                "old_ia": current_ia, "new_ia": new_ia, "confidence": float(confidence),
            })
        else:
            results["unmapped"] += 1

    if not dry_run:
        conn.commit()

    cur.close()
    return results
```

- [ ] **Step 2: 재매핑 API 엔드포인트 추가**

`backend/routers/transactions.py`에 추가:

```python
from backend.services.remapping_service import remap_transactions

@router.post("/remap")
def remap_all(
    entity_id: int = Query(...),
    dry_run: bool = Query(False),
    conn: PgConnection = Depends(get_db),
):
    """내부계정 전체 재매핑 (수동 매핑 유지)"""
    return remap_transactions(conn, entity_id=entity_id, dry_run=dry_run)
```

- [ ] **Step 3: dry-run 테스트**

```bash
curl -s -X POST "http://localhost:8000/api/transactions/remap?entity_id=2&dry_run=true" | python3 -m json.tool
```
Expected: mapped/unchanged/unmapped 카운트 + 변경 없음

- [ ] **Step 4: 커밋**

```bash
git add backend/services/remapping_service.py backend/routers/transactions.py
git commit -m "feat: 내부계정 전체 재매핑 배치 — dry-run 지원"
```

---

## Phase F: 고정비 초기 seed + 통합 테스트

### Task 7: 고정비 초기 데이터 등록

- [ ] **Step 1: 초기 seed 스크립트**

```bash
source .venv/bin/activate && python3 -c "
import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute('SET search_path TO financeone, public')

# 한아원코리아 2026년 1월 고정비
seeds = [
    (2, 2026, 1, '급여', None, 'out', 29263090, 351, 24, True, 'bank'),
    (2, 2026, 1, '임차료', '스파크플러스', 'out', 891000, 355, 2, True, 'bank'),
    (2, 2026, 1, '임차료', '기업정인자산', 'out', 8816940, 355, 24, True, 'bank'),
    (2, 2026, 1, '4대보험', None, 'out', 4282720, 380, 10, True, 'bank'),
    (2, 2026, 1, '원천세', None, 'out', 1004270, 380, 3, True, 'bank'),
    (2, 2026, 1, '사무실 청소', None, 'out', 386800, 451, 24, True, 'bank'),
]

for s in seeds:
    cur.execute('''
        INSERT INTO forecasts (entity_id, year, month, category, subcategory, type,
            forecast_amount, internal_account_id, expected_day, is_fixed, payment_method)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (entity_id, year, month, internal_account_id, type)
            WHERE internal_account_id IS NOT NULL
        DO UPDATE SET forecast_amount = EXCLUDED.forecast_amount,
            expected_day = EXCLUDED.expected_day, is_fixed = EXCLUDED.is_fixed,
            payment_method = EXCLUDED.payment_method
    ''', s)
    print(f'  Inserted: {s[3]} {s[4] or \"\"} {s[6]:,.0f}원 day={s[8]}')

conn.commit()
print('Done')
conn.close()
"
```

- [ ] **Step 2: 검증**

```bash
curl -s "http://localhost:8000/api/forecasts?entity_id=2&year=2026&month=1" | python3 -m json.tool | head -50
```
Expected: 6개 고정비 항목 + expected_day/is_fixed/payment_method 필드

- [ ] **Step 3: 예상 현금흐름 API 검증**

```bash
curl -s "http://localhost:8000/api/cashflow/forecast?entity_id=2&year=2026&month=1" | python3 -m json.tool
```
Expected: card_timing에 lotte_prev/woori_prev 분리, items에 새 필드 포함

- [ ] **Step 4: CHANGELOG 업데이트 + 최종 커밋**

```bash
git add CHANGELOG.md
git commit -m "feat: 내부계정 재매핑 + 예상 현금흐름 개선 — v0.8.0"
```

---

## Task 요약

| Task | 내용 | 예상 시간 |
|------|------|----------|
| 1 | DB 마이그레이션 + card_settings seed | 10분 |
| 2 | get_card_total_net 카드별 분리 | 10분 |
| 3 | get_forecast_cashflow 카드별 시차보정 + 이중 차감 방지 | 15분 |
| 4 | forecasts API 확장 + 고정비 자동 생성 | 15분 |
| 5 | 프론트엔드 그래프 날짜 기반 + 경고 | 20분 |
| 6 | 재매핑 배치 서비스 | 10분 |
| 7 | 고정비 seed + 통합 테스트 | 10분 |
| **총** | | **~90분** |
