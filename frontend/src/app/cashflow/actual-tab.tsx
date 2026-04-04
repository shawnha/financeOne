"use client"

import { useEffect, useState, useCallback, useMemo, useRef } from "react"
import { useGlobalMonth } from "@/hooks/use-global-month"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { fetchAPI } from "@/lib/api"
import { formatByEntity, abbreviateAmount } from "@/lib/format"
import {
  Bar,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
  Area,
  ComposedChart,
  Cell,
} from "recharts"
import { AlertCircle, RefreshCw, Upload, ChevronDown, ChevronUp, Download, List, FolderTree } from "lucide-react"
import Link from "next/link"
import { cn } from "@/lib/utils"
import { MonthPicker } from "@/components/month-picker"

// ── Types ──────────────────────────────────────────────

interface SummaryMonth {
  month: string
  opening_balance: number
  income: number
  expense: number
  net: number
  closing_balance: number
}

interface SummaryData {
  months: SummaryMonth[]
  available_months: string[]
  period_start_balance: number
  period_end_balance: number
}

interface ActualRow {
  type: string
  date: string | null
  description: string
  counterparty?: string
  amount: number
  balance: number
  tx_id: number | null
  source_type?: string
  internal_account_id?: number | null
  internal_account_name?: string | null
}

interface ActualData {
  year: number
  month: number
  opening_balance: number
  closing_balance: number
  rows: ActualRow[]
}

type LoadState = "loading" | "empty" | "error" | "success"

// ── Count-up Hook ─────────────────────────────────────

function useCountUp(target: number, duration = 600): number {
  const [current, setCurrent] = useState(0)
  const startRef = useRef<number | null>(null)
  const rafRef = useRef<number>(0)

  useEffect(() => {
    startRef.current = null
    const animate = (ts: number) => {
      if (startRef.current === null) startRef.current = ts
      const elapsed = ts - startRef.current
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setCurrent(target * eased)
      if (progress < 1) rafRef.current = requestAnimationFrame(animate)
    }
    rafRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(rafRef.current)
  }, [target, duration])

  return current
}

// ── KPI Card ───────────────────────────────────────────

function KPICard({
  label,
  value,
  rawAmount,
  subtext,
  colorClass,
  subtextColor,
  entityId,
}: {
  label: string
  value: string
  rawAmount?: number
  subtext?: string
  colorClass?: string
  subtextColor?: string
  entityId?: string | null
}) {
  const animated = useCountUp(rawAmount ?? 0)
  const displayValue = rawAmount != null && entityId != null
    ? (value.startsWith("+") ? "+" : value.startsWith("-") ? "-" : "") + formatByEntity(Math.abs(animated), entityId)
    : value

  return (
    <Card className="bg-secondary rounded-xl p-4">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={cn("text-lg md:text-xl lg:text-[28px] font-bold font-mono tabular-nums mt-1 truncate", colorClass)}>
        {displayValue}
      </p>
      {subtext && <p className={cn("text-[11px] mt-0.5", subtextColor || "text-muted-foreground")}>{subtext}</p>}
    </Card>
  )
}

// ── Type Badge ─────────────────────────────────────────

function TypeBadge({ type, description }: { type: string; description: string }) {
  // Detect card payment from description
  if (type === "out" && /카드\(주\)|카드대금/.test(description)) {
    return <Badge variant="outline" className="text-[10px] font-semibold px-2 py-0.5 bg-purple-500/12 text-purple-400">카드대금</Badge>
  }
  if (type === "out" && /선결제/.test(description)) {
    return <Badge variant="outline" className="text-[10px] font-semibold px-2 py-0.5 bg-purple-500/12 text-purple-400">선결제</Badge>
  }
  if (type === "in") {
    return <Badge variant="outline" className="text-[10px] font-semibold px-2 py-0.5 bg-green-500/12 text-green-400">입금</Badge>
  }
  if (type === "out") {
    return <Badge variant="outline" className="text-[10px] font-semibold px-2 py-0.5 bg-red-500/12 text-red-400">출금</Badge>
  }
  return null
}

