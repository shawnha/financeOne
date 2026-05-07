"use client"

import { useEffect, useState, useCallback } from "react"
import { useSearchParams } from "next/navigation"
import {
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  ComposedChart,
  Cell,
} from "recharts"
import { AlertCircle, RefreshCw, TrendingUp, FileBarChart, ArrowRight, ChevronDown, ChevronUp } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"

import { useGlobalMonth } from "@/hooks/use-global-month"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { fetchAPI } from "@/lib/api"
import { formatByEntity, abbreviateAmount } from "@/lib/format"
import { cn } from "@/lib/utils"
import { MonthPicker } from "@/components/month-picker"

interface NonOpTx {
  id: number
  date: string
  amount: number
  description: string
  counterparty: string | null
  transfer_memo: string | null
  internal_name: string | null
  std_code: string
  std_name: string
}

type GroupBy = "product" | "payee"

interface BreakdownRow {
  key: string
  count: number
  amount: number
}

interface BreakdownResponse {
  group_by: GroupBy
  rows: BreakdownRow[]
  others: { count: number; amount: number } | null
  total: { count: number; amount: number }
}

interface PnlSummary {
  year: number
  month: number
  revenue: number
  cogs: number
  gross_profit: number
  gross_margin_pct: number | null
  opex: number
  operating_profit: number
  operating_margin_pct: number | null
  non_op_income: number
  non_op_expense: number
  net_income: number
  net_margin_pct: number | null
  purchases_total: number
  sales_count: number
  purchases_count: number
  opex_breakdown: Array<{ code: string; name: string; count: number; amount: number }>
  non_op_expense_transactions: NonOpTx[]
}

interface MonthlyRow {
  month: string
  revenue: number
  cogs: number
  gross_profit: number
  gross_margin_pct: number | null
  opex: number
  operating_profit: number
  net_income: number
  purchases_total: number
  sales_count: number
  purchases_count: number
}

interface MonthlyData {
  months: MonthlyRow[]
  available_months: string[]
}

type LoadState = "loading" | "empty" | "error" | "success"

function KPICard({
  label,
  value,
  subtext,
  colorClass,
  subtextColor,
  large,
}: {
  label: string
  value: string
  subtext?: string
  colorClass?: string
  subtextColor?: string
  large?: boolean
}) {
  return (
    <Card className="bg-secondary rounded-xl p-4">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p
        className={cn(
          "font-bold font-mono tabular-nums mt-1 truncate",
          large ? "text-xl md:text-2xl lg:text-[28px]" : "text-base md:text-lg lg:text-[22px]",
          colorClass,
        )}
      >
        {value}
      </p>
      {subtext && <p className={cn("text-[11px] mt-0.5", subtextColor || "text-muted-foreground")}>{subtext}</p>}
    </Card>
  )
}

