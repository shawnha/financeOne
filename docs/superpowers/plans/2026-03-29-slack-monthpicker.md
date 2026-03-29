# Slack 매칭 MonthPicker 통합 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slack 매칭 화면에 MonthPicker를 도입하여 월별 탐색하고, 서버에서 월 필터링하며, 카드 접힌 상태에 메시지 요약 1줄을 표시한다.

**Architecture:** 백엔드 `GET /api/slack/messages`에 `month` 쿼리 파라미터를 추가하여 서버 측 월 필터링. 프론트엔드에서 기존 `groupByMonth` + `MonthSection` 구조를 제거하고 MonthPicker 컴포넌트로 교체. 카드 접힌 상태에 Slack 마크다운을 strip한 텍스트 80자를 추가.

**Tech Stack:** FastAPI, Next.js 14 App Router, TypeScript, shadcn/ui

---

## File Structure

- **Modify:** `backend/routers/slack.py` — `month` 쿼리 파라미터 추가 (WHERE절에 ts 기준 월 필터)
- **Modify:** `frontend/src/app/slack-match/page.tsx` — MonthPicker 도입, MonthSection 제거, 카드 요약 1줄 추가
- **No changes:** `frontend/src/components/month-picker.tsx` (기존 그대로 재사용)

---

### Task 1: 백엔드 — month 필터 파라미터 추가

**Files:**
- Modify: `backend/routers/slack.py:34-124`

- [ ] **Step 1: `list_slack_messages` 함수에 `month` 파라미터 추가**

`backend/routers/slack.py`의 `list_slack_messages` 함수 시그니처와 WHERE 절을 수정한다.

함수 시그니처에 추가:
```python
month: Optional[str] = Query(None, description="YYYY-MM format, e.g. 2026-03"),
```

WHERE 절 구성 부분 (`if is_cancelled is not None:` 블록 뒤)에 추가:
```python
if month:
    # month = "2026-03" → ts 범위 필터 (unix timestamp 기반)
    try:
        year_val, month_val = month.split("-")
        month_start = datetime(int(year_val), int(month_val), 1)
        if int(month_val) == 12:
            month_end = datetime(int(year_val) + 1, 1, 1)
        else:
            month_end = datetime(int(year_val), int(month_val) + 1, 1)
        where.append("CAST(sm.ts AS DOUBLE PRECISION) >= %s")
        params.append(month_start.timestamp())
        where.append("CAST(sm.ts AS DOUBLE PRECISION) < %s")
        params.append(month_end.timestamp())
    except (ValueError, IndexError):
        raise HTTPException(400, "month must be YYYY-MM format")
```

- [ ] **Step 2: monthly_summary 쿼리는 월 필터 적용하지 않도록 분리**

monthly_summary는 MonthPicker의 available months 데이터이므로 **month 필터 없이** entity_id만 적용해야 한다. 현재는 `where_clause`를 공유하고 있어서, monthly_summary용 별도 WHERE를 만든다.

현재 `cur2.execute(...)` 부분의 WHERE를 수정:

```python
# 월별 요약 통계 — month 필터 없이 entity 전체
summary_where = ["1=1"]
summary_params: list = []
if entity_id is not None:
    summary_where.append("sm.entity_id = %s")
    summary_params.append(entity_id)

summary_where_clause = " AND ".join(summary_where)

cur2 = conn.cursor()
cur2.execute(
    f"""
    SELECT
        EXTRACT(YEAR FROM to_timestamp(CAST(sm.ts AS DOUBLE PRECISION)))::int AS yr,
        EXTRACT(MONTH FROM to_timestamp(CAST(sm.ts AS DOUBLE PRECISION)))::int AS mo,
        COUNT(*) AS total,
        COUNT(CASE WHEN sm.slack_status = 'done' THEN 1 END) AS done_count,
        COUNT(CASE WHEN sm.slack_status = 'pending' THEN 1 END) AS pending_count,
        COUNT(CASE WHEN sm.slack_status = 'cancelled' THEN 1 END) AS cancelled_count,
        COALESCE(SUM(sm.parsed_amount) FILTER (WHERE sm.message_type IN ('card_payment', 'expense_share', 'deposit_request', 'tax_invoice')), 0) AS total_expense
    FROM slack_messages sm
    WHERE {summary_where_clause}
    GROUP BY yr, mo
    ORDER BY yr DESC, mo DESC
    """,
    summary_params,
)
monthly_summary = fetch_all(cur2)
cur2.close()
```