// ── Custom Bar Shape for rounded + opacity ─────────────

function CustomBar(props: {
  x?: number
  y?: number
  width?: number
  height?: number
  fill?: string
  isSelected?: boolean
  dataKey?: string
}) {
  const { x = 0, y = 0, width = 0, height = 0, fill, isSelected, dataKey } = props
  const opacity = isSelected ? 1 : 0.35
  const strokeWidth = isSelected ? 1 : 0.5
  const gradientId = dataKey === "income" ? "incomeBarGrad" : "expenseBarGrad"
  return (
    <rect
      x={x}
      y={y}
      width={width}
      height={height}
      rx={6}
      ry={6}
      fill={`url(#${gradientId})`}
      stroke={dataKey === "income" ? "#22C55E" : "#EF4444"}
      strokeWidth={strokeWidth}
      opacity={opacity}
    />
  )
}

// ── Component ──────────────────────────────────────────

export function ActualTab({ entityId }: { entityId: string | null }) {
  const [summary, setSummary] = useState<SummaryData | null>(null)
  const [detail, setDetail] = useState<ActualData | null>(null)
  const [state, setState] = useState<LoadState>("loading")
  const [detailState, setDetailState] = useState<LoadState>("loading")
  const [error, setError] = useState("")
  const [viewMode, setViewMode] = useState<"time" | "account">("time")
  const [globalMonth, setGlobalMonth, monthReady] = useGlobalMonth()
  const [selectedMonth, setSelectedMonthLocal] = useState(globalMonth)
  const setSelectedMonth = useCallback((m: string) => { setSelectedMonthLocal(m); setGlobalMonth(m) }, [setGlobalMonth])

  // globalMonth가 localStorage에서 복원되면 동기화
  useEffect(() => { setSelectedMonthLocal(globalMonth) }, [globalMonth])

  // Fetch summary (chart data)
  const fetchSummary = useCallback(async () => {
    if (!entityId) return
    setState("loading")
    try {
      const data = await fetchAPI<SummaryData>(
        `/cashflow/summary?entity_id=${entityId}&months=12`,
        { cache: "no-store" },
      )
      setSummary(data)
      if (!data.available_months.length) {
        setState("empty")
        return
      }
      setState("success")
      // 글로벌 월이 available에 없으면 최근 월로 fallback
      if (!selectedMonth || !data.available_months.includes(selectedMonth)) {
        const fallback = data.available_months[data.available_months.length - 1]
        setSelectedMonth(fallback)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "데이터를 불러올 수 없습니다.")
      setState("error")
    }
  }, [entityId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch detail for selected month
  const fetchDetail = useCallback(async () => {
    if (!entityId || !selectedMonth) return
    setDetailState("loading")
    const [y, m] = selectedMonth.split("-").map(Number)
    try {
      const data = await fetchAPI<ActualData>(
        `/cashflow/actual?entity_id=${entityId}&year=${y}&month=${m}`,
        { cache: "no-store" },
      )
      setDetail(data)
      setDetailState(data.rows.length <= 2 ? "empty" : "success") // only opening+closing = empty
    } catch {
      setDetailState("error")
    }
  }, [entityId, selectedMonth])

  useEffect(() => { fetchSummary() }, [fetchSummary])
  useEffect(() => { fetchDetail() }, [fetchDetail])

  // Tooltip
  function ChartTooltipContent({
    active,
    payload,
    label,
  }: {
    active?: boolean
    payload?: Array<{ value: number; name: string; color: string }>
    label?: string
  }) {
    if (!active || !payload?.length) return null
    return (
      <div className="rounded-lg bg-popover border border-border px-3 py-2 shadow-lg text-sm">
        <p className="text-muted-foreground mb-1">{label}</p>
        {payload.map((entry) => (
          <p key={entry.name} className="font-mono tabular-nums" style={{ color: entry.color }}>
            {entry.name}: {formatByEntity(entry.value, entityId)}
          </p>
        ))}
      </div>
    )
  }

  // ── LOADING ──
  if (state === "loading") {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-[300px] w-full rounded-xl" />
        <Skeleton className="h-[200px] w-full rounded-xl" />
      </div>
    )
  }

  // ── ERROR ──
  if (state === "error") {
    return (
      <Card className="p-8 flex flex-col items-center justify-center text-center gap-4">
        <AlertCircle className="h-12 w-12 text-[hsl(var(--loss))]" />
        <p className="text-lg font-medium">데이터를 불러올 수 없습니다.</p>
        <p className="text-sm text-muted-foreground">{error}</p>
        <Button onClick={fetchSummary} variant="secondary" className="gap-2">
          <RefreshCw className="h-4 w-4" />
          다시 시도
        </Button>
      </Card>
    )
  }

  // ── EMPTY ──
  if (state === "empty") {
    return (
      <Card className="p-12 flex flex-col items-center justify-center text-center gap-4">
        <Upload className="h-12 w-12 text-muted-foreground" />
        <p className="text-lg font-medium">거래 데이터를 업로드해보세요</p>
        <p className="text-sm text-muted-foreground">
          Excel 파일을 업로드하면 현금흐름이 자동으로 계산됩니다.
        </p>
        <Button asChild className="bg-[hsl(var(--accent))] text-accent-foreground hover:bg-[hsl(var(--accent))]/90 gap-2">
          <Link href="/upload"><Upload className="h-4 w-4" /> Excel 업로드</Link>
        </Button>
      </Card>
    )
  }

  // ── SUCCESS ──
  const months = summary!.available_months
  const chartData = summary!.months.map((m) => ({
    ...m,
    isSelected: m.month === selectedMonth,
    // Make expense positive for chart display (bars go up)
    expenseAbs: Math.abs(m.expense),
  }))

  // Current month KPI
  const currentSummary = chartData.find((m) => m.month === selectedMonth)
  const opening = currentSummary?.opening_balance ?? 0
  const income = currentSummary?.income ?? 0
  const expense = currentSummary?.expense ?? 0
  const closing = currentSummary?.closing_balance ?? 0
  const net = currentSummary?.net ?? 0

  return (
    <div className="space-y-6">
      {/* Header: Month nav + Actions */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <MonthPicker months={months} selected={selectedMonth} onSelect={setSelectedMonth} accentColor="hsl(var(--profit))" />
        <Button variant="outline" size="sm" className="gap-2">
          <Download className="h-4 w-4" /> 내보내기
        </Button>
      </div>

      {/* Chart: Bar (income/expense) + Area (net cashflow) */}
      <Card className="p-6 rounded-2xl">
        <div className="h-[220px] max-md:h-[180px]">
          <ResponsiveContainer width="100%" height="100%" minWidth={0}>
            <ComposedChart data={chartData} margin={{ top: 20, right: 10, left: 10, bottom: 5 }}>
              <defs>
                <linearGradient id="incomeBarGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#22C55E" stopOpacity={0.6} />
                  <stop offset="100%" stopColor="#22C55E" stopOpacity={0.05} />
                </linearGradient>
                <linearGradient id="expenseBarGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#EF4444" stopOpacity={0.6} />
                  <stop offset="100%" stopColor="#EF4444" stopOpacity={0.05} />
                </linearGradient>
                <linearGradient id="netAreaGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#F59E0B" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#F59E0B" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="4 4" stroke="rgba(255,255,255,0.03)" vertical={false} />
              <XAxis
                dataKey="month"
                tick={(props: Record<string, unknown>) => {
                  const x = Number(props.x ?? 0)
                  const y = Number(props.y ?? 0)
                  const value = String((props.payload as Record<string, unknown>)?.value ?? "")
                  const isActive = value === selectedMonth
                  return (
                    <text
                      x={x}
                      y={y + 12}
                      textAnchor="middle"
                      fill={isActive ? "#22C55E" : "#64748b"}
                      fontSize={11}
                      fontWeight={isActive ? 600 : 400}
                    >
                      {`${parseInt(value.slice(5))}월`}
                    </text>
                  )
                }}
                axisLine={{ stroke: "rgba(255,255,255,0.06)" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: "#64748b", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v) => abbreviateAmount(v)}
                width={55}
              />
              <RechartsTooltip content={<ChartTooltipContent />} />
              {/* Net cashflow Area (behind bars) */}
              <Area
                type="monotone"
                dataKey="net"
                name="순현금흐름"
                fill="url(#netAreaGrad)"
                stroke="#F59E0B"
                strokeWidth={1.5}
                dot={(dotProps: Record<string, unknown>) => {
                  const cx = Number(dotProps.cx ?? 0)
                  const cy = Number(dotProps.cy ?? 0)
                  const dotPayload = dotProps.payload as Record<string, unknown> | undefined
                  if (dotPayload?.isSelected) {
                    return <circle cx={cx} cy={cy} r={4} fill="#F59E0B" stroke="#050508" strokeWidth={2} />
                  }
                  return <circle cx={cx} cy={cy} r={0} fill="none" />
                }}
                animationDuration={300}
              />
              {/* Income bars */}
              <Bar
                dataKey="income"
                name="입금"
                radius={[6, 6, 0, 0]}
                animationDuration={300}
                barSize={20}
              >
                {chartData.map((entry, index) => (
                  <Cell
                    key={`income-${index}`}
                    fill="url(#incomeBarGrad)"
                    stroke="#22C55E"
                    strokeWidth={entry.isSelected ? 1 : 0.5}
                    opacity={entry.isSelected ? 1 : 0.35}
                  />
                ))}
              </Bar>
              {/* Expense bars */}
              <Bar
                dataKey="expenseAbs"
                name="출금"
                radius={[6, 6, 0, 0]}
                animationDuration={300}
                barSize={20}
              >
                {chartData.map((entry, index) => (
                  <Cell
                    key={`expense-${index}`}
                    fill="url(#expenseBarGrad)"
                    stroke="#EF4444"
                    strokeWidth={entry.isSelected ? 1 : 0.5}
                    opacity={entry.isSelected ? 1 : 0.35}
                  />
                ))}
              </Bar>
              <Legend
                wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                formatter={(value: string) => <span style={{ color: "#94a3b8", fontSize: 11 }}>{value}</span>}
                iconType="circle"
                iconSize={8}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* Summary KPI Cards */}
      <div className="grid grid-cols-4 gap-3 max-md:grid-cols-2">
        <KPICard label="기초 잔고" value={formatByEntity(opening, entityId)} rawAmount={opening} entityId={entityId} />
        <KPICard
          label="총 입금"
          value={`+${formatByEntity(income, entityId)}`}
          rawAmount={income}
          entityId={entityId}
          colorClass="text-[hsl(var(--profit))]"
        />
        <KPICard
          label="총 출금"
          value={`-${formatByEntity(Math.abs(expense), entityId)}`}
          rawAmount={Math.abs(expense)}
          entityId={entityId}
          colorClass="text-[hsl(var(--loss))]"
        />
        <KPICard
          label="기말 잔고"
          value={formatByEntity(closing, entityId)}
          rawAmount={closing}
          entityId={entityId}
          subtext={`순 ${net >= 0 ? "+" : ""}${formatByEntity(net, entityId)}`}
          subtextColor={net >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}
        />
      </div>

      {/* Transaction List */}
      <Card className="overflow-hidden rounded-2xl">
        <div className="px-4 py-3 flex items-center justify-between border-b border-border">
          <h3 className="text-lg font-semibold">
            {selectedMonth && `${parseInt(selectedMonth.slice(5))}월 거래 내역`}
          </h3>
          <div className="flex items-center gap-1 bg-muted/30 rounded-lg p-0.5">
            <button
              onClick={() => setViewMode("time")}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors",
                viewMode === "time" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              )}
              aria-pressed={viewMode === "time"}
            >
              <List className="h-3.5 w-3.5" /> 시간순
            </button>
            <button
              onClick={() => setViewMode("account")}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors",
                viewMode === "account" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              )}
              aria-pressed={viewMode === "account"}
            >
              <FolderTree className="h-3.5 w-3.5" /> 계정별
            </button>
          </div>
        </div>
        {detailState === "loading" ? (
          <div className="p-4 space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : detailState === "empty" ? (
          <div className="p-8 text-center text-sm text-muted-foreground">
            해당 월에 거래가 없습니다.
          </div>
        ) : detail ? (
          viewMode === "time"
            ? <TransactionList rows={detail.rows} entityId={entityId} />
            : <AccountGroupedList rows={detail.rows} entityId={entityId} />
        ) : null}
      </Card>
    </div>
  )
}

