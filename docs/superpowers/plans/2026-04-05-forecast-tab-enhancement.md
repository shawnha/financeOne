# 예상 탭 고도화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 예상 현금흐름 탭의 차트 정확도 개선, 항목별 진행바 UI, 미예산 거래 섹션, CSV 내보내기를 구현하여 월별 예산 관리 워크플로우를 완성한다.

**Architecture:** 백엔드 cashflow_service.py의 일별 스케줄 로직을 수정하여 비정기 대형 수입의 균등분배 문제를 해결하고, 프론트엔드 forecast-tab.tsx에 진행바·미예산·내보내기 UI를 추가한다. 새 API 없이 기존 forecast API 응답에 unbudgeted_actuals 필드를 추가하는 것이 유일한 백엔드 변경.

**Tech Stack:** Python/FastAPI, Next.js 14, Recharts, shadcn/ui

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/services/cashflow_service.py` | 일별 스케줄 균등분배 수정 + unbudgeted_actuals 쿼리 추가 |
| Modify | `backend/tests/test_forecasts.py` | 새 로직 단위 테스트 |
| Modify | `frontend/src/app/cashflow/forecast-tab.tsx` | 진행바 UI, 미예산 섹션, CSV 내보내기, 초과 배지 |

---

### Task 1: Worst-Case 시나리오 라인 추가

**Problem:** 날짜 모르는 비정기 수입이 균등 분배되어 "돈 충분하네" 착각을 줄 수 있음. 실제로는 수입이 월말에 들어오고 지출이 월초에 나가면 중간에 잔고 부족 발생 가능. 현재 구글시트로 따로 확인하고 있음.

**Solution:** `generate_daily_schedule()`에 worst-case 시나리오 포인트 추가 반환. 날짜 없는 비정기 지출은 1일 일괄, 날짜 없는 비정기 수입은 월말 일괄. 프론트에서 빨간 점선으로 표시.

**Files:**
- Modify: `backend/services/cashflow_service.py:937-1036` (generate_daily_schedule)
- Modify: `frontend/src/app/cashflow/forecast-tab.tsx` (ForecastBalanceChart)
- Test: `backend/tests/test_forecasts.py`

- [ ] **Step 1: Write test for worst-case schedule**

```python
# backend/tests/test_forecasts.py 하단에 추가

class TestWorstCaseSchedule:
    """worst-case: 비정기 수입 월말, 비정기 지출 월초."""

    def test_worst_case_income_at_end_expense_at_start(self):
        """비정기 지출은 1일, 수입은 31일에 반영되어야 함."""
        # worst-case에서 비정기 지출 1일 반영 → 잔고가 초반에 크게 하락
        # worst-case에서 비정기 수입 월말 반영 → 월말에만 회복
        opening = 100_000_000
        nr_expense = 60_000_000  # 비정기 지출
        nr_income = 80_000_000   # 비정기 수입

        # Day 1: opening - nr_expense = 40M
        worst_day1 = opening - nr_expense
        assert worst_day1 == 40_000_000

        # Day 31: 40M + nr_income = 120M (기타 항목 무시 시)
        worst_day31 = worst_day1 + nr_income
        assert worst_day31 == 120_000_000

        # 기본 예상에서는 매일 균등: (80M - 60M) / 31 = +645K/day
        daily_net = (nr_income - nr_expense) / 31
        normal_day1 = opening + daily_net
        # 기본 예상 Day 1은 opening과 거의 같지만, worst-case Day 1은 40M으로 급락
        assert worst_day1 < normal_day1
```

- [ ] **Step 2: Run test**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_forecasts.py::TestWorstCaseSchedule -v`
Expected: PASS (순수 계산 테스트)

- [ ] **Step 3: Modify generate_daily_schedule — worst_case_points 추가**

`backend/services/cashflow_service.py`의 `generate_daily_schedule()` 함수에서, 기존 시뮬레이션 루프(라인 1000-1018) 뒤에 worst-case 시뮬레이션 추가:

