# Slack 매칭 UI 재설계 + 환율 변환 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slack 메시지의 USD/EUR 금액을 환율 서비스로 원화 환산하고, 매칭 UI를 월별 그룹 + 카드 요약 + 클릭 상세보기로 재설계

**Architecture:** 백엔드 sync에서 exchange_rate_service로 외화 → KRW 변환. 프론트는 월별 섹션 + 접기/펼치기 카드 UI. 기존 후보 검색/확정 API는 그대로 활용.

**Tech Stack:** FastAPI, exchange_rate_service.py, Next.js 14, shadcn/ui (Collapsible, Card)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/routers/slack.py` | sync에서 환율 변환 + list API에 월별 그룹 옵션 |
| Modify | `backend/services/slack/message_parser.py` | parse_message에 원화 환산 금액 추가 |
| Create | `backend/tests/test_slack_currency.py` | 환율 변환 테스트 |
| Rewrite | `frontend/src/app/slack-match/page.tsx` | 월별 그룹 + 카드 요약 + 상세 펼치기 UI |

---

### Task 1: 백엔드 — sync 시 외화 → KRW 환율 변환

**Files:**
- Modify: `backend/routers/slack.py`
- Create: `backend/tests/test_slack_currency.py`

- [ ] **Step 1: Write failing test for currency conversion**

```python
# backend/tests/test_slack_currency.py
"""Slack 메시지 환율 변환 테스트"""

import pytest
from unittest.mock import MagicMock
from decimal import Decimal


def test_usd_to_krw_conversion():
    """USD 금액이 KRW로 변환되는지 확인"""
    from backend.services.slack.message_parser import convert_to_krw

    # mock cursor that returns exchange rate
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_cur.fetchone.return_value = (Decimal("1400.00"), __import__("datetime").date(2026, 1, 15))

    result = convert_to_krw(
        amount=11.0,
        currency="USD",
        msg_date=__import__("datetime").date(2026, 1, 15),
        conn=mock_conn,
    )
    assert result == 15400.0  # 11 * 1400


def test_krw_passthrough():
    """KRW는 변환 없이 그대로 반환"""
    from backend.services.slack.message_parser import convert_to_krw

    result = convert_to_krw(
        amount=35000,
        currency="KRW",
        msg_date=__import__("datetime").date(2026, 1, 15),
        conn=MagicMock(),
    )
    assert result == 35000


def test_no_rate_returns_original():
    """환율 없으면 원본 금액 반환 (에러 안 남)"""
    from backend.services.slack.message_parser import convert_to_krw

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_cur.fetchone.return_value = None

    result = convert_to_krw(
        amount=11.0,
        currency="USD",
        msg_date=__import__("datetime").date(2026, 1, 15),
        conn=mock_conn,
    )
    # 환율 없으면 원본 반환
    assert result == 11.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_slack_currency.py -v`
Expected: FAIL — `ImportError: cannot import name 'convert_to_krw'`

- [ ] **Step 3: Implement convert_to_krw in message_parser.py**

`backend/services/slack/message_parser.py` 맨 아래에 추가:

```python
# ── 환율 변환 ─────────────────────────────────────────

def convert_to_krw(amount: float, currency: str, msg_date, conn) -> float:
    """외화 금액을 KRW로 변환. KRW면 그대로 반환. 환율 없으면 원본 반환."""
    if currency == "KRW" or amount is None:
        return amount

    try:
        from backend.services.exchange_rate_service import get_closing_rate
        rate = get_closing_rate(conn, currency, "KRW", msg_date)
        return round(float(amount) * float(rate), 0)
    except Exception:
        # 환율 조회 실패 시 원본 금액 반환 (매칭 시 수동 처리)
        return amount
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_slack_currency.py -v`
Expected: ALL PASS

- [ ] **Step 5: sync 엔드포인트에서 환율 변환 적용**

`backend/routers/slack.py`의 sync 함수에서, `final_amount` 계산 후에 환율 변환 추가.

기존 코드 (final_amount 계산 부분 이후):
```python
            final_amount = parsed.get("parsed_amount")
            if thread_events.get("new_amount") is not None:
                final_amount = thread_events["new_amount"]
