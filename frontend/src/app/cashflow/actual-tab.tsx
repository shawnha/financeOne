"use client"

import { useEffect, useState, useCallback } from "react"
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
  Line,
  ComposedChart,
} from "recharts"
import { AlertCircle, RefreshCw, Upload, ChevronDown, ChevronUp, Download } from "lucide-react"
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
}

interface ActualData {
  year: number
  month: number
  opening_balance: number
  closing_balance: number
  rows: ActualRow[]
}

type LoadState = "loading" | "empty" | "error" | "success"

// ── KPI Card ───────────────────────────────────────────

function KPICard({
  label,
  value,
  subtext,
  colorClass,
}: {
  label: string
  value: string
  subtext?: string
  colorClass?: string
}) {
  return (
    <Card className="bg-secondary rounded-xl p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("text-2xl font-bold font-mono tabular-nums mt-1", colorClass)}>
        {value}
      </p>
      {subtext && <p className="text-xs text-muted-foreground mt-0.5">{subtext}</p>}
    </Card>
  )
}

// ── Type Badge ─────────────────────────────────────────

const TYPE_BADGES: Record<string, { label: string; className: string }> = {
  in: { label: "입금", className: "bg-green-500/12 text-green-400" },
  out: { label: "출금", className: "bg-red-500/12 text-red-400" },
  opening: { label: "", className: "" },
  closing: { label: "", className: "" },
}

function TypeBadge({ type, description }: { type: string; description: string }) {
  // Detect card payment from description
  if (type === "out" && /카드\(주\)|카드대금/.test(description)) {
    return <Badge variant="outline" className="text-xs px-2 py-0.5 bg-purple-500/12 text-purple-400">카드대금</Badge>
  }
  if (type === "out" && /선결제/.test(description)) {
    return <Badge variant="outline" className="text-xs px-2 py-0.5 bg-purple-500/12 text-purple-400">선결제</Badge>
  }
  const badge = TYPE_BADGES[type]
  if (!badge || !badge.label) return null
  return <Badge variant="outline" className={cn("text-xs px-2 py-0.5", badge.className)}>{badge.label}</Badge>
}

// ── Component ──────────────────────────────────────────

export function ActualTab({ entityId }: { entityId: string | null }) {
  const [summary, setSummary] = useState<SummaryData | null>(null)
  const [detail, setDetail] = useState<ActualData | null>(null)
  const [state, setState] = useState<LoadState>("loading")
  const [detailState, setDetailState] = useState<LoadState>("loading")
  const [error, setError] = useState("")
  const [selectedMonth, setSelectedMonth] = useState("")

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
      // Default to latest month
      if (!selectedMonth || !data.available_months.includes(selectedMonth)) {
        setSelectedMonth(data.available_months[data.available_months.length - 1])
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
    barOpacity: m.month === selectedMonth ? 1 : 0.35,
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

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-3 max-md:grid-cols-2">
        <KPICard label="기초 잔고" value={formatByEntity(opening, entityId)} />
        <KPICard label="입금" value={formatByEntity(income, entityId)} colorClass="text-[hsl(var(--profit))]" />
        <KPICard label="출금" value={formatByEntity(expense, entityId)} colorClass="text-[hsl(var(--loss))]" />
        <KPICard
          label="기말 잔고"
          value={formatByEntity(closing, entityId)}
          subtext={`순 ${net >= 0 ? "+" : ""}${formatByEntity(net, entityId)}`}
        />
      </div>

      {/* Chart */}
      <Card className="p-4">
        <div className="h-[300px] max-md:h-[250px] max-sm:h-[200px]">
          <ResponsiveContainer width="100%" height="100%" minWidth={0}>
            <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 5 }}>
              <defs>
                <linearGradient id="incomeBarGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#22C55E" stopOpacity={0.9} />
                  <stop offset="100%" stopColor="#22C55E" stopOpacity={0.3} />
                </linearGradient>
                <linearGradient id="expenseBarGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#EF4444" stopOpacity={0.9} />
                  <stop offset="100%" stopColor="#EF4444" stopOpacity={0.3} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
              <XAxis
                dataKey="month"
                tick={{ fill: "hsl(220, 9%, 46%)", fontSize: 12 }}
                axisLine={{ stroke: "#334155" }}
                tickLine={false}
                tickFormatter={(v) => `${parseInt(v.slice(5))}월`}
              />
              <YAxis
                tick={{ fill: "hsl(220, 9%, 46%)", fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v) => abbreviateAmount(v)}
              />
              <RechartsTooltip content={<ChartTooltipContent />} />
              <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
              <Bar
                dataKey="income"
                name="입금"
                fill="url(#incomeBarGrad)"
                radius={[4, 4, 0, 0]}
                animationDuration={300}
              />
              <Bar
                dataKey="expense"
                name="출금"
                fill="url(#expenseBarGrad)"
                radius={[4, 4, 0, 0]}
                animationDuration={300}
              />
              <Line
                type="monotone"
                dataKey="net"
                name="순현금흐름"
                stroke="#F59E0B"
                strokeWidth={2}
                dot={false}
                animationDuration={300}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* Transaction List */}
      <Card className="overflow-hidden">
        <div className="px-4 py-3 flex items-center justify-between border-b border-border">
          <h3 className="text-sm font-semibold">
            {selectedMonth && `${parseInt(selectedMonth.slice(5))}월 거래 내역`}
          </h3>
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
          <TransactionList rows={detail.rows} entityId={entityId} />
        ) : null}
      </Card>
    </div>
  )
}

