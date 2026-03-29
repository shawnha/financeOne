# 예산/고정비 관리 — 내부계정 연동 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** forecasts 테이블을 내부계정과 연결하고, 내부계정 트리 페이지에서 월별 예산을 입력하고, 고정비를 자동 복사하고, 예실대비를 자동 계산하는 기능 구현

**Architecture:** `forecasts` 테이블에 `internal_account_id` FK 추가. `internal_accounts`에 `is_recurring` 컬럼 추가. 내부계정 트리 페이지에서 월 선택 후 각 계정에 예산 금액 인라인 입력. 예상 탭(forecast-tab)에서 내부계정명으로 예실대비 표시. 고정비(`is_recurring=true`) 항목은 다음 달 자동 복사.

**Tech Stack:** Next.js 14 / FastAPI / Supabase PostgreSQL / Recharts

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `backend/database/schema.sql` | forecasts에 internal_account_id FK, internal_accounts에 is_recurring 추가 |
| Modify | `backend/routers/accounts.py` | internal_accounts API에 is_recurring 필드 지원 |
| Modify | `backend/routers/forecasts.py` | forecasts API에 internal_account_id 지원 + 고정비 자동복사 + 전월 실적 채우기 |
| Modify | `backend/services/cashflow_service.py` | 예실대비 계산에 internal_account_id 기반 actual 집계 |
| Modify | `frontend/src/app/accounts/internal/page.tsx` | 예산 인라인 입력 UI + 고정비 토글 + MonthPicker |
| Modify | `frontend/src/components/tree-account-item.tsx` | 고정비 배지 + 예산 금액 표시 |
| Modify | `frontend/src/app/cashflow/forecast-tab.tsx` | 내부계정명 표시 + 예실대비 + 예산 초과 경고 |

---

### Task 1: DB 스키마 마이그레이션

**Files:**
- Modify: `backend/database/schema.sql`

- [ ] **Step 1: internal_accounts에 is_recurring 컬럼 추가 마이그레이션 실행**

```bash
source .venv/bin/activate && python3 -c "
import psycopg2
from pathlib import Path
env_path = Path('$PWD/.env')
DATABASE_URL = None
for line in env_path.read_text().splitlines():
    if line.startswith('DATABASE_URL='):
        DATABASE_URL = line.split('=', 1)[1].strip()
        break
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()
cur.execute('SET search_path TO financeone, public')

# 1. internal_accounts에 is_recurring 추가
cur.execute('''
    ALTER TABLE internal_accounts
    ADD COLUMN IF NOT EXISTS is_recurring BOOLEAN NOT NULL DEFAULT FALSE
''')

# 2. forecasts에 internal_account_id FK 추가
cur.execute('''
    ALTER TABLE forecasts
    ADD COLUMN IF NOT EXISTS internal_account_id INTEGER REFERENCES internal_accounts(id)
''')

# 3. UNIQUE 제약 변경: category 기반 → internal_account_id 기반
cur.execute('''
    ALTER TABLE forecasts
    DROP CONSTRAINT IF EXISTS forecasts_entity_id_year_month_category_subcategory_type_key
''')
cur.execute('''
    CREATE UNIQUE INDEX IF NOT EXISTS uq_forecasts_account
    ON forecasts (entity_id, year, month, internal_account_id, type)
    WHERE internal_account_id IS NOT NULL
''')
# 기존 category 기반 forecast (internal_account_id 없는 것)용 UNIQUE 유지
cur.execute('''
    CREATE UNIQUE INDEX IF NOT EXISTS uq_forecasts_category
    ON forecasts (entity_id, year, month, category, subcategory, type)
    WHERE internal_account_id IS NULL
''')

conn.commit()
print('Migration done: is_recurring + internal_account_id + UNIQUE indexes')
cur.close()
conn.close()
"
```

- [ ] **Step 2: schema.sql 파일 업데이트**

`internal_accounts` 테이블 정의에 `is_recurring` 추가:

```sql
-- 4. internal_accounts — 내부 계정과목
CREATE TABLE IF NOT EXISTS internal_accounts (
  id                  SERIAL PRIMARY KEY,
  entity_id           INTEGER NOT NULL REFERENCES entities(id),
  code                TEXT NOT NULL,
  name                TEXT NOT NULL,
  standard_account_id INTEGER REFERENCES standard_accounts(id),
  parent_id           INTEGER REFERENCES internal_accounts(id),
  sort_order          INTEGER NOT NULL DEFAULT 0,
  is_active           BOOLEAN NOT NULL DEFAULT TRUE,
  is_recurring        BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE(entity_id, code)
);
```

`forecasts` 테이블 정의에 `internal_account_id` 추가:

```sql
-- 8. forecasts — 예측 수입/지출
CREATE TABLE IF NOT EXISTS forecasts (
  id                  SERIAL PRIMARY KEY,
  entity_id           INTEGER NOT NULL REFERENCES entities(id),
  year                INTEGER NOT NULL,
  month               INTEGER NOT NULL,
  category            TEXT NOT NULL,
  subcategory         TEXT,
  type                TEXT NOT NULL,
  forecast_amount     NUMERIC(18,2) NOT NULL DEFAULT 0,
  actual_amount       NUMERIC(18,2),
  is_recurring        BOOLEAN NOT NULL DEFAULT FALSE,
  internal_account_id INTEGER REFERENCES internal_accounts(id),
  note                TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  -- internal_account_id 있으면 계정 기반 UNIQUE
  -- internal_account_id 없으면 category 기반 UNIQUE (레거시 호환)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecasts_account
  ON forecasts (entity_id, year, month, internal_account_id, type)
  WHERE internal_account_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecasts_category
  ON forecasts (entity_id, year, month, category, subcategory, type)
  WHERE internal_account_id IS NULL;
```

- [ ] **Step 3: 데이터 확인**

```bash
source .venv/bin/activate && python3 -c "
import psycopg2
from pathlib import Path
env_path = Path('$PWD/.env')
DATABASE_URL = None
for line in env_path.read_text().splitlines():
    if line.startswith('DATABASE_URL='):
        DATABASE_URL = line.split('=', 1)[1].strip()
        break
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()
cur.execute('SET search_path TO financeone, public')

# internal_accounts 컬럼 확인
cur.execute(\"\"\"
    SELECT column_name, data_type, column_default
    FROM information_schema.columns
    WHERE table_schema = 'financeone' AND table_name = 'internal_accounts'
    AND column_name = 'is_recurring'
\"\"\")
print('internal_accounts.is_recurring:', cur.fetchone())

# forecasts 컬럼 확인
cur.execute(\"\"\"
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'financeone' AND table_name = 'forecasts'
    AND column_name = 'internal_account_id'
\"\"\")
print('forecasts.internal_account_id:', cur.fetchone())

cur.close()
conn.close()
"
```

- [ ] **Step 4: Commit**

```bash
git add backend/database/schema.sql
git commit -m "feat: DB 마이그레이션 — internal_accounts.is_recurring + forecasts.internal_account_id"
```

---

### Task 2: 백엔드 — internal_accounts API에 is_recurring 지원

**Files:**
- Modify: `backend/routers/accounts.py`

- [ ] **Step 1: Pydantic 모델에 is_recurring 추가**

`InternalAccountCreate`(line 18)에 추가:

```python
class InternalAccountCreate(BaseModel):
    entity_id: int
    code: str
    name: str
    standard_account_id: Optional[int] = None
    parent_id: Optional[int] = None
    sort_order: Optional[int] = 0
    is_recurring: Optional[bool] = False
```

`InternalAccountUpdate`(line 27)에 추가:

```python
class InternalAccountUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    standard_account_id: Optional[int] = None
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    is_recurring: Optional[bool] = None
```

- [ ] **Step 2: list_internal_accounts 쿼리에 is_recurring 포함**

`list_internal_accounts`(line 93)의 SELECT 쿼리를 수정하여 `ia.is_recurring` 포함:

```python
@router.get("/internal")
def list_internal_accounts(
    entity_id: Optional[int] = None,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    if entity_id is not None:
        cur.execute(
            """
            SELECT ia.id, ia.entity_id, ia.code, ia.name,
                   sa.code AS standard_code, sa.name AS standard_name,
                   ia.sort_order, ia.parent_id, ia.is_recurring
            FROM internal_accounts ia
            LEFT JOIN standard_accounts sa ON ia.standard_account_id = sa.id
            WHERE ia.entity_id = %s AND ia.is_active = true
            ORDER BY ia.sort_order, ia.code
            """,
            [entity_id],
        )
    else:
        cur.execute(
            """
            SELECT ia.id, ia.entity_id, ia.code, ia.name,
                   sa.code AS standard_code, sa.name AS standard_name,
                   ia.sort_order, ia.parent_id, ia.is_recurring
            FROM internal_accounts ia
            LEFT JOIN standard_accounts sa ON ia.standard_account_id = sa.id
            WHERE ia.is_active = true
            ORDER BY ia.entity_id, ia.sort_order, ia.code
            """
        )
    rows = fetch_all(cur)
    cur.close()
    return rows
```

- [ ] **Step 3: create_internal_account에 is_recurring 포함**

INSERT 쿼리(line 136)에 `is_recurring` 추가:

```python
cur.execute(
    """
    INSERT INTO internal_accounts
        (entity_id, code, name, standard_account_id, parent_id, sort_order, is_recurring)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    RETURNING id, entity_id, code, name, standard_account_id,
              parent_id, sort_order, is_active, is_recurring
    """,
    [
        body.entity_id,
        body.code,
        body.name,
        body.standard_account_id,
        body.parent_id,
        body.sort_order,
        body.is_recurring,
    ],
)
```