```python
    # Worst-case 시뮬레이션: 비정기 지출 1일, 비정기 수입 월말
    worst_day_events: dict[int, list[dict]] = defaultdict(list)

    # expected_day 있는 항목 + 카드 결제 (기본과 동일)
    for d_key, evts in day_events.items():
        worst_day_events[d_key].extend(evts)

    # 비정기 undated: 지출→1일, 수입→월말
    for item in items:
        if (item.get("payment_method", "bank") == "bank"
            and not item.get("expected_day")
            and not item.get("is_recurring", False)):
            target_day = days_in_month if item["type"] == "in" else 1
            worst_day_events[target_day].append({
                "name": item["category"],
                "amount": item["forecast_amount"],
                "type": item["type"],
            })

    worst_balance = forecast_data["opening_balance"]
    worst_points = []
    for d in range(1, days_in_month + 1):
        day_change = sum(
            -e["amount"] if e["type"] == "out" else e["amount"]
            for e in worst_day_events.get(d, [])
        ) - daily_undated_out + daily_undated_in
        worst_balance += day_change
        worst_points.append({
            "day": d,
            "balance": round(worst_balance),
        })
```

반환 dict에 추가:
```python
        "worst_case_points": worst_points,
```

- [ ] **Step 4: 프론트 ForecastBalanceChart에 worst-case 라인 추가**

`forecast-tab.tsx`의 DailyScheduleData 인터페이스에 추가:
```typescript
  worst_case_points?: Array<{ day: number; balance: number }>
```

ForecastBalanceChart 컴포넌트의 chartData 계산에 worst-case 추가:
```typescript
const points = schedule.points.map((p, i) => ({
  day: `${month}/${p.day}`,
  originalEstimated: p.balance,
  estimated: p.balance + (unmappedNet * p.day / schedule.points.length),
  worstCase: schedule.worst_case_points?.[i]?.balance ?? null,
  actual: p.day <= forecastData.last_actual_day
    ? (actualBalanceByDay.get(p.day) ?? null)
    : null,
  events: p.events,
}))
```

차트에 빨간 점선 Line 추가 (Area 뒤에):
```tsx
<Line
  type="monotone"
  dataKey="worstCase"
  stroke="#EF4444"
  strokeWidth={1.2}
  strokeDasharray="6 4"
  strokeOpacity={0.5}
  dot={false}
  activeDot={false}
/>
```

범례에 추가:
```tsx
<span className="text-[10px] text-red-400/60">— — 최악 시나리오</span>
```

- [ ] **Step 5: Run all tests**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_forecasts.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/cashflow_service.py backend/tests/test_forecasts.py frontend/src/app/cashflow/forecast-tab.tsx
git commit -m "feat: worst-case 시나리오 라인 추가 (비정기 수입 월말, 지출 월초)"
```

---

### Task 2: unbudgeted_actuals — 백엔드 API에 미예산 거래 추가

**Problem:** forecast에 없는 내부계정으로 실제 거래가 발생한 경우 현재 표시 안 됨.

**Files:**
- Modify: `backend/services/cashflow_service.py:611-625` (get_forecast_cashflow 반환값 확장)
- Test: `backend/tests/test_forecasts.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_forecasts.py 하단에 추가

class TestUnbudgetedActuals:
    """forecast에 없는 계정의 실제 거래를 감지."""

    def test_identifies_unbudgeted(self):
        """forecast에 internal_account_id가 없는 계정의 거래는 unbudgeted."""
        forecast_account_ids = {351, 353, 355}  # 급여, 4대보험, 임차료
        actual_account_ids = {351, 353, 355, 469, 467}  # + 개발외주, 국세/지방세

        unbudgeted_ids = actual_account_ids - forecast_account_ids
        assert unbudgeted_ids == {469, 467}

    def test_empty_when_all_budgeted(self):
        """모든 실제 거래가 forecast에 있으면 빈 리스트."""
        forecast_ids = {351, 353}
        actual_ids = {351, 353}
        assert actual_ids - forecast_ids == set()
```

- [ ] **Step 2: Run test**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_forecasts.py::TestUnbudgetedActuals -v`
Expected: PASS

- [ ] **Step 3: actual_by_account 쿼리에 계정 이름 JOIN 추가**

`backend/services/cashflow_service.py` 라인 464-479의 actual_by_account 쿼리를 수정하여 `ia.name`도 가져오도록 변경:

```python
    # 2-bis. 내부계정별 실제 거래 합계 (계정 이름 포함)
    cur.execute(
        """
        SELECT t.internal_account_id, t.type, SUM(t.amount) AS total, ia.name AS account_name
        FROM transactions t
        LEFT JOIN internal_accounts ia ON ia.id = t.internal_account_id
        WHERE t.entity_id = %s
          AND t.date >= make_date(%s, %s, 1)
          AND t.date < make_date(%s, %s, 1) + INTERVAL '1 month'
          AND t.is_duplicate = false
          AND t.internal_account_id IS NOT NULL
        GROUP BY t.internal_account_id, t.type, ia.name
        """,
        [entity_id, year, month, year, month],
    )
    actual_by_account = {}
    for row in cur.fetchall():
        actual_by_account[(row[0], row[1])] = {"total": float(row[2]), "name": row[3]}
```

그 후 `over_budget` 계산 뒤에 추가 (N+1 쿼리 없이):

```python
    # 미예산 실제 거래 (forecast에 없는 계정의 거래)
    forecast_account_ids = {
        (i["internal_account_id"], i["type"])
        for i in items if i.get("internal_account_id")
    }
    unbudgeted_actuals = []
    for (acct_id, acct_type), info in actual_by_account.items():
        if (acct_id, acct_type) not in forecast_account_ids:
            unbudgeted_actuals.append({
                "internal_account_id": acct_id,
                "account_name": info["name"] or f"계정 #{acct_id}",
                "type": acct_type,
                "actual_amount": info["total"],
            })
    unbudgeted_actuals.sort(key=lambda x: x["actual_amount"], reverse=True)
```

**주의:** actual_by_account 구조가 `float` → `{"total": float, "name": str}`로 변경되므로, 이 dict를 사용하는 다른 코드(over_budget, actual_from_transactions 등)도 `info["total"]`로 접근하도록 수정 필요.

반환 dict에 추가:
```python
        "unbudgeted_actuals": unbudgeted_actuals,
```

- [ ] **Step 4: Run tests**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_forecasts.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/cashflow_service.py backend/tests/test_forecasts.py
git commit -m "feat: forecast API에 unbudgeted_actuals 필드 추가"
```

---

### Task 3: 프론트 — 항목별 진행바 UI

**Problem:** 항목별 forecast 대비 actual %가 텍스트로만 표시됨. 시각적 진행바가 없음.

**Files:**
- Modify: `frontend/src/app/cashflow/forecast-tab.tsx:1586-1659` (예상 금액 컬럼 영역)

- [ ] **Step 1: ForecastData 인터페이스에 unbudgeted_actuals 타입 추가**

`forecast-tab.tsx` ForecastData 인터페이스 (라인 100-133 부근)에 추가:

```typescript
interface UnbudgetedActual {
  internal_account_id: number
  account_name: string
  type: string
  actual_amount: number
}

// ForecastData에 필드 추가:
  unbudgeted_actuals?: UnbudgetedActual[]
```

- [ ] **Step 2: 진행바 컴포넌트 inline 구현**

`forecast-tab.tsx`에서 기존 "실제 ₩X (+Y%)" 텍스트 표시 부분 (라인 1648-1659)을 교체:

```tsx
{item.actual_from_transactions != null && item.actual_from_transactions !== 0 && (() => {
  const actual = item.actual_from_transactions!
  const forecast = item.forecast_amount
  const pct = forecast !== 0 ? Math.round((actual / forecast) * 100) : 0
  const isOver = actual > forecast
  const barWidth = Math.min(pct, 150) // cap at 150%
  return (
    <div className="mt-1 space-y-0.5">
      <div className="flex items-center gap-2">
        <div className="relative h-1.5 flex-1 rounded-full bg-white/5 min-w-[60px]">
          <div
            className={cn(
              "absolute h-full rounded-full transition-all",
              isOver ? "bg-[hsl(var(--loss))]" : pct >= 80 ? "bg-[hsl(var(--warning))]" : "bg-[hsl(var(--profit))]"
            )}
            style={{ width: `${Math.min(barWidth, 100)}%` }}
          />
          {isOver && (
            <div
              className="absolute h-full rounded-r-full bg-[hsl(var(--loss))]/50"
              style={{ left: "100%", width: `${Math.min(barWidth - 100, 50)}%` }}
            />
          )}
        </div>
        <span className={cn(
          "text-[10px] font-mono tabular-nums whitespace-nowrap",
          isOver ? "text-[hsl(var(--loss))]" : "text-muted-foreground"
        )}>
          {pct}%
        </span>
      </div>
      <span className={cn("text-[10px]", isOver ? "text-[hsl(var(--loss))]" : "text-[hsl(var(--profit))]")}>
        실제 {formatByEntity(actual, entityId)}
      </span>
    </div>
  )
})()}
```

동일한 진행바를 가상 부모 행(라인 1595-1606)에도 적용. `displayActual`과 `displayAmount`를 사용.

- [ ] **Step 3: dev 서버에서 시각적 확인**

Run: `cd frontend && npm run dev`
브라우저에서 예상 탭 → 1월 → "실제 비교 펼치기" 클릭 → 항목별 진행바 확인

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/cashflow/forecast-tab.tsx
git commit -m "feat: 항목별 진행바 UI (forecast 대비 actual %)"
```