// ── Transaction List with 5-column layout (mockup style) ──

function TransactionList({ rows, entityId }: { rows: ActualRow[]; entityId: string | null }) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const toggle = (txId: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(txId)) next.delete(txId)
      else next.add(txId)
      return next
    })
  }

  return (
    <div className="overflow-x-auto">
      {/* 5-column header: 날짜, 유형, 항목, 금액, 잔고 */}
      <div className="grid grid-cols-[90px_70px_1fr_120px_130px] px-4 py-2.5 bg-muted/30 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
        <span>날짜</span>
        <span>유형</span>
        <span>항목</span>
        <span className="text-right">금액</span>
        <span className="text-right">잔고</span>
      </div>

      {rows.map((row, i) => {
        const isOpening = row.type === "opening"
        const isClosing = row.type === "closing"
        const isSpecial = isOpening || isClosing
        const isCardPayment = row.type === "out" && row.description && /카드\(주\)|카드대금/.test(row.description)
        const isExpanded = row.tx_id ? expanded.has(row.tx_id) : false

        // Opening balance row
        if (isOpening) {
          return (
            <div
              key={`opening-${i}`}
              className="grid grid-cols-[90px_70px_1fr_120px_130px] px-4 py-3 font-semibold bg-green-500/[0.03] border-b border-border"
            >
              <span className="font-mono text-xs text-muted-foreground">{row.date?.slice(0, 10) ?? ""}</span>
              <span />
              <span>시작 잔고</span>
              <span className="text-right font-mono text-xs">--</span>
              <span className="text-right font-mono text-xs font-medium">{formatByEntity(row.balance, entityId)}</span>
            </div>
          )
        }

        // Closing balance row
        if (isClosing) {
          return (
            <div
              key={`closing-${i}`}
              className="grid grid-cols-[90px_70px_1fr_120px_130px] px-4 py-3 font-semibold bg-green-500/[0.03] border-t-2 border-t-green-500/15"
            >
              <span className="font-mono text-xs text-muted-foreground">{row.date?.slice(0, 10) ?? ""}</span>
              <span />
              <span className="font-bold">기말 잔고</span>
              <span className="text-right font-mono text-xs">--</span>
              <span className="text-right font-mono text-xs font-medium text-[hsl(var(--profit))]">{formatByEntity(row.balance, entityId)}</span>
            </div>
          )
        }

        // Card payment row (collapsible)
        if (isCardPayment) {
          return (
            <div key={`card-${row.tx_id ?? i}`}>
              <div
                className="grid grid-cols-[90px_70px_1fr_120px_130px] px-4 py-2.5 border-t border-border cursor-pointer hover:bg-white/[0.02] transition-colors"
                onClick={() => row.tx_id && toggle(row.tx_id)}
              >
                <span className="font-mono text-xs text-muted-foreground">{row.date?.slice(5) ?? ""}</span>
                <span><TypeBadge type={row.type} description={row.description} /></span>
                <span className="flex items-center gap-1">
                  <span className="truncate">{row.description}</span>
                  {isExpanded ? <ChevronUp className="h-3 w-3 text-muted-foreground flex-shrink-0" /> : <ChevronDown className="h-3 w-3 text-muted-foreground flex-shrink-0" />}
                </span>
                <span className={cn("text-right font-mono text-xs", row.type === "in" ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]")}>
                  {row.type === "in" ? "+" : "-"}{formatByEntity(Math.abs(row.amount), entityId)}
                </span>
                <span className="text-right font-mono text-xs font-medium">{formatByEntity(row.balance, entityId)}</span>
              </div>
              {/* Drilldown placeholder (future: member/account breakdown) */}
              {isExpanded && (
                <div className="border-t border-border/30">
                  <div className="grid grid-cols-[90px_70px_1fr_120px_130px] px-4 py-2 pl-7 bg-black/[0.12] text-xs text-muted-foreground">
                    <span />
                    <span />
                    <span>(카드 내역 상세는 비용 탭에서 확인)</span>
                    <span />
                    <span />
                  </div>
                </div>
              )}
            </div>
          )
        }

        // Normal transaction row
        return (
          <div
            key={`${row.tx_id ?? row.type}-${i}`}
            className="grid grid-cols-[90px_70px_1fr_120px_130px] px-4 py-2.5 border-t border-border hover:bg-white/[0.02] transition-colors text-[13px]"
          >
            <span className="font-mono text-xs text-muted-foreground">{row.date?.slice(5) ?? ""}</span>
            <span><TypeBadge type={row.type} description={row.description} /></span>
            <span className="truncate">{row.description}</span>
            <span className={cn("text-right font-mono text-xs", row.type === "in" ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]")}>
              {row.type === "in" ? "+" : "-"}{formatByEntity(Math.abs(row.amount), entityId)}
            </span>
            <span className="text-right font-mono text-xs font-medium">{formatByEntity(row.balance, entityId)}</span>
          </div>
        )
      })}
    </div>
  )
}

// ── Account Grouped View (입금/출금 트리) ──────────────

interface AccountGroup {
  accountName: string
  accountId: number | null
  rows: ActualRow[]
  total: number
}

function AccountGroupedList({ rows, entityId }: { rows: ActualRow[]; entityId: string | null }) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())

  const { incomeGroups, expenseGroups, totalIncome, totalExpense } = useMemo(() => {
    const incomeMap = new Map<string, AccountGroup>()
    const expenseMap = new Map<string, AccountGroup>()

    const txRows = rows.filter(r => r.type === "in" || r.type === "out")

    for (const row of txRows) {
      const key = row.internal_account_name ?? "미분류"
      const map = row.type === "in" ? incomeMap : expenseMap

      if (!map.has(key)) {
        map.set(key, { accountName: key, accountId: row.internal_account_id ?? null, rows: [], total: 0 })
      }
      const group = map.get(key)!
      group.rows.push(row)
      group.total += Math.abs(row.amount)
    }

    const sortGroups = (groups: AccountGroup[]) =>
      groups.sort((a, b) => {
        if (a.accountName === "미분류") return 1
        if (b.accountName === "미분류") return -1
        return b.total - a.total // 금액 큰 순
      })

    return {
      incomeGroups: sortGroups(Array.from(incomeMap.values()) as AccountGroup[]),
      expenseGroups: sortGroups(Array.from(expenseMap.values()) as AccountGroup[]),
      totalIncome: txRows.filter(r => r.type === "in").reduce((s, r) => s + r.amount, 0),
      totalExpense: txRows.filter(r => r.type === "out").reduce((s, r) => s + Math.abs(r.amount), 0),
    }
  }, [rows])

  const toggleGroup = (key: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const renderSection = (
    label: string,
    groups: AccountGroup[],
    sectionTotal: number,
    type: "in" | "out",
    colorClass: string,
    bgClass: string,
  ) => {
    const sectionKey = `section-${type}`
    const isSectionExpanded = !expandedGroups.has(sectionKey) // default expanded

    return (
      <div>
        {/* Section header */}
        <button
          onClick={() => toggleGroup(sectionKey)}
          className={cn("w-full flex items-center justify-between px-4 py-3 font-semibold border-t border-border", bgClass)}
          aria-expanded={isSectionExpanded}
        >
          <span className="flex items-center gap-2">
            {isSectionExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4 rotate-90" />}
            <span className={colorClass}>{label}</span>
            <span className="text-xs text-muted-foreground font-normal">({groups.length}개 계정)</span>
          </span>
          <span className={cn("font-mono tabular-nums text-sm", colorClass)}>
            {type === "in" ? "+" : "-"}{formatByEntity(sectionTotal, entityId)}
          </span>
        </button>

        {/* Account groups */}
        {isSectionExpanded && groups.map((group) => {
          const groupKey = `${type}-${group.accountName}`
          const isExpanded = expandedGroups.has(groupKey)
          const isUnmapped = group.accountName === "미분류"

          return (
            <div key={groupKey}>
              {/* Account row */}
              <button
                onClick={() => toggleGroup(groupKey)}
                className={cn(
                  "w-full grid grid-cols-[1fr_120px_60px] px-4 py-2.5 pl-8 border-t border-border/50 text-left hover:bg-white/[0.02] transition-colors text-[13px]",
                  isUnmapped && "bg-amber-500/[0.03]"
                )}
                aria-expanded={isExpanded}
                aria-label={`${group.accountName} ${isExpanded ? "접기" : "펼치기"}`}
              >
                <span className="flex items-center gap-2">
                  {isExpanded ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronUp className="h-3.5 w-3.5 text-muted-foreground rotate-90" />}
                  <span className={cn("font-medium", isUnmapped && "text-amber-400")}>{group.accountName}</span>
                  {isUnmapped && (
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0 bg-amber-500/12 text-amber-400">{group.rows.length}건</Badge>
                  )}
                </span>
                <span className={cn("text-right font-mono text-xs tabular-nums", colorClass)}>
                  {type === "in" ? "+" : "-"}{formatByEntity(group.total, entityId)}
                </span>
                <span className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                  {group.rows.length}건
                </span>
              </button>

              {/* Individual transactions */}
              {isExpanded && (
                <div className="bg-black/[0.06]">
                  {group.rows.map((row: ActualRow, i: number) => (
                    <div
                      key={`${row.tx_id ?? i}`}
                      className="grid grid-cols-[60px_1fr_120px] px-4 py-1.5 pl-14 border-t border-border/20 text-[12px]"
                    >
                      <span className="font-mono text-muted-foreground">{row.date?.slice(5) ?? ""}</span>
                      <span className="truncate text-muted-foreground">{row.description}</span>
                      <span className={cn("text-right font-mono tabular-nums", colorClass)}>
                        {type === "in" ? "+" : "-"}{formatByEntity(Math.abs(row.amount), entityId)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    )
  }

  // Opening / Closing balances from rows
  const openingRow = rows.find(r => r.type === "opening")
  const closingRow = rows.find(r => r.type === "closing")

  return (
    <div>
      {/* Opening balance */}
      {openingRow && (
        <div className="grid grid-cols-[1fr_130px] px-4 py-3 font-semibold bg-green-500/[0.03] border-b border-border">
          <span>시작 잔고</span>
          <span className="text-right font-mono text-xs font-medium">{formatByEntity(openingRow.balance, entityId)}</span>
        </div>
      )}

      {/* Income tree */}
      {incomeGroups.length > 0 && renderSection(
        "수입 (입금)", incomeGroups, totalIncome, "in",
        "text-[hsl(var(--profit))]", "bg-green-500/[0.02]"
      )}

      {/* Expense tree */}
      {expenseGroups.length > 0 && renderSection(
        "지출 (출금)", expenseGroups, totalExpense, "out",
        "text-[hsl(var(--loss))]", "bg-red-500/[0.02]"
      )}

      {/* Closing balance */}
      {closingRow && (
        <div className="grid grid-cols-[1fr_130px] px-4 py-3 font-bold bg-green-500/[0.03] border-t-2 border-t-green-500/15">
          <span>기말 잔고</span>
          <span className="text-right font-mono text-xs font-medium text-[hsl(var(--profit))]">{formatByEntity(closingRow.balance, entityId)}</span>
        </div>
      )}
    </div>
  )
}