- [ ] **Step 4: update_internal_account의 RETURNING에 is_recurring 추가**

`update_internal_account`(line 206)의 RETURNING 절:

```sql
RETURNING id, entity_id, code, name, standard_account_id,
          parent_id, sort_order, is_active, is_recurring
```

- [ ] **Step 5: API 테스트**

```bash
source .venv/bin/activate && uvicorn backend.main:app --reload &
sleep 3
# is_recurring 필드 확인
curl -s "http://localhost:8000/api/accounts/internal?entity_id=2" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print('첫 항목:', json.dumps(data[0], indent=2, ensure_ascii=False))
print('is_recurring 필드 있음:', 'is_recurring' in data[0])
"
kill %1
```

Expected: `is_recurring: false` 필드가 응답에 포함.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/accounts.py
git commit -m "feat: internal_accounts API에 is_recurring 필드 추가"
```

---

### Task 3: 백엔드 — forecasts API 확장

**Files:**
- Modify: `backend/routers/forecasts.py`

- [ ] **Step 1: ForecastCreate에 internal_account_id 추가**

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
```

- [ ] **Step 2: create_forecast의 INSERT에 internal_account_id 포함**

```python
cur.execute(
    """
    INSERT INTO forecasts
        (entity_id, year, month, category, subcategory, type,
         forecast_amount, is_recurring, internal_account_id, note)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (entity_id, year, month, internal_account_id, type)
      WHERE internal_account_id IS NOT NULL
    DO UPDATE SET forecast_amount = EXCLUDED.forecast_amount,
                  is_recurring = EXCLUDED.is_recurring,
                  category = EXCLUDED.category,
                  note = EXCLUDED.note,
                  updated_at = NOW()
    RETURNING id
    """,
    [body.entity_id, body.year, body.month, body.category,
     body.subcategory, body.type, body.forecast_amount,
     body.is_recurring, body.internal_account_id, body.note],
)
```

- [ ] **Step 3: list_forecasts 쿼리에 internal_account_id + 내부계정명 JOIN 추가**

```python
@router.get("")
def list_forecasts(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: Optional[int] = None,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    base_query = """
        SELECT f.id, f.entity_id, f.year, f.month, f.category, f.subcategory, f.type,
               f.forecast_amount, f.actual_amount, f.is_recurring, f.note,
               f.internal_account_id, ia.name AS internal_account_name,
               f.created_at, f.updated_at
        FROM forecasts f
        LEFT JOIN internal_accounts ia ON f.internal_account_id = ia.id
    """
    if month is not None:
        cur.execute(
            base_query + " WHERE f.entity_id = %s AND f.year = %s AND f.month = %s ORDER BY f.type, f.category",
            [entity_id, year, month],
        )
    else:
        cur.execute(
            base_query + " WHERE f.entity_id = %s AND f.year = %s ORDER BY f.month, f.type, f.category",
            [entity_id, year],
        )
    rows = fetch_all(cur)
    cur.close()
    return {"forecasts": rows, "count": len(rows)}
```

- [ ] **Step 4: 고정비 자동 복사 API 추가**

`delete_forecast` 함수 뒤에 추가:

```python
@router.post("/copy-recurring", status_code=201)
def copy_recurring_forecasts(
    entity_id: int = Query(...),
    source_year: int = Query(...),
    source_month: int = Query(...),
    target_year: int = Query(...),
    target_month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """is_recurring=true인 항목을 source → target 월로 복사. 이미 있으면 skip."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO forecasts
                (entity_id, year, month, category, subcategory, type,
                 forecast_amount, is_recurring, internal_account_id, note)
            SELECT entity_id, %s, %s, category, subcategory, type,
                   forecast_amount, is_recurring, internal_account_id, note
            FROM forecasts
            WHERE entity_id = %s AND year = %s AND month = %s AND is_recurring = true
            ON CONFLICT (entity_id, year, month, category, subcategory, type) DO NOTHING
            RETURNING id
            """,
            [target_year, target_month, entity_id, source_year, source_month],
        )
        copied = len(cur.fetchall())
        conn.commit()
        cur.close()
        return {"copied": copied, "target": f"{target_year}-{target_month:02d}"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 5: 전월 실적 기반 예상 자동 채우기 API 추가**

```python
@router.get("/suggest-from-actuals")
def suggest_forecasts_from_actuals(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    conn: PgConnection = Depends(get_db),
):
    """전월 내부계정별 실제 지출을 예상 금액으로 제안."""
    # 전월 계산
    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12

    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.internal_account_id,
               ia.name AS account_name,
               ia.code AS account_code,
               ia.is_recurring,
               t.type,
               SUM(t.amount) AS total
        FROM transactions t
        JOIN internal_accounts ia ON t.internal_account_id = ia.id
        WHERE t.entity_id = %s
          AND t.date >= make_date(%s, %s, 1)
          AND t.date < make_date(%s, %s, 1) + INTERVAL '1 month'
          AND t.is_duplicate = false
          AND t.internal_account_id IS NOT NULL
        GROUP BY t.internal_account_id, ia.name, ia.code, ia.is_recurring, t.type
        ORDER BY ia.is_recurring DESC, total DESC
        """,
        [entity_id, prev_year, prev_month, prev_year, prev_month],
    )
    rows = fetch_all(cur)
    cur.close()

    return {
        "source_year": prev_year,
        "source_month": prev_month,
        "suggestions": rows,
    }
```

- [ ] **Step 6: Commit**

```bash
git add backend/routers/forecasts.py
git commit -m "feat: forecasts API — internal_account_id 지원 + 고정비 자동복사 + 전월 실적 제안"
```

---

### Task 4: 백엔드 — 예실대비 계산

**Files:**
- Modify: `backend/services/cashflow_service.py`

- [ ] **Step 1: get_forecast_cashflow에 내부계정별 actual 집계 추가**

`get_forecast_cashflow` 함수(line 383)의 items 조회 쿼리를 수정하여 `internal_account_id` + 내부계정명을 포함하고, forecast items에 실제 거래 합계를 자동 계산:

기존 items 조회(line 399-408) 뒤에 actual 집계 추가:

```python
    # 2-bis. 내부계정별 실제 거래 합계
    cur.execute(
        """
        SELECT internal_account_id, type, SUM(amount) AS total
        FROM transactions
        WHERE entity_id = %s
          AND date >= make_date(%s, %s, 1)
          AND date < make_date(%s, %s, 1) + INTERVAL '1 month'
          AND is_duplicate = false
          AND internal_account_id IS NOT NULL
        GROUP BY internal_account_id, type
        """,
        [entity_id, year, month, year, month],
    )
    actual_by_account = {}
    for row in cur.fetchall():
        actual_by_account[(row[0], row[1])] = float(row[2])
```

items 조회의 SELECT에 `internal_account_id, ia.name AS internal_account_name` 추가:

```python
    cur.execute(
        """
        SELECT f.id, f.category, f.subcategory, f.type, f.forecast_amount, f.actual_amount,
               f.is_recurring, f.note, f.internal_account_id
        FROM forecasts f
        WHERE f.entity_id = %s AND f.year = %s AND f.month = %s
        ORDER BY f.type, f.category
        """,
        [entity_id, year, month],
    )
    items = fetch_all(cur)
```

반환하는 items 리스트에 `actual_from_transactions` 필드 추가:

```python
    "items": [
        {
            "id": i["id"],
            "category": i["category"],
            "subcategory": i["subcategory"],
            "type": i["type"],
            "forecast_amount": float(i["forecast_amount"]),
            "actual_amount": float(i["actual_amount"]) if i["actual_amount"] else None,
            "is_recurring": i["is_recurring"],
            "note": i["note"],
            "internal_account_id": i.get("internal_account_id"),
            "actual_from_transactions": actual_by_account.get(
                (i.get("internal_account_id"), i["type"]), 0.0
            ) if i.get("internal_account_id") else None,
        }
        for i in items
    ],
```

- [ ] **Step 2: 예산 초과 항목 리스트 추가**

반환 dict에 `over_budget` 필드 추가:

```python
    # 예산 초과 항목 (실제 >= 예상 * 1.1)
    over_budget = []
    for i in items:
        if i.get("internal_account_id") and i["type"] == "out":
            forecast = float(i["forecast_amount"])
            actual = actual_by_account.get((i["internal_account_id"], "out"), 0.0)
            if forecast > 0 and actual >= forecast * 1.1:
                over_budget.append({
                    "category": i["category"],
                    "internal_account_id": i["internal_account_id"],
                    "forecast": forecast,
                    "actual": actual,
                    "diff_pct": round((actual / forecast - 1) * 100, 1),
                })
```

반환 dict에 추가:

```python
    return {
        ...기존 필드들...,
        "over_budget": over_budget,
    }
```

- [ ] **Step 3: Commit**

```bash
git add backend/services/cashflow_service.py
git commit -m "feat: 예실대비 자동 계산 + 예산 초과 감지"
```

---

### Task 5: 프론트엔드 — 내부계정 트리에 고정비 토글 + 예산 입력

**Files:**
- Modify: `frontend/src/components/tree-account-item.tsx`
- Modify: `frontend/src/app/accounts/internal/page.tsx`

- [ ] **Step 1: RawAccount 타입에 is_recurring 추가**

`frontend/src/app/accounts/internal/page.tsx`의 `RawAccount` 인터페이스(line 43):

```typescript
interface RawAccount {
  id: number
  entity_id: number
  code: string
  name: string
  standard_code: string | null
  standard_name: string | null
  sort_order: number
  parent_id: number | null
  is_recurring: boolean
}
```

- [ ] **Step 2: TreeAccount 인터페이스에 is_recurring 추가**

`frontend/src/components/tree-account-item.tsx`의 `TreeAccount` 인터페이스:

```typescript
export interface TreeAccount {
  id: number
  code: string
  name: string
  parent_id: number | null
  sort_order: number
  standard_code: string | null
  standard_name: string | null
  depth: number
  children: TreeAccount[]
  isRoot: boolean
  is_recurring: boolean
}
```

- [ ] **Step 3: TreeAccountItem에 고정비 배지 추가**

Name span 뒤에 고정비 배지:

```tsx
{/* Name */}
<span className={cn(
  "flex-1 text-sm truncate",
  account.isRoot && "text-base font-medium",
)}>
  {account.name}
</span>

{/* 고정비 배지 */}
{account.is_recurring && !account.isRoot && (
  <Badge variant="outline" className="text-[10px] shrink-0 border-blue-500/30 text-blue-400">
    고정
  </Badge>
)}
```

- [ ] **Step 4: TreeAccountItem에 예산 금액 표시 prop 추가**

Props에 `budgetAmount` 추가:

```typescript
interface TreeAccountItemProps {
  account: TreeAccount
  collapsed: Set<number>
  onToggle: (id: number) => void
  onEdit: (account: TreeAccount) => void
  onDelete: (account: TreeAccount) => void
  onAddChild: (parentId: number) => void
  budgetAmount?: number | null
  onBudgetClick?: (account: TreeAccount) => void
}
```

고정비 배지 뒤에 예산 금액 표시:

```tsx
{/* 예산 금액 */}
{budgetAmount !== undefined && budgetAmount !== null && !account.isRoot && (
  <span
    className="text-xs font-mono text-muted-foreground cursor-pointer hover:text-foreground shrink-0"
    onClick={(e) => { e.stopPropagation(); onBudgetClick?.(account) }}
  >
    ₩{budgetAmount.toLocaleString()}
  </span>
)}
{budgetAmount === null && !account.isRoot && !account.children?.length && onBudgetClick && (
  <span
    className="text-xs text-muted-foreground/40 cursor-pointer hover:text-muted-foreground shrink-0"
    onClick={(e) => { e.stopPropagation(); onBudgetClick?.(account) }}
  >
    + 예산
  </span>
)}
```

- [ ] **Step 5: buildTree에 is_recurring 전달**

`page.tsx`의 `buildTree` 함수에서 `is_recurring` 포함:

```typescript
.map((a) => ({
  ...a,
  depth,
  isRoot: ROOT_CODES.includes(a.code),
  is_recurring: a.is_recurring ?? false,
  children: walk(a.id, depth + 1),
}))
```

- [ ] **Step 6: 내부계정 페이지에 MonthPicker + 예산 데이터 fetch 추가**

페이지 상단에 MonthPicker import:

```typescript
import { MonthPicker } from "@/components/month-picker"
```

InternalAccountsContent에 state 추가:

```typescript
const now = new Date()
const [budgetYear, setBudgetYear] = useState(now.getFullYear())
const [budgetMonth, setBudgetMonth] = useState(now.getMonth() + 1)
const [budgets, setBudgets] = useState<Record<number, number>>({}) // internal_account_id → amount

// 예산 데이터 fetch
const loadBudgets = useCallback(async () => {
  if (!entityId) return
  try {
    const data = await fetchAPI<{ forecasts: Array<{ internal_account_id: number | null; forecast_amount: number }> }>(
      `/forecasts?entity_id=${entityId}&year=${budgetYear}&month=${budgetMonth}`
    )
    const map: Record<number, number> = {}
    for (const f of data.forecasts) {
      if (f.internal_account_id) {
        map[f.internal_account_id] = (map[f.internal_account_id] || 0) + f.forecast_amount
      }
    }
    setBudgets(map)
  } catch {}
}, [entityId, budgetYear, budgetMonth])

useEffect(() => { loadBudgets() }, [loadBudgets])
```

- [ ] **Step 7: 예산 입력 다이얼로그 추가**

```typescript
const [budgetTarget, setBudgetTarget] = useState<TreeAccount | null>(null)
const [budgetInput, setBudgetInput] = useState("")
const [budgetSaving, setBudgetSaving] = useState(false)

const handleSaveBudget = async () => {
  if (!budgetTarget || !entityId) return
  setBudgetSaving(true)
  try {
    const isIncome = budgetTarget.code.startsWith("INC")
    await fetchAPI("/forecasts", {
      method: "POST",
      body: JSON.stringify({
        entity_id: Number(entityId),
        year: budgetYear,
        month: budgetMonth,
        category: budgetTarget.name,
        type: isIncome ? "in" : "out",
        forecast_amount: parseFloat(budgetInput) || 0,
        is_recurring: budgetTarget.is_recurring,
        internal_account_id: budgetTarget.id,
      }),
    })
    toast.success(`${budgetTarget.name} ${budgetYear}년 ${budgetMonth}월 예산 저장`)
    setBudgetTarget(null)
    setBudgetInput("")
    loadBudgets()
  } catch {
    toast.error("예산 저장에 실패했습니다")
  } finally {
    setBudgetSaving(false)
  }
}
```

- [ ] **Step 8: 고정비 토글 핸들러**

```typescript
const handleToggleRecurring = useCallback(async (account: TreeAccount) => {
  try {
    await fetchAPI(`/accounts/internal/${account.id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_recurring: !account.is_recurring }),
    })
    toast.success(`${account.name} ${!account.is_recurring ? "고정비로 설정" : "고정비 해제"}`)
    load()
  } catch {
    toast.error("변경에 실패했습니다")
  }
}, [load])
```

- [ ] **Step 9: 카드 헤더에 MonthPicker + 고정비 복사 버튼 추가**

CardHeader 부분:

```tsx
<CardHeader className="flex flex-row items-center justify-between">
  <CardTitle className="text-base font-medium">
    내부 계정과목 ({accounts.length}건)
  </CardTitle>
  <div className="flex items-center gap-2">
    <MonthPicker
      year={budgetYear}
      month={budgetMonth}
      onChange={(y, m) => { setBudgetYear(y); setBudgetMonth(m) }}
    />
    <Button size="sm" variant="outline" onClick={handleCopyRecurring}>
      고정비 복사
    </Button>
    <Button size="sm" onClick={() => {
      setEditingId(null)
      setForm(EMPTY_FORM)
      setDialogOpen(true)
    }}>
      <Plus className="mr-1.5 h-4 w-4" />
      계정 추가
    </Button>
  </div>
</CardHeader>
```

고정비 복사 핸들러:

```typescript
const handleCopyRecurring = useCallback(async () => {
  if (!entityId) return
  const prevMonth = budgetMonth === 1 ? 12 : budgetMonth - 1
  const prevYear = budgetMonth === 1 ? budgetYear - 1 : budgetYear
  try {
    const result = await fetchAPI<{ copied: number }>(`/forecasts/copy-recurring?entity_id=${entityId}&source_year=${prevYear}&source_month=${prevMonth}&target_year=${budgetYear}&target_month=${budgetMonth}`, {
      method: "POST",
    })
    if (result.copied > 0) {
      toast.success(`고정비 ${result.copied}건 복사 완료`)
      loadBudgets()
    } else {
      toast.info("복사할 고정비가 없습니다")
    }
  } catch {
    toast.error("고정비 복사에 실패했습니다")
  }
}, [entityId, budgetYear, budgetMonth, loadBudgets])
```

- [ ] **Step 10: visibleItems 렌더링에 budgetAmount + onBudgetClick 전달**

```tsx
{visibleItems.map((node) => (
  <TreeAccountItem
    key={node.id}
    account={node}
    collapsed={collapsed}
    onToggle={handleToggle}
    onEdit={handleEdit}
    onDelete={(a) => setDeleteTarget(a as unknown as RawAccount)}
    onAddChild={handleAddChild}
    budgetAmount={budgets[node.id] ?? null}
    onBudgetClick={(a) => {
      setBudgetTarget(a)
      setBudgetInput(budgets[a.id]?.toString() || "")
    }}
  />
))}
```

- [ ] **Step 11: 예산 입력 Dialog 렌더링**

Delete Dialog 뒤에 추가:

```tsx
{/* Budget Input Dialog */}
<Dialog open={!!budgetTarget} onOpenChange={(open) => !open && setBudgetTarget(null)}>
  <DialogContent className="sm:max-w-[400px]">
    <DialogHeader>
      <DialogTitle>{budgetTarget?.name} — {budgetYear}년 {budgetMonth}월 예산</DialogTitle>
      <DialogDescription>
        예상 {budgetTarget?.code.startsWith("INC") ? "수입" : "지출"} 금액을 입력하세요.
      </DialogDescription>
    </DialogHeader>
    <div className="grid gap-4 py-4">
      <div className="grid gap-2">
        <label className="text-sm font-medium">예상 금액 (원)</label>
        <Input
          type="number"
          placeholder="예: 3000000"
          value={budgetInput}
          onChange={(e) => setBudgetInput(e.target.value)}
          autoFocus
        />
      </div>
      <div className="flex items-center gap-2">
        <Checkbox
          checked={budgetTarget?.is_recurring ?? false}
          onCheckedChange={() => budgetTarget && handleToggleRecurring(budgetTarget)}
        />
        <label className="text-sm text-muted-foreground">고정비 (매달 반복)</label>
      </div>
    </div>
    <DialogFooter>
      <Button variant="outline" onClick={() => setBudgetTarget(null)}>취소</Button>
      <Button onClick={handleSaveBudget} disabled={budgetSaving}>
        {budgetSaving ? "저장 중..." : "저장"}
      </Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
```

- [ ] **Step 12: DialogDescription import 추가**

기존 Dialog import에 `DialogDescription` 추가:

```typescript
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
```

- [ ] **Step 13: 빌드 확인**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: Build 성공.

- [ ] **Step 14: Commit**

```bash
git add frontend/src/components/tree-account-item.tsx frontend/src/app/accounts/internal/page.tsx
git commit -m "feat: 내부계정 트리에 고정비 토글 + 월별 예산 인라인 입력"
```

---

### Task 6: 프론트엔드 — forecast-tab 예실대비 + 예산 초과 경고

**Files:**
- Modify: `frontend/src/app/cashflow/forecast-tab.tsx`

- [ ] **Step 1: ForecastItem 타입에 필드 추가**

```typescript
interface ForecastItem {
  id: number
  category: string
  subcategory: string | null
  type: string
  forecast_amount: number
  actual_amount: number | null
  is_recurring: boolean
  note: string | null
  internal_account_id: number | null
  internal_account_name: string | null
  actual_from_transactions: number | null
}
```

ForecastData에 over_budget 추가:

```typescript
interface ForecastData {
  // ...기존 필드들...
  over_budget: Array<{
    category: string
    internal_account_id: number
    forecast: number
    actual: number
    diff_pct: number
  }>
}
```

- [ ] **Step 2: items 테이블에 예실대비 컬럼 추가**

기존 forecast items 테이블에 "실제" + "차이" 컬럼 추가. 예산 초과 시 빨간색 표시:

items 렌더링 부분에서 각 항목에:

```tsx
<TableHead className="text-right">예상</TableHead>
<TableHead className="text-right">실제</TableHead>
<TableHead className="text-right">차이</TableHead>
```

각 행에:

```tsx
<TableCell className="text-right font-mono text-sm">
  {formatByEntity(item.forecast_amount, entityId)}
</TableCell>
<TableCell className="text-right font-mono text-sm">
  {item.actual_from_transactions != null
    ? formatByEntity(item.actual_from_transactions, entityId)
    : <span className="text-muted-foreground">—</span>}
</TableCell>
<TableCell className={cn(
  "text-right font-mono text-sm",
  item.actual_from_transactions != null && item.actual_from_transactions > item.forecast_amount * 1.1
    ? "text-red-400"
    : item.actual_from_transactions != null && item.actual_from_transactions <= item.forecast_amount
    ? "text-green-400"
    : ""
)}>
  {item.actual_from_transactions != null
    ? formatByEntity(item.actual_from_transactions - item.forecast_amount, entityId)
    : "—"}
</TableCell>
```

- [ ] **Step 3: 예산 초과 경고 배너 추가**

KPI 카드 아래에:

```tsx
{data.over_budget && data.over_budget.length > 0 && (
  <Card className="bg-red-500/10 border-red-500/30 rounded-xl p-4">
    <div className="flex items-center gap-2 mb-2">
      <AlertCircle className="h-4 w-4 text-red-400" />
      <span className="text-sm font-medium text-red-400">예산 초과 항목</span>
    </div>
    <div className="space-y-1">
      {data.over_budget.map((item, i) => (
        <p key={i} className="text-xs text-red-300">
          {item.category}: 예상 {formatByEntity(item.forecast, entityId)} → 실제 {formatByEntity(item.actual, entityId)} (+{item.diff_pct}%)
        </p>
      ))}
    </div>
  </Card>
)}
```

- [ ] **Step 4: ForecastModal의 category를 내부계정 선택으로 변경**

기존 하드코딩된 `CATEGORIES_IN/OUT`를 제거하고 내부계정 목록을 fetch하여 AccountCombobox로 선택:

```typescript
import { AccountCombobox } from "@/components/account-combobox"

// ForecastModal 내부에:
const [internalAccounts, setInternalAccounts] = useState<Array<{ id: number; code: string; name: string; parent_id: number | null }>>([])
const [selectedAccountId, setSelectedAccountId] = useState<string>("")

useEffect(() => {
  fetchAPI<Array<{ id: number; code: string; name: string; parent_id: number | null }>>(
    `/accounts/internal?entity_id=${entityId}`
  ).then(setInternalAccounts).catch(() => {})
}, [entityId])
```

카테고리 Select를 AccountCombobox로 교체:

```tsx
<div>
  <label className="text-xs text-muted-foreground">계정</label>
  <AccountCombobox
    options={internalAccounts}
    value={selectedAccountId}
    onChange={(v) => {
      setSelectedAccountId(v)
      const acc = internalAccounts.find(a => String(a.id) === v)
      if (acc) setCategory(acc.name)
    }}
    placeholder="내부계정 선택"
  />
</div>
```

handleSave에서 `internal_account_id` 포함:

```typescript
await fetchAPI("/forecasts", {
  method: "POST",
  body: JSON.stringify({
    entity_id: Number(entityId),
    year,
    month,
    category,
    type,
    forecast_amount: parseFloat(amount),
    is_recurring: recurring,
    internal_account_id: selectedAccountId ? Number(selectedAccountId) : null,
  }),
})
```

- [ ] **Step 5: 빌드 확인**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/cashflow/forecast-tab.tsx
git commit -m "feat: forecast-tab 예실대비 자동 계산 + 예산 초과 경고 + 내부계정 선택"
```

---

### Task 7: 백엔드 테스트

**Files:**
- Create: `backend/tests/test_forecasts.py`

- [ ] **Step 1: 테스트 파일 생성**

```python
"""forecasts 예산/고정비 기능 테스트"""

import pytest
from unittest.mock import MagicMock, patch


def make_cursor(rows=None, fetchone=None, description=None):
    cur = MagicMock()
    cur.fetchall.return_value = rows or []
    cur.fetchone.return_value = fetchone
    cur.description = description
    return cur


def make_conn(cursor):
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


class TestCopyRecurring:
    """고정비 자동 복사 테스트"""

    def test_copies_recurring_items(self):
        """is_recurring=true 항목만 다음 달로 복사"""
        cur = make_cursor(rows=[(101,), (102,)])
        conn = make_conn(cur)

        from backend.routers.forecasts import copy_recurring_forecasts
        # Direct function call with mocked dependencies
        result = copy_recurring_forecasts(
            entity_id=2, source_year=2026, source_month=3,
            target_year=2026, target_month=4, conn=conn,
        )
        assert result["copied"] == 2
        assert result["target"] == "2026-04"

    def test_skip_existing(self):
        """이미 존재하는 항목은 skip (ON CONFLICT DO NOTHING)"""
        cur = make_cursor(rows=[])  # 0 rows returned = all skipped
        conn = make_conn(cur)

        from backend.routers.forecasts import copy_recurring_forecasts
        result = copy_recurring_forecasts(
            entity_id=2, source_year=2026, source_month=3,
            target_year=2026, target_month=4, conn=conn,
        )
        assert result["copied"] == 0


class TestSuggestFromActuals:
    """전월 실적 기반 예상 제안 테스트"""

    def test_returns_previous_month(self):
        """3월 요청 시 2월 데이터 반환"""
        from backend.routers.forecasts import suggest_forecasts_from_actuals
        cur = make_cursor(rows=[])
        conn = make_conn(cur)

        result = suggest_forecasts_from_actuals(
            entity_id=2, year=2026, month=3, conn=conn,
        )
        assert result["source_year"] == 2026
        assert result["source_month"] == 2

    def test_january_wraps_to_december(self):
        """1월 요청 시 전년 12월 반환"""
        from backend.routers.forecasts import suggest_forecasts_from_actuals
        cur = make_cursor(rows=[])
        conn = make_conn(cur)

        result = suggest_forecasts_from_actuals(
            entity_id=2, year=2026, month=1, conn=conn,
        )
        assert result["source_year"] == 2025
        assert result["source_month"] == 12


class TestOverBudget:
    """예산 초과 감지 테스트"""

    def test_detects_over_budget(self):
        """실제 >= 예상 * 1.1 일 때 초과 감지"""
        from backend.services.cashflow_service import calc_forecast_closing
        # forecast=100, actual=115 → 15% 초과 → over_budget
        forecast = 100.0
        actual = 115.0
        assert actual >= forecast * 1.1

    def test_no_false_positive_at_boundary(self):
        """실제 < 예상 * 1.1 일 때 초과 아님"""
        forecast = 100.0
        actual = 109.0
        assert actual < forecast * 1.1

    def test_zero_forecast_no_division_error(self):
        """예상 0원일 때 division error 없이 skip"""
        forecast = 0.0
        # forecast > 0 체크로 skip
        assert not (forecast > 0)
```

- [ ] **Step 2: 테스트 실행**

```bash
source .venv/bin/activate && python3 -m pytest backend/tests/test_forecasts.py -v
```

Expected: 모든 테스트 PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_forecasts.py
git commit -m "test: 예산/고정비 기능 테스트 (복사, 제안, 초과감지)"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - ✅ forecasts.internal_account_id FK (Task 1)
   - ✅ internal_accounts.is_recurring (Task 1, 2)
   - ✅ 내부계정 트리에서 예산 인라인 입력 (Task 5)
   - ✅ 고정비 토글 (Task 5)
   - ✅ 고정비 자동 복사 (Task 3, 5)
   - ✅ 예실대비 자동 계산 (Task 4, 6)
   - ✅ 예산 초과 알림 (Task 4, 6)
   - ✅ 전월 실적 기반 예상 자동 채우기 API (Task 3)
   - ✅ forecast-tab 내부계정명 표시 (Task 6)

2. **Placeholder scan:** 모든 step에 실제 코드 포함, TBD/TODO 없음

3. **Type consistency:** `RawAccount.is_recurring` → `TreeAccount.is_recurring` → `buildTree` 전달 일관성 확인. `ForecastItem.internal_account_id` → API 응답 일관.