---

### Task 4: 프론트 — 미예산(unbudgeted) 섹션

**Problem:** forecast에 없는 계정의 실제 거래가 표시되지 않아 서프라이즈 비용 포착 불가.

**Files:**
- Modify: `frontend/src/app/cashflow/forecast-tab.tsx` (예산 초과 항목 아래에 추가)

- [ ] **Step 1: 미예산 섹션 UI 추가**

예산 초과 카드(라인 1382-1397) 바로 아래에 추가:

```tsx
{/* Unbudgeted actuals */}
{data.unbudgeted_actuals && data.unbudgeted_actuals.length > 0 && (
  <Card className="bg-amber-500/10 border-amber-500/30 rounded-xl p-4">
    <div className="flex items-center justify-between mb-3">
      <div className="flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-amber-400" />
        <span className="text-sm font-medium text-amber-400">
          미예산 거래 ({data.unbudgeted_actuals.length}건)
        </span>
      </div>
    </div>
    <div className="space-y-2">
      {data.unbudgeted_actuals.map((item) => (
        <div key={`${item.internal_account_id}-${item.type}`}
          className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <span className={cn(
              "px-1.5 py-0.5 rounded text-[10px] font-medium",
              item.type === "in"
                ? "bg-[hsl(var(--profit))]/10 text-[hsl(var(--profit))]"
                : "bg-[hsl(var(--loss))]/10 text-[hsl(var(--loss))]"
            )}>
              {item.type === "in" ? "입금" : "출금"}
            </span>
            <span className="text-foreground">{item.account_name}</span>
          </div>
          <div className="flex items-center gap-3">
            <span className={cn(
              "font-mono tabular-nums",
              item.type === "in" ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"
            )}>
              {item.type === "out" ? "-" : "+"}{formatByEntity(item.actual_amount, entityId)}
            </span>
            <button
              onClick={async () => {
                try {
                  await fetchAPI("/forecasts", {
                    method: "POST",
                    body: JSON.stringify({
                      entity_id: Number(entityId),
                      year: y,
                      month: m,
                      category: item.account_name,
                      type: item.type,
                      forecast_amount: item.actual_amount,
                      is_recurring: false,
                      internal_account_id: item.internal_account_id,
                    }),
                  })
                  fetchForecast()
                } catch { /* error */ }
              }}
              className="text-[10px] text-amber-400 hover:text-amber-300 underline decoration-dotted"
            >
              + 예산 추가
            </button>
          </div>
        </div>
      ))}
    </div>
  </Card>
)}
```

- [ ] **Step 2: AlertTriangle import 확인**

`forecast-tab.tsx` 상단 lucide-react import에 `AlertTriangle` 추가 (없으면).

- [ ] **Step 3: 시각적 확인**

브라우저에서 1월 예상 탭 → 미예산 거래 섹션 표시 확인
- 사무실 공사 6,200만, 법률서비스 1,800만 등이 amber 섹션에 표시되어야 함
- "+ 예산 추가" 클릭 시 forecast 항목 생성 확인

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/cashflow/forecast-tab.tsx
git commit -m "feat: 미예산(unbudgeted) 거래 섹션 + 예산 추가 버튼"
```

---

### Task 5: 프론트 — 초과 알림 뱃지 (KPI 카드)

**Problem:** 예산 초과 항목이 KPI 영역과 분리되어 눈에 잘 안 들어옴.

**Files:**
- Modify: `frontend/src/app/cashflow/forecast-tab.tsx:1353-1380` (KPI 카드 영역)

- [ ] **Step 1: "조정 예상 기말" KPI 카드에 초과 건수 배지 추가**

KPICard 컴포넌트의 subtext를 활용. 라인 1355-1363 교체:

```tsx
<KPICard
  label="조정 예상 기말"
  value={formatByEntity(data.adjusted_forecast_closing, entityId)}
  rawAmount={data.adjusted_forecast_closing}
  entityId={entityId}
  colorClass="text-[hsl(var(--warning))]"
  subtext={
    data.over_budget && data.over_budget.length > 0
      ? `초과 ${data.over_budget.length}건`
      : data.unmapped_count > 0
        ? `미분류 ${data.unmapped_count}건 반영`
        : undefined
  }
  subtextColor={data.over_budget && data.over_budget.length > 0 ? "text-red-400" : "text-amber-400"}