export function PnlContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const entityId = searchParams.get("entity")
  const [nonOpExpanded, setNonOpExpanded] = useState(false)
  const [revenueExpanded, setRevenueExpanded] = useState(false)
  const [revenueGroup, setRevenueGroup] = useState<GroupBy>("product")
  const [revenueData, setRevenueData] = useState<BreakdownResponse | null>(null)
  const [revenueLoading, setRevenueLoading] = useState(false)
  const [cogsExpanded, setCogsExpanded] = useState(false)
  const [cogsGroup, setCogsGroup] = useState<GroupBy>("product")
  const [cogsData, setCogsData] = useState<BreakdownResponse | null>(null)
  const [cogsLoading, setCogsLoading] = useState(false)
  const [purchasesExpanded, setPurchasesExpanded] = useState(false)
  const [purchasesGroup, setPurchasesGroup] = useState<GroupBy>("payee")
  const [purchasesData, setPurchasesData] = useState<BreakdownResponse | null>(null)
  const [purchasesLoading, setPurchasesLoading] = useState(false)
  const [summary, setSummary] = useState<PnlSummary | null>(null)
  const [monthly, setMonthly] = useState<MonthlyData | null>(null)
  const [state, setState] = useState<LoadState>("loading")
  const [error, setError] = useState("")
  const [globalMonth, setGlobalMonth] = useGlobalMonth()
  const [selectedMonth, setSelectedMonthLocal] = useState(globalMonth)
  const setSelectedMonth = useCallback(
    (m: string) => {
      setSelectedMonthLocal(m)
      setGlobalMonth(m)
    },
    [setGlobalMonth],
  )

  useEffect(() => setSelectedMonthLocal(globalMonth), [globalMonth])

  const fetchData = useCallback(async () => {
    if (!entityId) return
    setState("loading")
    try {
      const [m] = selectedMonth.split("-").map(Number)
      const monthData = await fetchAPI<MonthlyData>(
        `/pnl/monthly?entity_id=${entityId}&months=12`,
        { cache: "no-store" },
      )
      setMonthly(monthData)
      if (!monthData.available_months.length) {
        setState("empty")
        return
      }
      const useMonth = monthData.available_months.includes(selectedMonth)
        ? selectedMonth
        : monthData.available_months[monthData.available_months.length - 1]
      if (useMonth !== selectedMonth) setSelectedMonth(useMonth)
      const [y, mn] = useMonth.split("-").map(Number)
      const sumData = await fetchAPI<PnlSummary>(
        `/pnl/summary?entity_id=${entityId}&year=${y}&month=${mn}`,
        { cache: "no-store" },
      )
      setSummary(sumData)
      setState("success")
    } catch (err) {
      setError(err instanceof Error ? err.message : "데이터를 불러올 수 없습니다.")
      setState("error")
    }
  }, [entityId, selectedMonth]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // month 또는 entity 가 바뀌면 drilldown 캐시 무효화
  useEffect(() => {
    setRevenueData(null)
    setCogsData(null)
    setPurchasesData(null)
  }, [selectedMonth, entityId])

  const fetchBreakdown = useCallback(
    async (kind: "revenue" | "cogs" | "purchases", group: GroupBy) => {
      if (!entityId || !summary) return
      const setter =
        kind === "revenue" ? setRevenueData : kind === "cogs" ? setCogsData : setPurchasesData
      const loadSetter =
        kind === "revenue"
          ? setRevenueLoading
          : kind === "cogs"
          ? setCogsLoading
          : setPurchasesLoading
      const path =
        kind === "revenue"
          ? "revenue-breakdown"
          : kind === "cogs"
          ? "cogs-breakdown"
          : "purchases-breakdown"
      loadSetter(true)
      try {
        const data = await fetchAPI<BreakdownResponse>(
          `/pnl/${path}?entity_id=${entityId}&year=${summary.year}&month=${summary.month}&group_by=${group}&limit=20`,
          { cache: "no-store" },
        )
        setter(data)
      } catch {
        setter(null)
      } finally {
        loadSetter(false)
      }
    },
    [entityId, summary],
  )

  const toggleRevenue = useCallback(() => {
    const next = !revenueExpanded
    setRevenueExpanded(next)
    if (next && !revenueData) fetchBreakdown("revenue", revenueGroup)
  }, [revenueExpanded, revenueData, revenueGroup, fetchBreakdown])

  const toggleCogs = useCallback(() => {
    const next = !cogsExpanded
    setCogsExpanded(next)
    if (next && !cogsData) fetchBreakdown("cogs", cogsGroup)
  }, [cogsExpanded, cogsData, cogsGroup, fetchBreakdown])

  const togglePurchases = useCallback(() => {
    const next = !purchasesExpanded
    setPurchasesExpanded(next)
    if (next && !purchasesData) fetchBreakdown("purchases", purchasesGroup)
  }, [purchasesExpanded, purchasesData, purchasesGroup, fetchBreakdown])

  const switchRevenueGroup = useCallback(
    (g: GroupBy) => {
      setRevenueGroup(g)
      fetchBreakdown("revenue", g)
    },
    [fetchBreakdown],
  )

  const switchCogsGroup = useCallback(
    (g: GroupBy) => {
      setCogsGroup(g)
      fetchBreakdown("cogs", g)
    },
    [fetchBreakdown],
  )

  const switchPurchasesGroup = useCallback(
    (g: GroupBy) => {
      setPurchasesGroup(g)
      fetchBreakdown("purchases", g)
    },
    [fetchBreakdown],
  )

  if (!entityId) {
    return (
      <div className="p-6">
        <Skeleton className="h-[260px] w-full rounded-xl" />
      </div>
    )
  }

  if (state === "loading") {
    return (
      <div className="p-6 space-y-6">
        <div className="grid grid-cols-4 gap-3 max-md:grid-cols-2">
          {Array.from({ length: 7 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-[260px] w-full rounded-xl" />
      </div>
    )
  }

  if (state === "error") {
    return (
      <div className="p-6">
        <Card className="p-8 flex flex-col items-center justify-center text-center gap-4">
          <AlertCircle className="h-12 w-12 text-[hsl(var(--loss))]" />
          <p className="text-lg font-medium">데이터를 불러올 수 없습니다.</p>
          <p className="text-sm text-muted-foreground">{error}</p>
          <Button onClick={fetchData} variant="secondary" className="gap-2">
            <RefreshCw className="h-4 w-4" /> 다시 시도
          </Button>
        </Card>
      </div>
    )
  }

  if (state === "empty" || !summary || !monthly) {
    return (
      <div className="p-6">
        <Card className="p-12 flex flex-col items-center justify-center text-center gap-4">
          <FileBarChart className="h-12 w-12 text-muted-foreground" />
          <p className="text-lg font-medium">P&amp;L 데이터가 없습니다.</p>
          <p className="text-sm text-muted-foreground">
            매출관리/매입관리 xlsx 를 업로드하면 P&amp;L 이 자동 계산됩니다.
          </p>
          <Button asChild variant="secondary">
            <Link href="/upload">업로드 페이지로</Link>
          </Button>
        </Card>
      </div>
    )
  }

  const months = monthly.available_months
  const chartData = monthly.months.map((m) => ({
    ...m,
    isSelected: m.month === selectedMonth,
  }))

  const fmtPct = (v: number | null) => (v == null ? "-" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`)
  const profitColor = (v: number) =>
    v > 0 ? "text-[hsl(var(--profit))]" : v < 0 ? "text-[hsl(var(--loss))]" : "text-foreground"

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <FileBarChart className="h-5 w-5 text-[hsl(var(--accent))]" />
            P&amp;L
          </h1>
          <p className="text-xs text-muted-foreground mt-1">
            매출 = 도매 매출관리 (발생주의) · 매출원가 = 매출 row × 매입가 · OpEx = 거래내역 판관비
          </p>
        </div>
        <MonthPicker
          months={months}
          selected={selectedMonth}
          onSelect={setSelectedMonth}
          accentColor="hsl(var(--accent))"
        />
      </div>

      {/* Top KPIs — 매출 / 매출총이익 / 영업이익 / 순이익 */}
      <div className="grid grid-cols-4 gap-3 max-md:grid-cols-2">
        <KPICard
          label="매출"
          value={formatByEntity(summary.revenue, entityId)}
          subtext={`${summary.sales_count}건`}
          large
        />
        <KPICard
          label="매출총이익"
          value={formatByEntity(summary.gross_profit, entityId)}
          subtext={summary.gross_margin_pct != null ? `${fmtPct(summary.gross_margin_pct)} 마진` : undefined}
          colorClass={profitColor(summary.gross_profit)}
          subtextColor={summary.gross_profit >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}
          large
        />
        <KPICard
          label="영업이익"
          value={formatByEntity(summary.operating_profit, entityId)}
          subtext={
            summary.operating_margin_pct != null
              ? `${fmtPct(summary.operating_margin_pct)} 영업이익률`
              : undefined
          }
          colorClass={profitColor(summary.operating_profit)}
          subtextColor={
            summary.operating_profit >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"
          }
          large
        />
        <KPICard
          label="당기순이익"
          value={formatByEntity(summary.net_income, entityId)}
          subtext={summary.net_margin_pct != null ? fmtPct(summary.net_margin_pct) : undefined}
          colorClass={profitColor(summary.net_income)}
          subtextColor={
            summary.net_income >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"
          }
          large
        />
      </div>

      {/* Detail breakdown — 매출원가 / OpEx / 영업외 */}
      <div className="grid grid-cols-3 gap-3 max-md:grid-cols-1">
        <KPICard
          label="매출원가"
          value={`-${formatByEntity(summary.cogs, entityId)}`}
          subtext={`${summary.purchases_count}건 매입 ₩${summary.purchases_total.toLocaleString()}`}
          colorClass="text-[hsl(var(--loss))]"
        />
        <KPICard
          label="OpEx (판관비)"
          value={`-${formatByEntity(summary.opex, entityId)}`}
          subtext="OpEx 페이지 연결 →"
          colorClass="text-[hsl(var(--loss))]"
        />
        <KPICard
          label="영업외 (비용/수익)"
          value={`-${formatByEntity(summary.non_op_expense, entityId)} / +${formatByEntity(summary.non_op_income, entityId)}`}
          subtext={`순 ${summary.non_op_income - summary.non_op_expense >= 0 ? "+" : ""}${formatByEntity(summary.non_op_income - summary.non_op_expense, entityId)}`}
          colorClass="text-foreground"
        />
      </div>

      {/* Monthly chart — 매출 (bar) + 영업이익 (line) */}
      <Card className="p-6 rounded-2xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-muted-foreground">
            월별 매출 + 영업이익 ({monthly.months.length}개월)
          </h3>
        </div>
        <div className="h-[260px] max-md:h-[200px]">
          <ResponsiveContainer width="100%" height="100%" minWidth={0}>
            <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 5 }}>
              <defs>
                <linearGradient id="revBarGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity={0.6} />
                  <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="4 4" stroke="rgba(255,255,255,0.03)" vertical={false} />
              <XAxis
                dataKey="month"
                tick={{ fill: "#64748b", fontSize: 11 }}
                axisLine={{ stroke: "rgba(255,255,255,0.06)" }}
                tickLine={false}
                tickFormatter={(v) => `${parseInt(v.slice(5))}월`}
              />
              <YAxis
                tick={{ fill: "#64748b", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v) => abbreviateAmount(v)}
                width={60}
              />
              <RechartsTooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null
                  const data = payload[0].payload as MonthlyRow
                  return (
                    <div className="rounded-lg bg-popover border border-border px-3 py-2 shadow-lg text-xs">
                      <p className="text-muted-foreground mb-1">{label}</p>
                      <p className="font-mono tabular-nums">
                        매출: <span className="text-[hsl(var(--accent))]">{formatByEntity(data.revenue, entityId)}</span>
                      </p>
                      <p className="font-mono tabular-nums">
                        영업이익: <span className={profitColor(data.operating_profit)}>{formatByEntity(data.operating_profit, entityId)}</span>
                      </p>
                      <p className="font-mono tabular-nums">
                        순이익: <span className={profitColor(data.net_income)}>{formatByEntity(data.net_income, entityId)}</span>
                      </p>
                    </div>
                  )
                }}
              />
              <Bar dataKey="revenue" name="매출" radius={[6, 6, 0, 0]} barSize={26}>
                {chartData.map((entry, i) => (
                  <Cell
                    key={`rev-${i}`}
                    fill="url(#revBarGrad)"
                    stroke="hsl(var(--accent))"
                    strokeWidth={entry.isSelected ? 1 : 0.5}
                    opacity={entry.isSelected ? 1 : 0.4}
                    cursor="pointer"
                    onClick={() => setSelectedMonth(entry.month)}
                  />
                ))}
              </Bar>
              <Line
                type="monotone"
                dataKey="operating_profit"
                name="영업이익"
                stroke="#22C55E"
                strokeWidth={2}
                dot={{ r: 3, fill: "#22C55E" }}
              />
              <Line
                type="monotone"
                dataKey="net_income"
                name="순이익"
                stroke="#F59E0B"
                strokeWidth={2}
                strokeDasharray="4 4"
                dot={{ r: 2, fill: "#F59E0B" }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* 월별 매출 vs 매출원가 vs 매입 비교 */}
      <Card className="p-6 rounded-2xl">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <h3 className="text-sm font-medium text-muted-foreground">
            월별 매출 · 매출원가 · 매입 추이 ({monthly.months.length}개월)
          </h3>
          <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-3 h-3 rounded-sm bg-[hsl(var(--accent))]/60" /> 매출
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-3 h-3 rounded-sm bg-[hsl(var(--loss))]/50" /> 매출원가
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-3 h-3 rounded-sm bg-amber-500/60" /> 매입
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-3 h-0.5 bg-emerald-400" /> 매출총이익률 (우)
            </span>
          </div>
        </div>
        <div className="h-[260px] max-md:h-[200px]">
          <ResponsiveContainer width="100%" height="100%" minWidth={0}>
            <ComposedChart data={chartData} margin={{ top: 10, right: 50, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="4 4" stroke="rgba(255,255,255,0.03)" vertical={false} />
              <XAxis
                dataKey="month"
                tick={{ fill: "#64748b", fontSize: 11 }}
                axisLine={{ stroke: "rgba(255,255,255,0.06)" }}
                tickLine={false}
                tickFormatter={(v) => `${parseInt(v.slice(5))}월`}
              />
              <YAxis
                yAxisId="amount"
                tick={{ fill: "#64748b", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v) => abbreviateAmount(v)}
                width={60}
              />
              <YAxis
                yAxisId="pct"
                orientation="right"
                tick={{ fill: "#64748b", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v) => `${v.toFixed(0)}%`}
                width={40}
                domain={["auto", "auto"]}
              />
              <RechartsTooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null
                  const data = payload[0].payload as MonthlyRow
                  const cogsRatio = data.revenue > 0 ? (data.cogs / data.revenue) * 100 : 0
                  const purRatio = data.revenue > 0 ? (data.purchases_total / data.revenue) * 100 : 0
                  return (
                    <div className="rounded-lg bg-popover border border-border px-3 py-2 shadow-lg text-xs space-y-0.5 min-w-[200px]">
                      <p className="text-muted-foreground mb-1">{label}</p>
                      <p className="font-mono tabular-nums flex justify-between gap-4">
                        <span>매출 ({data.sales_count}건)</span>
                        <span className="text-[hsl(var(--accent))]">{formatByEntity(data.revenue, entityId)}</span>
                      </p>
                      <p className="font-mono tabular-nums flex justify-between gap-4">
                        <span>매출원가 ({cogsRatio.toFixed(1)}%)</span>
                        <span className="text-[hsl(var(--loss))]">-{formatByEntity(data.cogs, entityId)}</span>
                      </p>
                      <p className="font-mono tabular-nums flex justify-between gap-4">
                        <span>매입 ({data.purchases_count}건 · {purRatio.toFixed(1)}%)</span>
                        <span className="text-amber-400">{formatByEntity(data.purchases_total, entityId)}</span>
                      </p>
                      <div className="border-t border-border/40 my-1" />
                      <p className="font-mono tabular-nums flex justify-between gap-4">
                        <span>매출총이익</span>
                        <span className={profitColor(data.gross_profit)}>{formatByEntity(data.gross_profit, entityId)}</span>
                      </p>
                      <p className="font-mono tabular-nums flex justify-between gap-4">
                        <span>매출총이익률</span>
                        <span className="text-emerald-400">
                          {data.gross_margin_pct == null ? "-" : `${data.gross_margin_pct.toFixed(2)}%`}
                        </span>
                      </p>
                    </div>
                  )
                }}
              />
              <Bar yAxisId="amount" dataKey="revenue" name="매출" radius={[4, 4, 0, 0]} barSize={14}>
                {chartData.map((entry, i) => (
                  <Cell
                    key={`rev2-${i}`}
                    fill="hsl(var(--accent))"
                    fillOpacity={entry.isSelected ? 0.8 : 0.45}
                    cursor="pointer"
                    onClick={() => setSelectedMonth(entry.month)}
                  />
                ))}
              </Bar>
              <Bar yAxisId="amount" dataKey="cogs" name="매출원가" radius={[4, 4, 0, 0]} barSize={14}>
                {chartData.map((entry, i) => (
                  <Cell
                    key={`cogs-${i}`}
                    fill="hsl(var(--loss))"
                    fillOpacity={entry.isSelected ? 0.7 : 0.35}
                    cursor="pointer"
                    onClick={() => setSelectedMonth(entry.month)}
                  />
                ))}
              </Bar>
              <Bar yAxisId="amount" dataKey="purchases_total" name="매입" radius={[4, 4, 0, 0]} barSize={14}>
                {chartData.map((entry, i) => (
                  <Cell
                    key={`pur-${i}`}
                    fill="#F59E0B"
                    fillOpacity={entry.isSelected ? 0.8 : 0.4}
                    cursor="pointer"
                    onClick={() => setSelectedMonth(entry.month)}
                  />
                ))}
              </Bar>
              <Line
                yAxisId="pct"
                type="monotone"
                dataKey="gross_margin_pct"
                name="매출총이익률"
                stroke="#34D399"
                strokeWidth={2}
                dot={{ r: 3, fill: "#34D399" }}
                connectNulls
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* P&L 표 */}
      <Card className="overflow-hidden rounded-2xl">
        <div className="px-4 py-3 border-b border-border">
          <h3 className="text-base font-semibold">{summary.month}월 P&amp;L</h3>
        </div>
        <div className="divide-y divide-border/40">
          <PnlRow
            label="매출"
            value={summary.revenue}
            entityId={entityId}
            bold
            onClick={toggleRevenue}
            expandable
            expanded={revenueExpanded}
          />
          {revenueExpanded && (
            <BreakdownPanel
              data={revenueData}
              loading={revenueLoading}
              group={revenueGroup}
              onSwitch={switchRevenueGroup}
              entityId={entityId}
              accent="profit"
            />
          )}
          <PnlRow
            label="(-) 매출원가"
            value={-summary.cogs}
            entityId={entityId}
            indent
            onClick={toggleCogs}
            expandable
            expanded={cogsExpanded}
          />
          {cogsExpanded && (
            <BreakdownPanel
              data={cogsData}
              loading={cogsLoading}
              group={cogsGroup}
              onSwitch={switchCogsGroup}
              entityId={entityId}
              accent="loss"
              negative
            />
          )}
          <PnlRow label="매출총이익" value={summary.gross_profit} entityId={entityId} bold subtle pct={summary.gross_margin_pct} />
          <PnlRow
            label="(-) OpEx (판관비)"
            value={-summary.opex}
            entityId={entityId}
            indent
            onClick={() => router.push(`/opex?entity=${entityId}`)}
            actionHint="OpEx 페이지 →"
          />
          <PnlRow
            label="영업이익"
            value={summary.operating_profit}
            entityId={entityId}
            bold
            highlight
            pct={summary.operating_margin_pct}
          />
          <PnlRow label="(+) 영업외수익" value={summary.non_op_income} entityId={entityId} indent />
          <PnlRow
            label="(-) 영업외비용"
            value={-summary.non_op_expense}
            entityId={entityId}
            indent
            onClick={() =>
              summary.non_op_expense_transactions.length > 0 && setNonOpExpanded((v) => !v)
            }
            expandable={summary.non_op_expense_transactions.length > 0}
            expanded={nonOpExpanded}
          />
          {/* 영업외비용 drilldown */}
          {nonOpExpanded && summary.non_op_expense_transactions.length > 0 && (
            <div className="bg-black/[0.08]">
              <div className="grid grid-cols-[80px_120px_1fr_140px] px-4 py-2 pl-12 text-[10px] uppercase tracking-wider text-muted-foreground/70 font-semibold">
                <span>날짜</span>
                <span>표준계정</span>
                <span>거래</span>
                <span className="text-right">금액</span>
              </div>
              {summary.non_op_expense_transactions.map((tx) => (
                <div
                  key={tx.id}
                  className="grid grid-cols-[80px_120px_1fr_140px] px-4 py-1.5 pl-12 border-t border-border/20 text-[12px]"
                >
                  <span className="font-mono text-muted-foreground">{tx.date.slice(5)}</span>
                  <span className="text-muted-foreground truncate" title={tx.std_name}>
                    {tx.std_code} {tx.std_name}
                  </span>
                  <span className="truncate text-muted-foreground" title={tx.description}>
                    {tx.description}
                    {tx.counterparty && (
                      <span className="text-muted-foreground/50 ml-1.5">· {tx.counterparty}</span>
                    )}
                    {tx.transfer_memo && (
                      <span className="ml-1.5 text-[10px] text-blue-300/80 bg-blue-500/10 rounded px-1 py-0.5">
                        {tx.transfer_memo}
                      </span>
                    )}
                  </span>
                  <span className="text-right font-mono tabular-nums text-[hsl(var(--loss))]">
                    -{formatByEntity(tx.amount, entityId)}
                  </span>
                </div>
              ))}
            </div>
          )}
          <PnlRow
            label="당기순이익"
            value={summary.net_income}
            entityId={entityId}
            bold
            highlight
            pct={summary.net_margin_pct}
          />
        </div>
      </Card>

      {/* 매입 (도매) — 별도 분석 (P&L 표에 없음) */}
      <Card className="overflow-hidden rounded-2xl">
        <button
          type="button"
          onClick={togglePurchases}
          aria-expanded={purchasesExpanded}
          className="w-full px-4 py-3 border-b border-border/40 flex items-center justify-between hover:bg-white/[0.03] transition-colors"
        >
          <div className="text-left">
            <p className="text-base font-semibold flex items-center gap-1.5">
              매입 (도매)
              {purchasesExpanded ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronUp className="h-4 w-4 text-muted-foreground rotate-90" />
              )}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {summary.purchases_count}건 · 매입처별/제품별 분석
            </p>
          </div>
          <p className="text-base font-mono tabular-nums">
            {formatByEntity(summary.purchases_total, entityId)}
          </p>
        </button>
        {purchasesExpanded && (
          <BreakdownPanel
            data={purchasesData}
            loading={purchasesLoading}
            group={purchasesGroup}
            onSwitch={switchPurchasesGroup}
            entityId={entityId}
            accent="neutral"
            payeeLabel="매입처"
          />
        )}
      </Card>

      {/* OpEx breakdown link */}
      <Link
        href={`/opex?entity=${entityId}`}
        className="flex items-center justify-between p-4 rounded-xl bg-secondary/40 border border-border/40 hover:bg-secondary/60 transition-colors"
      >
        <div>
          <p className="text-sm font-medium">OpEx (판관비) 카테고리별 분석</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {summary.opex_breakdown.length}개 표준계정 · 인건비/임차료/교통/사무용품 등
          </p>
        </div>
        <ArrowRight className="h-5 w-5 text-muted-foreground" />
      </Link>
    </div>
  )
}

function PnlRow({
  label,
  value,
  entityId,
  bold,
  highlight,
  indent,
  subtle,
  pct,
  onClick,
  expandable,
  expanded,
  actionHint,
}: {
  label: string
  value: number
  entityId: string | null
  bold?: boolean
  highlight?: boolean
  indent?: boolean
  subtle?: boolean
  pct?: number | null
  onClick?: () => void
  expandable?: boolean
  expanded?: boolean
  actionHint?: string
}) {
  const isLoss = value < 0
  const isProfit = bold && value > 0
  const clickable = !!onClick
  const Comp: "button" | "div" = clickable ? "button" : "div"
  return (
    <Comp
      onClick={onClick}
      type={clickable ? ("button" as const) : undefined}
      aria-expanded={expandable ? expanded : undefined}
      className={cn(
        "w-full grid grid-cols-[1fr_auto_70px] gap-4 px-4 py-2.5 text-left",
        indent && "pl-10",
        highlight && "bg-accent/5",
        subtle && "bg-secondary/30",
        clickable && "hover:bg-white/[0.03] transition-colors cursor-pointer",
      )}
    >
      <span className={cn("text-sm flex items-center gap-1.5", bold && "font-semibold")}>
        {label}
        {expandable && (
          expanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          ) : (
            <ChevronUp className="h-3.5 w-3.5 text-muted-foreground rotate-90" />
          )
        )}
        {actionHint && !expandable && (
          <span className="text-[10px] text-muted-foreground/70 ml-1">{actionHint}</span>
        )}
      </span>
      <span
        className={cn(
          "text-right font-mono tabular-nums",
          bold ? "text-base" : "text-sm",
          isLoss && "text-[hsl(var(--loss))]",
          isProfit && "text-[hsl(var(--profit))]",
        )}
      >
        {value < 0 ? "-" : ""}
        {formatByEntity(Math.abs(value), entityId)}
      </span>
      <span className="text-right text-xs font-mono text-muted-foreground tabular-nums">
        {pct != null ? `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%` : ""}
      </span>
    </Comp>
  )
}

function BreakdownPanel({
  data,
  loading,
  group,
  onSwitch,
  entityId,
  accent,
  negative,
  payeeLabel = "거래처",
}: {
  data: BreakdownResponse | null
  loading: boolean
  group: GroupBy
  onSwitch: (g: GroupBy) => void
  entityId: string | null
  accent: "profit" | "loss" | "neutral"
  negative?: boolean
  payeeLabel?: string
}) {
  const accentClass =
    accent === "profit"
      ? "text-[hsl(var(--profit))]"
      : accent === "loss"
      ? "text-[hsl(var(--loss))]"
      : "text-foreground"

  const fmt = (v: number) => `${negative ? "-" : ""}${formatByEntity(v, entityId)}`

  const totalAmount = data?.total.amount ?? 0

  return (
    <div className="bg-black/[0.08]">
      {/* group toggle */}
      <div className="px-4 py-2 pl-12 flex items-center gap-1.5 border-b border-border/20">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground/70 font-semibold mr-2">
          기준
        </span>
        <button
          type="button"
          onClick={() => onSwitch("product")}
          className={cn(
            "text-[11px] px-2.5 py-1 rounded-md font-medium transition-colors",
            group === "product"
              ? "bg-accent/20 text-foreground"
              : "text-muted-foreground hover:text-foreground hover:bg-white/[0.04]",
          )}
        >
          제품별
        </button>
        <button
          type="button"
          onClick={() => onSwitch("payee")}
          className={cn(
            "text-[11px] px-2.5 py-1 rounded-md font-medium transition-colors",
            group === "payee"
              ? "bg-accent/20 text-foreground"
              : "text-muted-foreground hover:text-foreground hover:bg-white/[0.04]",
          )}
        >
          {payeeLabel}별
        </button>
        {data && (
          <span className="text-[10px] text-muted-foreground/60 ml-auto">
            top {data.rows.length}{data.others ? ` · 기타 ${data.others.count}` : ""} · 합 {data.total.count}건
          </span>
        )}
      </div>

      {loading || !data ? (
        <div className="px-4 py-6 pl-12 text-xs text-muted-foreground">
          불러오는 중…
        </div>
      ) : data.rows.length === 0 ? (
        <div className="px-4 py-6 pl-12 text-xs text-muted-foreground">
          데이터가 없습니다.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-[1fr_70px_140px_60px] px-4 py-2 pl-12 text-[10px] uppercase tracking-wider text-muted-foreground/70 font-semibold">
            <span>{group === "product" ? "제품" : payeeLabel}</span>
            <span className="text-right">건수</span>
            <span className="text-right">금액</span>
            <span className="text-right">비중</span>
          </div>
          {data.rows.map((row, idx) => {
            const pct = totalAmount > 0 ? (row.amount / totalAmount) * 100 : 0
            return (
              <div
                key={`${group}-${idx}-${row.key}`}
                className="grid grid-cols-[1fr_70px_140px_60px] px-4 py-1.5 pl-12 border-t border-border/20 text-[12px]"
              >
                <span className="truncate" title={row.key}>
                  <span className="text-muted-foreground/50 mr-1.5 font-mono tabular-nums">
                    {String(idx + 1).padStart(2, " ")}
                  </span>
                  {row.key}
                </span>
                <span className="text-right font-mono tabular-nums text-muted-foreground">
                  {row.count}
                </span>
                <span className={cn("text-right font-mono tabular-nums", accentClass)}>
                  {fmt(row.amount)}
                </span>
                <span className="text-right font-mono tabular-nums text-muted-foreground/70 text-[11px]">
                  {pct.toFixed(1)}%
                </span>
              </div>
            )
          })}
          {data.others && (
            <div className="grid grid-cols-[1fr_70px_140px_60px] px-4 py-1.5 pl-12 border-t border-border/20 text-[12px] text-muted-foreground/80">
              <span>기타 ({data.others.count}{group === "product" ? "개 제품" : "곳"})</span>
              <span className="text-right font-mono tabular-nums">{data.others.count}</span>
              <span className={cn("text-right font-mono tabular-nums", accentClass, "opacity-70")}>
                {fmt(data.others.amount)}
              </span>
              <span className="text-right font-mono tabular-nums text-muted-foreground/70 text-[11px]">
                {totalAmount > 0 ? ((data.others.amount / totalAmount) * 100).toFixed(1) : "0.0"}%
              </span>
            </div>
          )}
          <div className="grid grid-cols-[1fr_70px_140px_60px] px-4 py-2 pl-12 border-t border-border/40 bg-secondary/40 text-[12px] font-semibold">
            <span>합계</span>
            <span className="text-right font-mono tabular-nums">{data.total.count}</span>
            <span className={cn("text-right font-mono tabular-nums", accentClass)}>
              {fmt(data.total.amount)}
            </span>
            <span className="text-right font-mono tabular-nums text-muted-foreground/70">
              100%
            </span>
          </div>
        </>
      )}
    </div>
  )
}