- [ ] **Step 3: 전체 테스트 실행**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/ -v`
Expected: All 161 tests pass (변경은 쿼리 파라미터 추가뿐, 기존 동작 유지)

- [ ] **Step 4: Commit**

```bash
git add backend/routers/slack.py
git commit -m "feat: GET /api/slack/messages에 month 필터 파라미터 추가"
```

---

### Task 2: 프론트엔드 — MonthPicker 도입 + MonthSection 제거

**Files:**
- Modify: `frontend/src/app/slack-match/page.tsx`

- [ ] **Step 1: import 추가 및 불필요한 코드 제거**

파일 상단에 MonthPicker import 추가:
```typescript
import { MonthPicker } from "@/components/month-picker"
```

아래 함수/컴포넌트를 **삭제**:
- `groupByMonth` 함수 (line 128-143)
- `formatMonthLabel` 함수 (line 145-149)
- `MonthSection` 컴포넌트 (line 429-505)

- [ ] **Step 2: SlackMatchContent에 selectedMonth 상태 추가**

`SlackMatchContent` 함수 안, 기존 state 선언 부분에 추가:

```typescript
// Month navigation
const [selectedMonth, setSelectedMonth] = useState<string>(() => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
})
```

- [ ] **Step 3: fetchMessages에 month 파라미터 추가**

`fetchMessages` useCallback 안의 API 호출을 수정:

```typescript
const fetchMessages = useCallback(async () => {
  setLoading(true)
  setError(null)
  try {
    const data = await fetchAPI<SlackMessagesResponse>(
      `/slack/messages?entity_id=${entityId}&page=${page}&per_page=50&month=${selectedMonth}`,
    )
    setMessages(data.items)
    setTotal(data.total)
    setPages(data.pages)
    setMonthlySummary(data.monthly_summary || [])
  } catch (err) {
    setError(
      err instanceof Error ? err.message : "Slack 데이터를 불러올 수 없습니다.",
    )
  } finally {
    setLoading(false)
  }
}, [entityId, page, selectedMonth])
```

dependency array에 `selectedMonth` 추가. `per_page`를 50으로 올림 (월별 데이터가 적으므로).

- [ ] **Step 4: entity 변경 시 selectedMonth 리셋 제거 (유지)**

기존 entity 변경 useEffect에서 selectedMonth는 리셋하지 않는다 (월은 유지하는게 자연스러움). page만 리셋:

```typescript
useEffect(() => {
  setSelectedMessageId(null)
  setExpandedId(null)
  setPage(1)
}, [entityId])
```

selectedMonth 변경 시 page 리셋 추가:

```typescript
useEffect(() => {
  setPage(1)
  setSelectedMessageId(null)
  setExpandedId(null)
}, [selectedMonth])
```

- [ ] **Step 5: KPI를 선택된 월 기준으로 변경**

기존 KPI 계산 부분 (kpiTotal, kpiDone, kpiPending, kpiCancelled)을 selectedMonth 기준 summary에서 추출:

```typescript
// KPI: 선택된 월의 summary
const selectedSummary = monthlySummary.find((s) => {
  const key = `${s.yr}-${String(s.mo).padStart(2, "0")}`
  return key === selectedMonth
})
const kpiTotal = selectedSummary?.total ?? 0
const kpiDone = selectedSummary?.done_count ?? 0
const kpiPending = selectedSummary?.pending_count ?? 0
const kpiCancelled = selectedSummary?.cancelled_count ?? 0
```

- [ ] **Step 6: MonthPicker를 헤더에 배치**

SUCCESS 영역의 헤더 부분 (`<div className="flex flex-col sm:flex-row ...">`)을 수정:

```tsx
{/* Header */}
<div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
  <div className="flex items-center gap-4">
    <h1 className="text-2xl font-semibold tracking-tight">Slack 매칭</h1>
    <MonthPicker
      months={monthlySummary.map((s) =>
        `${s.yr}-${String(s.mo).padStart(2, "0")}`
      )}
      selected={selectedMonth}
      onSelect={setSelectedMonth}
    />
  </div>
  <Button onClick={handleSync} disabled={syncing} variant="outline" className="gap-2">
    <RefreshCw className={cn("h-4 w-4", syncing && "animate-spin")} />
    {syncing ? "동기화 중..." : "Slack 동기화"}
  </Button>