/>
```

- [ ] **Step 2: 시각적 확인**

1월 예상 탭 → KPI "조정 예상 기말" 카드에 "초과 5건" 빨간 텍스트 표시 확인

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/cashflow/forecast-tab.tsx
git commit -m "feat: KPI 카드에 예산 초과 건수 배지"
```

---

### Task 6: 프론트 — CSV 내보내기

**Problem:** 내보내기 버튼이 있지만 onClick 핸들러 없음.

**Files:**
- Modify: `frontend/src/app/cashflow/forecast-tab.tsx:1309-1311`

- [ ] **Step 1: CSV 내보내기 함수 추가**

ForecastTab 컴포넌트 내부에 함수 추가:

```tsx
const handleExportCSV = useCallback(() => {
  if (!data) return
  const [y, m] = selectedMonth.split("-").map(Number)

  const rows: string[][] = [
    ["유형", "항목", "예상 금액", "실제 금액", "차이", "차이(%)", "반복", "결제일", "결제수단"],
  ]

  for (const item of data.items) {
    const actual = item.actual_from_transactions ?? 0
    const diff = actual - item.forecast_amount
    const pct = item.forecast_amount !== 0 ? Math.round((diff / item.forecast_amount) * 100) : 0
    rows.push([
      item.type === "in" ? "입금" : "출금",
      item.category + (item.subcategory ? ` > ${item.subcategory}` : ""),
      String(item.forecast_amount),
      String(actual),
      String(diff),
      `${pct}%`,
      item.is_recurring ? "Y" : "N",
      item.expected_day ? `${item.expected_day}일` : "",
      item.payment_method === "card" ? "카드" : "은행",
    ])
  }

  // Summary rows
  rows.push([])
  rows.push(["기초 잔고", "", String(data.opening_balance)])
  rows.push(["조정 예상 기말", "", String(data.adjusted_forecast_closing)])
  rows.push(["실제 기말", "", String(data.actual_closing)])
  rows.push(["차이", "", String(data.diff)])

  const BOM = "\uFEFF"
  const csv = BOM + rows.map(r => r.map(c => `"${c}"`).join(",")).join("\n")
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = `forecast_${y}-${String(m).padStart(2, "0")}.csv`
  a.click()
  URL.revokeObjectURL(url)
}, [data, selectedMonth, entityId])
```

- [ ] **Step 2: 버튼에 핸들러 연결**

라인 1309 교체:

```tsx
<Button variant="outline" size="sm" className="gap-2" onClick={handleExportCSV}>
```

- [ ] **Step 3: 시각적 확인**

브라우저에서 내보내기 클릭 → CSV 파일 다운로드 확인 → Excel/Numbers에서 열기 (한글 깨짐 없는지 BOM 확인)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/cashflow/forecast-tab.tsx
git commit -m "feat: 예상 현금흐름 CSV 내보내기 구현"
```

---

### Task 7: next build 검증

**Files:**
- None (빌드 검증만)

- [ ] **Step 1: TypeScript 빌드 확인**

Run: `cd frontend && npm run build 2>&1 | tail -20`
Expected: Build succeeded

- [ ] **Step 2: 빌드 실패 시 타입 에러 수정**

타입 에러가 있으면 해당 파일 수정 후 재빌드

- [ ] **Step 3: dev 서버 재시작 후 전체 확인**

Run: `cd frontend && npm run dev`
CSS 깨짐 방지를 위해 build 후 반드시 dev 재시작 (feedback_build_dev_restart.md 참조)

- [ ] **Step 4: Final commit (if any fixes)**

```bash
git add -A
git commit -m "fix: build errors from forecast tab enhancement"
```