// ── Transaction List with Drilldown ────────────────────

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
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-muted/30 text-xs text-muted-foreground">
            <th className="text-left px-4 py-2 w-[100px]">날짜</th>
            <th className="text-left px-4 py-2">거래 내용</th>
            <th className="text-right px-4 py-2 w-[120px]">입금</th>
            <th className="text-right px-4 py-2 w-[120px]">출금</th>
            <th className="text-right px-4 py-2 w-[120px] max-md:hidden">잔고</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const isSpecial = row.type === "opening" || row.type === "closing"
            const isCardPayment = row.type === "out" && row.description && /카드\(주\)|카드대금/.test(row.description)

            return (
              <tr
                key={`${row.tx_id ?? row.type}-${i}`}
                className={cn(
                  "border-t border-border transition-colors",
                  isSpecial && row.type === "opening" && "bg-green-500/3",
                  isSpecial && row.type === "closing" && "border-t-2 border-t-[hsl(var(--profit))]",
                  !isSpecial && "hover:bg-muted/10",
                )}
              >
                <td className="px-4 py-2.5 font-mono text-xs">
                  {row.date ? row.date.slice(5) : ""}
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <TypeBadge type={row.type} description={row.description} />
                    <span className={cn(
                      "truncate",
                      isSpecial && "font-medium",
                    )}>
                      {row.description}
                    </span>
                    {isCardPayment && (
                      <button
                        onClick={() => row.tx_id && toggle(row.tx_id)}
                        className="ml-auto text-muted-foreground hover:text-foreground transition-colors"
                        aria-expanded={row.tx_id ? expanded.has(row.tx_id) : false}
                        aria-label="드릴다운 토글"
                      >
                        {row.tx_id && expanded.has(row.tx_id) ? (
                          <ChevronUp className="h-4 w-4" />
                        ) : (
                          <ChevronDown className="h-4 w-4" />
                        )}
                      </button>
                    )}
                  </div>
                </td>
                <td className="px-4 py-2.5 text-right font-mono tabular-nums text-[hsl(var(--profit))]">
                  {row.type === "in" ? formatByEntity(row.amount, entityId) : ""}
                </td>
                <td className="px-4 py-2.5 text-right font-mono tabular-nums text-[hsl(var(--loss))]">
                  {row.type === "out" ? formatByEntity(row.amount, entityId) : ""}
                </td>
                <td className="px-4 py-2.5 text-right font-mono tabular-nums max-md:hidden">
                  {formatByEntity(row.balance, entityId)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
