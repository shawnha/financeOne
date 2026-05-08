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
  ReferenceLine,
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
  parent_account_name?: string | null
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

      {/* Daily Chart — 선택된 월의 일별 입금/출금 + 잔고 추이 */}
      {detail && detail.rows.length > 2 && (
        <DailyChart detail={detail} entityId={entityId} />
      )}

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

// ── Account Grouped View (입금/출금 → 중분류 → 소분류 트리) ──

interface ChildAccount {
  accountName: string
  rows: ActualRow[]
  total: number
}

interface ParentGroup {
  parentName: string
  children: ChildAccount[]
  total: number
  txCount: number
}

function AccountGroupedList({ rows, entityId }: { rows: ActualRow[]; entityId: string | null }) {
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set())

  const { incomeTree, expenseTree, totalIncome, totalExpense } = useMemo(() => {
    const txRows = rows.filter(r => r.type === "in" || r.type === "out")

    // Build: type → parentName → childName → rows
    const buildTree = (type: "in" | "out"): ParentGroup[] => {
      const filtered = txRows.filter(r => r.type === type)
      const parentMap = new Map<string, Map<string, ActualRow[]>>()

      for (const row of filtered) {
        const parentName = row.parent_account_name ?? row.internal_account_name ?? "미분류"
        const childName = row.parent_account_name ? (row.internal_account_name ?? "미분류") : "_self"

        if (!parentMap.has(parentName)) parentMap.set(parentName, new Map())
        const childMap = parentMap.get(parentName)!
        if (!childMap.has(childName)) childMap.set(childName, [])
        childMap.get(childName)!.push(row)
      }

      const groups: ParentGroup[] = []
      parentMap.forEach((childMap, parentName) => {
        const children: ChildAccount[] = []
        let groupTotal = 0
        let txCount = 0

        childMap.forEach((childRows, childName) => {
          const total = childRows.reduce((s, r) => s + Math.abs(r.amount), 0)
          children.push({ accountName: childName === "_self" ? parentName : childName, rows: childRows, total })
          groupTotal += total
          txCount += childRows.length
        })

        // Sort children by amount desc
        children.sort((a, b) => b.total - a.total)
        groups.push({ parentName, children, total: groupTotal, txCount })
      })

      // Sort: 미분류 last, rest by total desc
      groups.sort((a, b) => {
        if (a.parentName === "미분류") return 1
        if (b.parentName === "미분류") return -1
        return b.total - a.total
      })

      return groups
    }

    return {
      incomeTree: buildTree("in"),
      expenseTree: buildTree("out"),
      totalIncome: txRows.filter(r => r.type === "in").reduce((s, r) => s + r.amount, 0),
      totalExpense: txRows.filter(r => r.type === "out").reduce((s, r) => s + Math.abs(r.amount), 0),
    }
  }, [rows])

  const toggle = (key: string) => {
    setExpandedKeys(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const renderTree = (
    label: string,
    tree: ParentGroup[],
    sectionTotal: number,
    type: "in" | "out",
    color: string,
    bg: string,
  ) => {
    const sectionKey = `section-${type}`
    const sectionOpen = !expandedKeys.has(sectionKey) // default open

    return (
      <div>
        {/* L0: 수입/지출 섹션 헤더 */}
        <button
          onClick={() => toggle(sectionKey)}
          className={cn("w-full flex items-center justify-between px-4 py-3 font-semibold border-t border-border", bg)}
          aria-expanded={sectionOpen}
        >
          <span className="flex items-center gap-2">
            {sectionOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4 rotate-90" />}
            <span className={color}>{label}</span>
            <span className="text-xs text-muted-foreground font-normal">({tree.reduce((s, g) => s + g.txCount, 0)}건)</span>
          </span>
          <span className={cn("font-mono tabular-nums text-sm", color)}>
            {type === "in" ? "+" : "-"}{formatByEntity(sectionTotal, entityId)}
          </span>
        </button>

        {sectionOpen && tree.map((parent) => {
          const parentKey = `${type}-${parent.parentName}`
          const parentOpen = expandedKeys.has(parentKey)
          const isUnmapped = parent.parentName === "미분류"
          const hasMultipleChildren = parent.children.length > 1 || (parent.children.length === 1 && parent.children[0].accountName !== parent.parentName)

          return (
            <div key={parentKey}>
              {/* L1: 중분류 (매출, 인건비, ...) */}
              <button
                onClick={() => toggle(parentKey)}
                className={cn(
                  "w-full grid grid-cols-[1fr_130px_60px] px-4 py-2.5 pl-8 border-t border-border/50 text-left hover:bg-white/[0.02] transition-colors",
                  isUnmapped && "bg-amber-500/[0.03]"
                )}
                aria-expanded={parentOpen}
                aria-label={`${parent.parentName} ${parentOpen ? "접기" : "펼치기"}`}
              >
                <span className="flex items-center gap-2">
                  {hasMultipleChildren
                    ? (parentOpen ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronUp className="h-3.5 w-3.5 text-muted-foreground rotate-90" />)
                    : <span className="w-3.5" />}
                  <span className={cn("font-medium", isUnmapped && "text-amber-400")}>{parent.parentName}</span>
                </span>
                <span className={cn("text-right font-mono text-xs tabular-nums", color)}>
                  {type === "in" ? "+" : "-"}{formatByEntity(parent.total, entityId)}
                </span>
                <span className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                  {parent.txCount}건
                </span>
              </button>

              {/* L2: 소분류 (스마트스토어, 급여, ...) + 거래 */}
              {parentOpen && parent.children.map((child) => {
                const childKey = `${parentKey}-${child.accountName}`
                const childOpen = expandedKeys.has(childKey)

                return (
                  <div key={childKey}>
                    {/* L2 header — only show if different from parent */}
                    {child.accountName !== parent.parentName && (
                      <button
                        onClick={() => toggle(childKey)}
                        className="w-full grid grid-cols-[1fr_130px_60px] px-4 py-2 pl-14 border-t border-border/30 text-left hover:bg-white/[0.02] transition-colors text-[13px]"
                        aria-expanded={childOpen}
                      >
                        <span className="flex items-center gap-1.5">
                          {childOpen ? <ChevronDown className="h-3 w-3 text-muted-foreground" /> : <ChevronUp className="h-3 w-3 text-muted-foreground rotate-90" />}
                          <span className="text-muted-foreground">{child.accountName}</span>
                        </span>
                        <span className={cn("text-right font-mono text-xs tabular-nums", color)}>
                          {type === "in" ? "+" : "-"}{formatByEntity(child.total, entityId)}
                        </span>
                        <span className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                          {child.rows.length}건
                        </span>
                      </button>
                    )}

                    {/* L3: 개별 거래 */}
                    {(child.accountName === parent.parentName ? parentOpen : childOpen) && (
                      <div className="bg-black/[0.05]">
                        {child.rows.map((row: ActualRow, i: number) => (
                          <div
                            key={`${row.tx_id ?? i}`}
                            className={cn(
                              "grid grid-cols-[55px_1fr_120px] px-4 py-1.5 border-t border-border/15 text-[12px]",
                              child.accountName === parent.parentName ? "pl-14" : "pl-20"
                            )}
                          >
                            <span className="font-mono text-muted-foreground">{row.date?.slice(5) ?? ""}</span>
                            <span className="truncate text-muted-foreground">{row.description}</span>
                            <span className={cn("text-right font-mono tabular-nums", color)}>
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
        })}
      </div>
    )
  }

  const openingRow = rows.find(r => r.type === "opening")
  const closingRow = rows.find(r => r.type === "closing")

  return (
    <div>
      {openingRow && (
        <div className="grid grid-cols-[1fr_130px] px-4 py-3 font-semibold bg-green-500/[0.03] border-b border-border">
          <span>시작 잔고</span>
          <span className="text-right font-mono text-xs font-medium tabular-nums">{formatByEntity(openingRow.balance, entityId)}</span>
        </div>
      )}

      {incomeTree.length > 0 && renderTree("수입 (입금)", incomeTree, totalIncome, "in", "text-[hsl(var(--profit))]", "bg-green-500/[0.02]")}
      {expenseTree.length > 0 && renderTree("지출 (출금)", expenseTree, totalExpense, "out", "text-[hsl(var(--loss))]", "bg-red-500/[0.02]")}

      {closingRow && (
        <div className="grid grid-cols-[1fr_130px] px-4 py-3 font-bold bg-green-500/[0.03] border-t-2 border-t-green-500/15">
          <span>기말 잔고</span>
          <span className="text-right font-mono text-xs font-medium text-[hsl(var(--profit))] tabular-nums">{formatByEntity(closingRow.balance, entityId)}</span>
        </div>
      )}
    </div>
  )
}

// ── Daily Chart (선택된 월의 일별 추이) ─────────────────

function DailyTooltipContent({
  active,
  payload,
  month,
  entityId,
}: {
  active?: boolean
  payload?: Array<{ payload: DailyPoint }>
  month: number
  entityId: string | null
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="rounded-lg bg-popover border border-border px-3 py-2 shadow-lg text-xs space-y-0.5">
      <p className="text-muted-foreground mb-1">{month}월 {p.dayLabel}일</p>
      {p.hasTx ? (
        <>
          {p.income > 0 && (
            <p className="font-mono tabular-nums text-[hsl(var(--profit))]">
              입금: +{formatByEntity(p.income, entityId)}
            </p>
          )}
          {p.expense > 0 && (
            <p className="font-mono tabular-nums text-[hsl(var(--loss))]">
              출금: -{formatByEntity(p.expense, entityId)}
            </p>
          )}
        </>
      ) : (
        <p className="text-muted-foreground italic">거래 없음</p>
      )}
      <p className="font-mono tabular-nums text-amber-400 pt-0.5 border-t border-border/40 mt-1">
        잔고: {formatByEntity(p.balance, entityId)}
      </p>
    </div>
  )
}

interface DailyPoint {
  day: string
  dayLabel: number
  income: number
  expense: number
  balance: number
  hasTx: boolean
}

interface IntercompanyLoan {
  day: number
  amount: number
  description: string
}

function DailyChart({ detail, entityId }: { detail: ActualData; entityId: string | null }) {
  const dailyData = useMemo<DailyPoint[]>(() => {
    const txRows = detail.rows.filter((r) => r.type === "in" || r.type === "out")
    if (txRows.length === 0) return []

    // Group by date — sum income/expense, keep last balance of the day
    const dayMap = new Map<string, { income: number; expense: number; balance: number }>()
    for (const row of txRows) {
      if (!row.date) continue
      const day = row.date.slice(0, 10)
      const existing = dayMap.get(day) ?? { income: 0, expense: 0, balance: row.balance }
      if (row.type === "in") existing.income += row.amount
      else existing.expense += Math.abs(row.amount)
      existing.balance = row.balance // rows are chronological → last wins
      dayMap.set(day, existing)
    }

    // Gap-fill all days of month for continuous balance line
    const lastDay = new Date(detail.year, detail.month, 0).getDate()
    const filled: DailyPoint[] = []
    let prevBalance = detail.opening_balance
    for (let d = 1; d <= lastDay; d++) {
      const dayStr = `${detail.year}-${String(detail.month).padStart(2, "0")}-${String(d).padStart(2, "0")}`
      const found = dayMap.get(dayStr)
      if (found) {
        filled.push({ day: dayStr, dayLabel: d, ...found, hasTx: true })
        prevBalance = found.balance
      } else {
        filled.push({ day: dayStr, dayLabel: d, income: 0, expense: 0, balance: prevBalance, hasTx: false })
      }
    }
    return filled
  }, [detail])

  // 한아원코리아 차입금 식별 — internal_account_name='차입금' AND counterparty 가 한아원코리아 (개인 차입 제외)
  // counterparty 패턴: '주식회사 한아' (truncated) / '주식회사 한아원코리아' / '한아원코리아'
  const intercompanyLoans = useMemo<IntercompanyLoan[]>(() => {
    return detail.rows
      .filter(
        (r) =>
          r.type === "in" &&
          r.internal_account_name === "차입금" &&
          r.counterparty != null &&
          /주식회사\s*한아|한아원코리아/.test(r.counterparty),
      )
      .map((r) => ({
        day: parseInt((r.date ?? "").slice(8, 10)),
        amount: r.amount,
        description: r.description,
      }))
      .filter((l) => l.day >= 1 && l.day <= 31)
  }, [detail])

  const totalLoans = intercompanyLoans.reduce((s, l) => s + l.amount, 0)
  // 차입 이후 외상매출금 회수 (첫 차입 시점 ~ 월말)
  const firstLoanDay = intercompanyLoans.length > 0 ? Math.min(...intercompanyLoans.map((l) => l.day)) : null
  const postLoanReceipts = useMemo(() => {
    if (firstLoanDay == null) return 0
    return detail.rows
      .filter((r) => {
        if (r.type !== "in") return false
        if (!r.date) return false
        const d = parseInt(r.date.slice(8, 10))
        if (d < firstLoanDay) return false
        // 차입금 자체는 제외
        if (r.internal_account_name === "차입금") return false
        return true
      })
      .reduce((s, r) => s + r.amount, 0)
  }, [detail, firstLoanDay])

  if (dailyData.length === 0) return null

  return (
    <Card className="p-6 rounded-2xl">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h3 className="text-sm font-medium text-muted-foreground">
          {detail.month}월 일별 현금흐름 ({detail.year})
        </h3>
        <p className="text-[11px] text-muted-foreground">
          잔고 추이 + 일별 입금/출금
          {intercompanyLoans.length > 0 && (
            <span className="ml-2 text-violet-300">· 한아원코리아 차입 {intercompanyLoans.length}건</span>
          )}
        </p>
      </div>

      {intercompanyLoans.length > 0 && (
        <div className="grid grid-cols-3 gap-2 mb-4 max-md:grid-cols-1">
          <div className="rounded-lg bg-violet-500/[0.06] border border-violet-500/20 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-violet-300/80">한아원코리아 차입</p>
            <p className="text-base font-bold font-mono tabular-nums text-violet-200">
              {formatByEntity(totalLoans, entityId)}
            </p>
            <p className="text-[10px] text-muted-foreground mt-0.5">
              {intercompanyLoans.map((l) => `${l.day}일 ${formatByEntity(l.amount, entityId)}`).join(" · ")}
            </p>
          </div>
          <div className="rounded-lg bg-secondary/40 border border-border/40 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">차입 이후 입금 (차입금 제외)</p>
            <p className="text-base font-bold font-mono tabular-nums text-[hsl(var(--profit))]">
              +{formatByEntity(postLoanReceipts, entityId)}
            </p>
            <p className="text-[10px] text-muted-foreground mt-0.5">
              {firstLoanDay}일 ~ 월말
            </p>
          </div>
          <div className="rounded-lg bg-secondary/40 border border-border/40 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">차입 대비 입금 배수</p>
            <p className="text-base font-bold font-mono tabular-nums">
              {totalLoans > 0 ? `${(postLoanReceipts / totalLoans).toFixed(2)}x` : "-"}
            </p>
            <p className="text-[10px] text-muted-foreground mt-0.5">투입 자금 회전 효과</p>
          </div>
        </div>
      )}
      <div className="h-[220px] max-md:h-[180px]">
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <ComposedChart data={dailyData} margin={{ top: 20, right: 10, left: 10, bottom: 5 }}>
            <defs>
              <linearGradient id="incomeBarGradDaily" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#22C55E" stopOpacity={0.6} />
                <stop offset="100%" stopColor="#22C55E" stopOpacity={0.05} />
              </linearGradient>
              <linearGradient id="expenseBarGradDaily" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#EF4444" stopOpacity={0.6} />
                <stop offset="100%" stopColor="#EF4444" stopOpacity={0.05} />
              </linearGradient>
              <linearGradient id="balanceAreaGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#F59E0B" stopOpacity={0.25} />
                <stop offset="100%" stopColor="#F59E0B" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="4 4" stroke="rgba(255,255,255,0.03)" vertical={false} />
            <XAxis
              dataKey="dayLabel"
              tick={{ fill: "#64748b", fontSize: 10 }}
              axisLine={{ stroke: "rgba(255,255,255,0.06)" }}
              tickLine={false}
              interval={2}
              tickFormatter={(v) => `${v}`}
            />
            <YAxis
              yAxisId="amount"
              tick={{ fill: "#64748b", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) => abbreviateAmount(v)}
              width={55}
            />
            <YAxis
              yAxisId="balance"
              orientation="right"
              tick={{ fill: "#94a3b8", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) => abbreviateAmount(v)}
              width={55}
            />
            <RechartsTooltip content={<DailyTooltipContent month={detail.month} entityId={entityId} />} />
            {/* 한아원코리아 차입금 marker (vertical line) */}
            {intercompanyLoans.map((loan, i) => (
              <ReferenceLine
                key={`loan-${i}`}
                yAxisId="amount"
                x={loan.day}
                stroke="#a78bfa"
                strokeDasharray="4 4"
                strokeWidth={1.5}
                label={{
                  value: `차입 ${abbreviateAmount(loan.amount)}`,
                  position: "top",
                  fill: "#c4b5fd",
                  fontSize: 10,
                  fontWeight: 600,
                }}
              />
            ))}
            <Area
              yAxisId="balance"
              type="monotone"
              dataKey="balance"
              name="잔고"
              fill="url(#balanceAreaGrad)"
              stroke="#F59E0B"
              strokeWidth={1.5}
              dot={false}
              animationDuration={300}
            />
            <Bar yAxisId="amount" dataKey="income" name="입금" radius={[3, 3, 0, 0]} barSize={6} animationDuration={300}>
              {dailyData.map((_, i) => (
                <Cell key={`d-in-${i}`} fill="url(#incomeBarGradDaily)" stroke="#22C55E" strokeWidth={0.5} />
              ))}
            </Bar>
            <Bar yAxisId="amount" dataKey="expense" name="출금" radius={[3, 3, 0, 0]} barSize={6} animationDuration={300}>
              {dailyData.map((_, i) => (
                <Cell key={`d-out-${i}`} fill="url(#expenseBarGradDaily)" stroke="#EF4444" strokeWidth={0.5} />
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
  )
}