```

변경:
```python
            final_amount = parsed.get("parsed_amount")
            if thread_events.get("new_amount") is not None:
                final_amount = thread_events["new_amount"]

            # 외화 → KRW 변환
            if final_amount is not None and parsed["currency"] != "KRW":
                from backend.services.slack.message_parser import convert_to_krw
                from datetime import datetime as dt
                msg_date = dt.fromtimestamp(float(ts)).date()
                final_amount = convert_to_krw(final_amount, parsed["currency"], msg_date, conn)
```

- [ ] **Step 6: 기존 데이터 업데이트 — 재동기화**

sync를 다시 실행하면 `ON CONFLICT DO UPDATE`로 기존 USD 메시지의 `parsed_amount`가 KRW로 업데이트됨.

- [ ] **Step 7: Commit**

```bash
git add backend/services/slack/message_parser.py backend/routers/slack.py backend/tests/test_slack_currency.py
git commit -m "feat: Slack sync 시 USD/EUR → KRW 환율 변환 (exchange_rate_service 활용)"
```

---

### Task 2: 백엔드 — list API에 월별 정보 + 요약 데이터 추가

**Files:**
- Modify: `backend/routers/slack.py`

- [ ] **Step 1: list_slack_messages에 월별 요약 추가**

기존 `list_slack_messages` 함수의 반환값에 월별 요약 통계를 추가.

함수 끝부분, `return` 직전에:

```python
    # 월별 요약 통계
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
            COALESCE(SUM(sm.parsed_amount) FILTER (WHERE sm.message_type IN ('card_payment', 'expense_share')), 0) AS total_expense
        FROM slack_messages sm
        WHERE {where_clause}
        GROUP BY yr, mo
        ORDER BY yr DESC, mo DESC
        """,
        params,
    )
    monthly_summary = fetch_all(cur2)
    cur2.close()
```

반환값 수정:

```python
    return {
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
        "monthly_summary": monthly_summary,
    }
```

- [ ] **Step 2: list API에 project_tag 필드 포함 확인**

기존 SELECT에 `sm.project_tag`이 이미 포함되어 있는지 확인. 포함되어 있으면 OK.

- [ ] **Step 3: Commit**

```bash
git add backend/routers/slack.py
git commit -m "feat: Slack 메시지 목록에 월별 요약 통계 추가"
```

---

### Task 3: 프론트엔드 — Slack 매칭 UI 재설계

**Files:**
- Rewrite: `frontend/src/app/slack-match/page.tsx`

이 Task는 프론트엔드 전체 재설계. 기존 파일을 리라이트합니다.

- [ ] **Step 1: SlackMessage 인터페이스 업데이트**

기존 인터페이스에 누락된 필드 추가:

```typescript
interface SlackMessage {
  id: number
  entity_id: number
  channel_name: string
  sender_name: string | null
  message_text: string
  parsed_amount: number | null
  parsed_amount_vat_included: number | null
  vat_flag: string | null
  project_tag: string | null
  message_date: string | null
  is_completed: boolean
  is_cancelled: boolean
  slack_status: string | null
  message_type: string | null
  currency: string | null
  member_id: number | null
  reply_count: number
  match_id: number | null
  matched_transaction_id: number | null
  match_confidence: number | null
  match_confirmed: boolean | null
}

interface MonthlySummary {
  yr: number
  mo: number
  total: number
  done_count: number
  pending_count: number
  cancelled_count: number
  total_expense: number
}

interface SlackMessagesResponse {
  items: SlackMessage[]
  total: number
  page: number
  pages: number
  monthly_summary: MonthlySummary[]
}
```

- [ ] **Step 2: 월별 그룹핑 로직**

```typescript
// 메시지를 월별로 그룹핑
function groupByMonth(messages: SlackMessage[]): Map<string, SlackMessage[]> {
  const groups = new Map<string, SlackMessage[]>()
  for (const msg of messages) {
    // ts에서 월 추출 (Slack ts = unix timestamp)
    const date = msg.message_date
      ? new Date(msg.message_date)
      : new Date()
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(msg)
  }
  return groups
}
```

- [ ] **Step 3: 메시지 카드 컴포넌트 재설계 — 요약 카드**

카드에 보여줄 요약 정보:
- 프로젝트 태그 배지 (있으면)
- 메시지 유형 배지 (법카결제/입금요청/세금계산서/비용공유)
- 금액 (큰 글씨)
- 보낸 사람 이름
- 상태 (done/pending/cancelled)
- 매칭 상태 (매칭됨/미매칭)

```tsx
function MessageCard({ message, isExpanded, onToggle, onConfirmDirect, onIgnore, onSelect }: {
  message: SlackMessage
  isExpanded: boolean
  onToggle: () => void
  onConfirmDirect: () => void
  onIgnore: () => void
  onSelect: () => void
}) {
  const status = message.slack_status || "pending"
  const typeLabels: Record<string, string> = {
    card_payment: "법카결제",
    deposit_request: "입금요청",
    tax_invoice: "세금계산서",
    expense_share: "비용공유",
  }

  return (
    <div
      className={cn(
        "rounded-xl border transition-all",
        status === "done" ? "border-white/[0.04] bg-card/50" :
        status === "cancelled" ? "border-white/[0.04] bg-card/30 opacity-60" :
        "border-white/[0.06] bg-card",
      )}
    >
      {/* Summary row — always visible */}
      <button
        className="w-full text-left px-4 py-3 flex items-center gap-3"
        onClick={onToggle}
      >
        {/* Project tag */}
        {message.project_tag && (
          <Badge variant="outline" className="text-[10px] shrink-0 bg-indigo-500/10 text-indigo-400 border-indigo-500/20">
            {message.project_tag}
          </Badge>
        )}

        {/* Type badge */}
        <Badge variant="outline" className={cn(
          "text-[10px] shrink-0",
          message.message_type === "card_payment" ? "bg-blue-500/10 text-blue-400 border-blue-500/20" :
          message.message_type === "deposit_request" ? "bg-amber-500/10 text-amber-400 border-amber-500/20" :
          "bg-secondary text-muted-foreground border-transparent",
        )}>
          {typeLabels[message.message_type || ""] || "기타"}
        </Badge>

        {/* Amount */}
        <span className="font-mono font-semibold text-sm tabular-nums flex-1">
          {message.parsed_amount != null
            ? (message.currency === "USD"
              ? `$${message.parsed_amount.toLocaleString()}`
              : formatKRW(message.parsed_amount))
            : "—"}
        </span>

        {/* Sender */}
        <span className="text-xs text-muted-foreground truncate max-w-[100px]">
          {message.sender_name || "—"}
        </span>

        {/* Status indicator */}
        <span className={cn(
          "h-2 w-2 rounded-full shrink-0",
          status === "done" ? "bg-green-500" :
          status === "cancelled" ? "bg-red-500" :
          "bg-amber-500",
        )} />

        {/* Chevron */}
        <ChevronDown className={cn(
          "h-4 w-4 text-muted-foreground transition-transform",
          isExpanded && "rotate-180",
        )} />
      </button>

      {/* Expanded detail */}
      {isExpanded && (
        <div className="px-4 pb-4 pt-0 space-y-3 border-t border-white/[0.04]">
          {/* Message text */}
          <p className="text-sm leading-relaxed whitespace-pre-wrap text-muted-foreground mt-3">
            {message.message_text}
          </p>

          {/* Meta info */}
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            {message.vat_flag && message.vat_flag !== "none" && (
              <span>VAT: {message.vat_flag === "included" ? "포함" : "별도"}</span>
            )}
            {message.reply_count > 0 && (
              <span>댓글 {message.reply_count}개</span>
            )}
            {message.match_confirmed && (
              <Badge variant="outline" className="text-[10px] bg-green-500/10 text-green-400 border-green-500/20">
                거래 매칭됨
              </Badge>
            )}
          </div>

          {/* Actions — only for pending */}
          {status === "pending" && (
            <div className="flex gap-2 pt-1">
              {message.matched_transaction_id && (
                <Button size="sm" onClick={(e) => { e.stopPropagation(); onConfirmDirect() }}
                  className="bg-[hsl(var(--accent))] text-accent-foreground hover:bg-[hsl(var(--accent))]/90 h-8 text-xs">
                  <Check className="h-3 w-3 mr-1" /> 확정
                </Button>
              )}
              <Button size="sm" variant="secondary" className="h-8 text-xs" onClick={(e) => { e.stopPropagation(); onSelect() }}>
                <Search className="h-3 w-3 mr-1" /> 수동 매칭
              </Button>
              <Button size="sm" variant="ghost" className="h-8 text-xs text-[hsl(var(--loss))]"
                onClick={(e) => { e.stopPropagation(); onIgnore() }}>
                <EyeOff className="h-3 w-3 mr-1" /> 무시
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: 월별 섹션 컴포넌트**

```tsx
function MonthSection({
  yearMonth,
  messages,
  summary,
  expandedId,
  selectedMessageId,
  onToggle,
  onSelect,
  onConfirmDirect,
  onIgnore,
}: {
  yearMonth: string
  messages: SlackMessage[]
  summary?: MonthlySummary
  expandedId: number | null
  selectedMessageId: number | null
  onToggle: (id: number) => void
  onSelect: (id: number) => void
  onConfirmDirect: (msg: SlackMessage) => void
  onIgnore: (id: number) => void
}) {
  const [collapsed, setCollapsed] = useState(false)
  const [year, month] = yearMonth.split("-").map(Number)
  const monthName = `${year}년 ${month}월`

  return (
    <div>
      {/* Month header */}
      <button
        className="flex items-center gap-3 w-full py-2 mb-2"
        onClick={() => setCollapsed(!collapsed)}
      >
        <h3 className="text-sm font-semibold">{monthName}</h3>
        <span className="text-xs text-muted-foreground">
          {messages.length}건
          {summary && summary.pending_count > 0 && (
            <span className="text-amber-400 ml-1">({summary.pending_count} 미처리)</span>
          )}
        </span>
        {summary && (
          <span className="text-xs font-mono text-muted-foreground ml-auto">
            {formatKRW(summary.total_expense)}
          </span>
        )}
        <ChevronDown className={cn(
          "h-3 w-3 text-muted-foreground transition-transform",
          collapsed && "-rotate-90",
        )} />
      </button>

      {/* Messages */}
      {!collapsed && (
        <div className="space-y-1.5 ml-1">
          {messages.map((msg) => (
            <MessageCard
              key={msg.id}
              message={msg}
              isExpanded={expandedId === msg.id}
              onToggle={() => onToggle(msg.id)}
              onConfirmDirect={() => onConfirmDirect(msg)}
              onIgnore={() => onIgnore(msg.id)}
              onSelect={() => onSelect(msg.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 5: SlackMatchContent 메인 컴포넌트 리라이트**

기존 2패널 레이아웃을 유지하되:
- 왼쪽: 월별 섹션 + 카드 요약 (접기/펼치기)
- 오른쪽: 선택한 메시지의 후보 패널 (기존 CandidatePanel 재사용)

핵심 변경:
- `expandedId` state 추가 (어떤 카드가 펼쳐져 있는지)
- `filteredMessages`를 `groupByMonth()`로 그룹핑
- 월별 헤더에 summary 통계 표시

```typescript
// 기존 filteredMessages 아래에:
const monthGroups = groupByMonth(filteredMessages)
const [expandedId, setExpandedId] = useState<number | null>(null)

const handleToggle = (id: number) => {
  setExpandedId(expandedId === id ? null : id)
}
```

렌더링에서 기존 `filteredMessages.map(...)` 대신:

```tsx
{Array.from(monthGroups.entries()).map(([yearMonth, msgs]) => {
  const [y, m] = yearMonth.split("-").map(Number)
  const summary = monthlySummary?.find(s => s.yr === y && s.mo === m)
  return (
    <MonthSection
      key={yearMonth}
      yearMonth={yearMonth}
      messages={msgs}
      summary={summary}
      expandedId={expandedId}
      selectedMessageId={selectedMessageId}
      onToggle={handleToggle}
      onSelect={(id) => setSelectedMessageId(id)}
      onConfirmDirect={(msg) => {
        if (msg.matched_transaction_id) handleConfirm(msg.id, msg.matched_transaction_id)
      }}
      onIgnore={(id) => handleIgnore(id)}
    />
  )
})}
```

- [ ] **Step 6: monthlySummary state 추가**

```typescript
const [monthlySummary, setMonthlySummary] = useState<MonthlySummary[]>([])
```

fetchMessages에서 summary도 저장:

```typescript
const data = await fetchAPI<SlackMessagesResponse>(...)
setMessages(data.items)
setMonthlySummary(data.monthly_summary || [])
```

- [ ] **Step 7: KPI 카드 상단에 전체 요약**

필터/동기화 버튼 아래에:

```tsx
{/* Summary KPIs */}
<div className="grid grid-cols-4 gap-3">
  <Card className="bg-card rounded-xl p-3">
    <p className="text-xs text-muted-foreground">전체</p>
    <p className="text-lg font-semibold">{messages.length}건</p>
  </Card>
  <Card className="bg-card rounded-xl p-3">
    <p className="text-xs text-muted-foreground">완료</p>
    <p className="text-lg font-semibold text-green-400">{messages.filter(m => m.slack_status === "done").length}</p>
  </Card>
  <Card className="bg-card rounded-xl p-3">
    <p className="text-xs text-muted-foreground">미처리</p>
    <p className="text-lg font-semibold text-amber-400">{messages.filter(m => m.slack_status === "pending").length}</p>
  </Card>
  <Card className="bg-card rounded-xl p-3">
    <p className="text-xs text-muted-foreground">취소</p>
    <p className="text-lg font-semibold text-red-400">{messages.filter(m => m.slack_status === "cancelled").length}</p>
  </Card>
</div>
```

- [ ] **Step 8: ChevronDown import 추가**

lucide-react import에 `ChevronDown` 추가 (기존 `ChevronLeft`, `ChevronRight` 옆에).

- [ ] **Step 9: 빌드 확인**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: Build 성공

- [ ] **Step 10: Commit**

```bash
git add frontend/src/app/slack-match/page.tsx
git commit -m "feat: Slack 매칭 UI 재설계 — 월별 그룹 + 카드 요약 + 환율 변환"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - ✅ USD/EUR → KRW 환율 변환 (Task 1, exchange_rate_service 활용)
   - ✅ 월별 그룹핑 (Task 3, groupByMonth)
   - ✅ 카드 요약 보기 (Task 3, MessageCard summary row)
   - ✅ 클릭 시 상세 보기 (Task 3, isExpanded)
   - ✅ 월별 요약 통계 (Task 2, monthly_summary)
   - ✅ KPI 카드 (Task 3, Step 7)

2. **Placeholder scan:** 없음. 모든 step에 실제 코드 포함.

3. **Type consistency:** `SlackMessage.slack_status` → `status` 변수 → MessageCard에서 사용. `MonthlySummary.yr/mo` → monthGroups key와 일치. `convert_to_krw()` → sync에서 호출 일관.