</div>
```

- [ ] **Step 7: 메시지 리스트를 flat 리스트로 변경 (MonthSection 제거)**

기존 monthGroups 관련 코드를 제거하고, filteredMessages를 직접 flat 리스트로 렌더링:

기존:
```tsx
const monthGroups = groupByMonth(filteredMessages)
```
→ 이 줄 삭제

기존 `Array.from(monthGroups.entries()).map(...)` 렌더링을 교체:

```tsx
{/* Left: Message list */}
<div className="space-y-1" role="listbox" aria-label="Slack 메시지 목록">
  {filteredMessages.length === 0 ? (
    <div className="flex flex-col items-center justify-center py-8 gap-2">
      <Search className="h-8 w-8 text-muted-foreground" />
      <p className="text-sm text-muted-foreground">
        이 달에 메시지가 없습니다.
      </p>
    </div>
  ) : (
    filteredMessages.map((msg) => (
      <CompactMessageRow
        key={msg.id}
        message={msg}
        isSelected={selectedMessageId === msg.id}
        isExpanded={expandedId === msg.id}
        onSelect={() => setSelectedMessageId(msg.id)}
        onToggleExpand={() => handleToggleExpand(msg.id)}
        onConfirmDirect={() => handleConfirmDirect(msg)}
        onIgnore={() => handleIgnore(msg.id)}
        onManualMatch={() => handleManualMatch(msg.id)}
      />
    ))
  )}

  {/* Pagination */}
  {pages > 1 && (
    <div className="flex items-center justify-center gap-2 pt-4">
      <Button
        variant="ghost"
        size="sm"
        disabled={page <= 1}
        onClick={() => setPage((p) => Math.max(1, p - 1))}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <span className="text-sm text-muted-foreground">
        {page} / {pages}
      </span>
      <Button
        variant="ghost"
        size="sm"
        disabled={page >= pages}
        onClick={() => setPage((p) => Math.min(pages, p + 1))}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  )}
</div>
```

- [ ] **Step 8: 서버 시작 후 수동 확인**

```bash
cd frontend && npm run dev
```

브라우저에서 `http://localhost:3000/slack-match?entity=1` 접속:
- MonthPicker가 헤더에 표시되는지 확인
- ◀ ▶ 클릭 시 월 전환 + 데이터 재로딩 확인
- KPI가 선택된 월 기준으로 변경되는지 확인
- 필터(상태/신뢰도)가 정상 작동하는지 확인

- [ ] **Step 9: Commit**

```bash
git add frontend/src/app/slack-match/page.tsx
git commit -m "feat: Slack 매칭 MonthPicker 도입 — 월별 서버 필터링"
```

---

### Task 3: 카드 접힌 상태에 메시지 요약 1줄 추가

**Files:**
- Modify: `frontend/src/app/slack-match/page.tsx` (CompactMessageRow 컴포넌트)

- [ ] **Step 1: stripSlackText 헬퍼 함수 추가**

파일 상단 Helpers 섹션에 추가:

```typescript
function stripSlackText(text: string): string {
  return text
    .replace(/<@[A-Z0-9]+>/g, "")           // 멘션 제거
    .replace(/<#[A-Z0-9]+\|([^>]+)>/g, "$1") // 채널 링크 → 채널명
    .replace(/<(https?:\/\/[^|>]+)\|([^>]+)>/g, "$2") // URL 링크 → 표시 텍스트
    .replace(/<(https?:\/\/[^>]+)>/g, "$1")  // URL 링크 (표시 텍스트 없음)
    .replace(/\*([^*]+)\*/g, "$1")           // 볼드 제거
    .replace(/_([^_]+)_/g, "$1")             // 이탤릭 제거
    .replace(/~([^~]+)~/g, "$1")             // 취소선 제거
    .replace(/\n+/g, " ")                    // 줄바꿈 → 공백
    .replace(/\s+/g, " ")                    // 다중 공백 정리
    .trim()
}
```

- [ ] **Step 2: CompactMessageRow 접힌 상태에 요약 줄 추가**

`CompactMessageRow` 컴포넌트의 `<button>` (compact summary line) 바로 뒤, `{isExpanded && (` 바로 앞에 요약 줄 추가:

```tsx
{/* Summary preview (collapsed) */}
{!isExpanded && message.message_text && (
  <p className="px-3 pb-2 text-xs text-muted-foreground truncate">
    {stripSlackText(message.message_text).slice(0, 80)}
  </p>
)}
```

이렇게 하면 접힌 상태에서:
```
🟡 입금요청  Rosse Han  03/15  ₩3,000  ▼
   아래와 같이 ODD. 스마트스토어 리뷰 작업 비용 결제가 필요하여 검토 부탁드리겠습니다! [ODD. 스마트...
```

- [ ] **Step 3: 수동 확인**

브라우저에서 확인:
- 접힌 카드에 메시지 요약 1줄이 표시되는지
- Slack 멘션(`<@U07TGKTAGMV>`)이 제거되었는지
- 볼드(`*텍스트*`)가 plain text로 변환되었는지
- 80자 초과 시 `...` (CSS truncate)로 잘리는지
- 펼친 상태에서는 요약 줄이 숨겨지는지

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/slack-match/page.tsx
git commit -m "feat: Slack 카드 접힌 상태에 메시지 요약 1줄 표시"
```
