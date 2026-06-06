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
  ReferenceLine,
  Cell,
} from "recharts"
import { AlertCircle, ChevronLeft, ChevronRight, RefreshCw, TrendingDown } from "lucide-react"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { fetchAPI } from "@/lib/api"
import { formatByEntity, abbreviateAmount } from "@/lib/format"
import { cn } from "@/lib/utils"

interface ReceivableRow {
  canonical: string
  billed: number
  received: number
  outstanding: number
  sales_count: number
  receive_count: number
  collection_rate_pct: number | null
}

interface CollectionMethod {
  method: string
  amount: number
  count: number
  pct: number
}

interface ReceivablesSummary {
  entity_id: number
  total_billed: number
  total_received: number
  total_outstanding: number
  collection_rate_pct: number | null
  payee_count: number
  detail: ReceivableRow[]
  no_match_received: ReceivableRow[]
  collection_methods: CollectionMethod[]
}

interface MonthlyRow {
  month: string
  billed: number
  received: number
  monthly_diff: number
  cumulative_outstanding: number
  collection_rate_pct: number | null
}

interface MonthlyData {
  opening_balance?: number
  months: MonthlyRow[]
}

interface DailyRow {
  date: string
  billed: number
  received: number
  daily_diff: number
  cumulative_outstanding: number
  collection_rate_pct: number | null
}

interface DailyData {
  opening_balance?: number
  days: DailyRow[]
}

type LoadState = "loading" | "empty" | "error" | "success"

function KPICard({
  label, value, subtext, colorClass, large,
}: {
  label: string; value: string; subtext?: string; colorClass?: string; large?: boolean
}) {
  return (
    <Card className="bg-secondary rounded-xl p-4">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={cn(
        "font-bold font-mono tabular-nums mt-1 truncate",
        large ? "text-xl md:text-2xl lg:text-[28px]" : "text-base md:text-lg lg:text-[22px]",
        colorClass,
      )}>{value}</p>
      {subtext && <p className="text-[11px] mt-0.5 text-muted-foreground">{subtext}</p>}
    </Card>
  )
}

export function ReceivablesContent() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity")
  const [summary, setSummary] = useState<ReceivablesSummary | null>(null)
  const [monthly, setMonthly] = useState<MonthlyData | null>(null)
  const [state, setState] = useState<LoadState>("loading")
  const [error, setError] = useState("")
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null)  // 'YYYY-MM'
  const [daily, setDaily] = useState<DailyData | null>(null)
  const [dailyLoading, setDailyLoading] = useState(false)

  const fetchData = useCallback(async () => {
    if (!entityId) return
    setState("loading")
    try {
      const [s, m] = await Promise.all([
        fetchAPI<ReceivablesSummary>(`/receivables/summary?entity_id=${entityId}`, { cache: "no-store" }),
        fetchAPI<MonthlyData>(`/receivables/monthly?entity_id=${entityId}&months=12`, { cache: "no-store" }),
      ])
      setSummary(s)
      setMonthly(m)
      setState(s.payee_count === 0 ? "empty" : "success")
    } catch (err) {
      setError(err instanceof Error ? err.message : "데이터를 불러올 수 없습니다.")
      setState("error")
    }
  }, [entityId])

  useEffect(() => { fetchData() }, [fetchData])

  // 월별 데이터 로드 완료 시 마지막 월 자동 선택
  useEffect(() => {
    if (monthly && monthly.months.length > 0 && selectedMonth === null) {
      setSelectedMonth(monthly.months[monthly.months.length - 1].month)
    }
  }, [monthly, selectedMonth])

  // 선택 월 변경 시 일별 데이터 fetch
  useEffect(() => {
    if (!entityId || !selectedMonth) return
    setDailyLoading(true)
    const [y, m] = selectedMonth.split("-").map(Number)
    const startDate = `${y}-${String(m).padStart(2, "0")}-01`
    const lastDay = new Date(y, m, 0).getDate()
    const endDate = `${y}-${String(m).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`
    fetchAPI<DailyData>(
      `/receivables/daily?entity_id=${entityId}&start_date=${startDate}&end_date=${endDate}`,
      { cache: "no-store" },
    )
      .then(setDaily)
      .catch((e) => console.error("daily fetch failed", e))
      .finally(() => setDailyLoading(false))
  }, [entityId, selectedMonth])

  // ← / → keyboard nav
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!monthly || !selectedMonth) return
      const idx = monthly.months.findIndex((m) => m.month === selectedMonth)
      if (idx < 0) return
      if (e.key === "ArrowLeft" && idx > 0) {
        setSelectedMonth(monthly.months[idx - 1].month)
      } else if (e.key === "ArrowRight" && idx < monthly.months.length - 1) {
        setSelectedMonth(monthly.months[idx + 1].month)
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [monthly, selectedMonth])

  if (!entityId) {
    return <div className="p-6"><Skeleton className="h-[260px] w-full rounded-xl" /></div>
  }
  if (state === "loading") {
    return (
      <div className="p-6 space-y-6">
        <div className="grid grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}
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
        <Card className="p-12 text-center">
          <p className="text-lg font-medium">외상매출금 데이터가 없습니다.</p>
          <p className="text-sm text-muted-foreground mt-2">
            매출관리 (도매) xlsx 와 거래내역이 모두 적재되어야 외상매출금이 자동 계산됩니다.
          </p>
        </Card>
      </div>
    )
  }

  const overallRate = summary.collection_rate_pct ?? 0
  const rateColor = overallRate >= 70 ? "text-[hsl(var(--profit))]" : overallRate >= 40 ? "text-amber-300" : "text-[hsl(var(--loss))]"
  // 수금방식 분해가 있으면 도매(SIMS 코드 기준 수금) 법인
  const isWholesale = (summary.collection_methods?.length ?? 0) > 0
  const overpaid = isWholesale ? summary.detail.filter((r) => r.outstanding < 0) : []

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold flex items-center gap-2">
          <TrendingDown className="h-5 w-5 text-amber-400" />
          외상매출금
        </h1>
        <p className="text-xs text-muted-foreground mt-1">
          {isWholesale
            ? "매출관리 (발생주의) − SIMS 수금 (customer_collections, 거래처 코드 기준) + 2025 기초잔고"
            : "매출관리 (발생주의) − 거래내역 입금 (현금주의) — payee_aliases 매칭 base"}
        </p>
      </div>

      <div className="grid grid-cols-4 gap-3 max-md:grid-cols-2">
        <KPICard
          label="발생 매출 (누계)"
          value={formatByEntity(summary.total_billed, entityId)}
          subtext={`${summary.payee_count}개 거래처`}
          large
        />
        <KPICard
          label="회수 입금 (누계)"
          value={formatByEntity(summary.total_received, entityId)}
          subtext={overallRate ? `회수율 ${overallRate.toFixed(1)}%` : undefined}
          colorClass="text-[hsl(var(--profit))]"
          large
        />
        <KPICard
          label="외상매출금 (잔액)"
          value={formatByEntity(summary.total_outstanding, entityId)}
          subtext="발생 − 회수"
          colorClass="text-amber-300"
          large
        />
        <KPICard
          label="전체 회수율"
          value={`${overallRate.toFixed(1)}%`}
          subtext={overallRate >= 70 ? "양호" : overallRate >= 40 ? "주의" : isWholesale ? "낮음" : "낮음 — alias 부족 가능"}
          colorClass={rateColor}
          large
        />
      </div>

      {/* 월별 추이 */}
      <Card className="p-6 rounded-2xl">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <h3 className="text-sm font-medium text-muted-foreground">
            월별 발생 vs 회수 + 누적 외상매출금 ({monthly.months.length}개월)
          </h3>
          <div className="flex items-center gap-3 text-[11px] text-muted-foreground flex-wrap">
            <span className="flex items-center gap-1.5"><span className="inline-block w-3 h-3 rounded-sm bg-[hsl(var(--accent))]/60" /> 발생 (좌)</span>
            <span className="flex items-center gap-1.5"><span className="inline-block w-3 h-3 rounded-sm bg-emerald-500/60" /> 회수 (좌)</span>
            <span className="flex items-center gap-1.5"><span className="inline-block w-3 h-0.5 bg-amber-400" /> 누적 외상 (우)</span>
          </div>
        </div>
        <div className="h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={monthly.months} margin={{ top: 10, right: 50, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="4 4" stroke="rgba(255,255,255,0.03)" vertical={false} />
              <XAxis dataKey="month" tick={{ fill: "#64748b", fontSize: 11 }} axisLine={{ stroke: "rgba(255,255,255,0.06)" }} tickLine={false} tickFormatter={(v) => `${parseInt(v.slice(5))}월`} />
              <YAxis yAxisId="amount" tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v) => abbreviateAmount(v)} width={60} />
              <YAxis yAxisId="cum" orientation="right" tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v) => abbreviateAmount(v)} width={50} />
              <RechartsTooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null
                  const d = payload[0].payload as MonthlyRow
                  return (
                    <div className="rounded-lg bg-popover border border-border px-3 py-2 shadow-lg text-xs space-y-0.5">
                      <p className="text-muted-foreground mb-1">{label}</p>
                      <p className="font-mono tabular-nums">발생: <span className="text-[hsl(var(--accent))]">{formatByEntity(d.billed, entityId)}</span></p>
                      <p className="font-mono tabular-nums">회수: <span className="text-[hsl(var(--profit))]">{formatByEntity(d.received, entityId)}</span></p>
                      <p className="font-mono tabular-nums">월별 차이: <span className={d.monthly_diff > 0 ? "text-amber-300" : "text-[hsl(var(--profit))]"}>{d.monthly_diff > 0 ? "+" : ""}{formatByEntity(d.monthly_diff, entityId)}</span></p>
                      <p className="font-mono tabular-nums">누적 외상: <span className="text-amber-400">{formatByEntity(d.cumulative_outstanding, entityId)}</span></p>
                      {d.collection_rate_pct != null && (
                        <p className="font-mono tabular-nums">회수율: <span>{d.collection_rate_pct.toFixed(1)}%</span></p>
                      )}
                    </div>
                  )
                }}
              />
              <ReferenceLine yAxisId="amount" y={0} stroke="rgba(255,255,255,0.1)" />
              <Bar
                yAxisId="amount" dataKey="billed" name="발생"
                fill="hsl(var(--accent))" fillOpacity={0.5}
                radius={[4, 4, 0, 0]} barSize={16}
                onClick={(data) => setSelectedMonth((data as unknown as MonthlyRow).month)}
                cursor="pointer"
              >
                {monthly.months.map((m) => (
                  <Cell
                    key={m.month}
                    fillOpacity={m.month === selectedMonth ? 1 : 0.4}
                    stroke={m.month === selectedMonth ? "hsl(var(--accent))" : undefined}
                    strokeWidth={m.month === selectedMonth ? 2 : 0}
                  />
                ))}
              </Bar>
              <Bar
                yAxisId="amount" dataKey="received" name="회수"
                fill="#22C55E" fillOpacity={0.5}
                radius={[4, 4, 0, 0]} barSize={16}
                onClick={(data) => setSelectedMonth((data as unknown as MonthlyRow).month)}
                cursor="pointer"
              >
                {monthly.months.map((m) => (
                  <Cell
                    key={m.month}
                    fillOpacity={m.month === selectedMonth ? 1 : 0.4}
                  />
                ))}
              </Bar>
              <Line yAxisId="cum" type="monotone" dataKey="cumulative_outstanding" name="누적 외상" stroke="#F59E0B" strokeWidth={2.5} dot={{ r: 3, fill: "#F59E0B" }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* 수금방식 분해 + 과수금/선수금 (도매) */}
      {isWholesale && (
        <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
          <Card className="p-6 rounded-2xl">
            <h3 className="text-sm font-medium text-muted-foreground mb-4">수금방식 분해</h3>
            <div className="space-y-2.5">
              {summary.collection_methods.map((m) => (
                <div key={m.method} className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span>{m.method}</span>
                    <span className="font-mono tabular-nums text-muted-foreground">
                      {formatByEntity(m.amount, entityId)} · {m.count}건 · {m.pct.toFixed(1)}%
                    </span>
                  </div>
                  <div className="h-1.5 rounded-full bg-white/[0.04] overflow-hidden">
                    <div className="h-full rounded-full bg-emerald-500/60" style={{ width: `${Math.min(m.pct, 100)}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card className="p-6 rounded-2xl">
            <h3 className="text-sm font-medium text-muted-foreground mb-4">
              과수금 / 선수금 거래처 {overpaid.length > 0 && <span className="text-amber-300">({overpaid.length})</span>}
            </h3>
            {overpaid.length === 0 ? (
              <p className="text-xs text-muted-foreground leading-relaxed">
                현재 초과 수금(선수금) 거래처가 없습니다.<br />모든 거래처가 미수 또는 정산 완료 상태입니다.
              </p>
            ) : (
              <div className="space-y-1.5 text-[12px] max-h-[200px] overflow-y-auto">
                {overpaid
                  .slice()
                  .sort((a, b) => a.outstanding - b.outstanding)
                  .map((r, i) => (
                    <div key={i} className="grid grid-cols-[1fr_120px] gap-2">
                      <span className="truncate" title={r.canonical}>{r.canonical}</span>
                      <span className="text-right font-mono tabular-nums text-[hsl(var(--profit))]">
                        {formatByEntity(r.outstanding, entityId)}
                      </span>
                    </div>
                  ))}
              </div>
            )}
          </Card>
        </div>
      )}

      {/* 일별 차트 — 선택 월 기준 */}
      {selectedMonth && (
        <Card className="p-6 rounded-2xl">
          <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-medium text-muted-foreground">
                {parseInt(selectedMonth.slice(5))}월 일별 발생 vs 회수 + 누적
              </h3>
              <span className="text-[10px] text-muted-foreground/60">(막대 클릭 또는 ←/→ 키로 월 이동)</span>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                disabled={!monthly || monthly.months.findIndex((m) => m.month === selectedMonth) <= 0}
                onClick={() => {
                  if (!monthly) return
                  const idx = monthly.months.findIndex((m) => m.month === selectedMonth)
                  if (idx > 0) setSelectedMonth(monthly.months[idx - 1].month)
                }}
                className="h-7 px-2"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="text-xs font-mono text-muted-foreground tabular-nums w-20 text-center">
                {selectedMonth}
              </span>
              <Button
                variant="ghost"
                size="sm"
                disabled={!monthly || monthly.months.findIndex((m) => m.month === selectedMonth) >= (monthly.months.length - 1)}
                onClick={() => {
                  if (!monthly) return
                  const idx = monthly.months.findIndex((m) => m.month === selectedMonth)
                  if (idx >= 0 && idx < monthly.months.length - 1) setSelectedMonth(monthly.months[idx + 1].month)
                }}
                className="h-7 px-2"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <div className="h-[240px]">
            {dailyLoading ? (
              <Skeleton className="h-full w-full rounded-lg" />
            ) : daily && daily.days.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={daily.days} margin={{ top: 10, right: 50, left: 10, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="4 4" stroke="rgba(255,255,255,0.03)" vertical={false} />
                  <XAxis
                    dataKey="date" tick={{ fill: "#64748b", fontSize: 10 }}
                    axisLine={{ stroke: "rgba(255,255,255,0.06)" }} tickLine={false}
                    tickFormatter={(v) => v.slice(8)}
                  />
                  <YAxis yAxisId="amount" tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v) => abbreviateAmount(v)} width={60} />
                  <YAxis yAxisId="cum" orientation="right" tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v) => abbreviateAmount(v)} width={50} />
                  <RechartsTooltip
                    content={({ active, payload, label }) => {
                      if (!active || !payload?.length) return null
                      const d = payload[0].payload as DailyRow
                      return (
                        <div className="rounded-lg bg-popover border border-border px-3 py-2 shadow-lg text-xs space-y-0.5">
                          <p className="text-muted-foreground mb-1">{label}</p>
                          <p className="font-mono tabular-nums">발생: <span className="text-[hsl(var(--accent))]">{formatByEntity(d.billed, entityId)}</span></p>
                          <p className="font-mono tabular-nums">회수: <span className="text-[hsl(var(--profit))]">{formatByEntity(d.received, entityId)}</span></p>
                          <p className="font-mono tabular-nums">누적 외상: <span className="text-amber-400">{formatByEntity(d.cumulative_outstanding, entityId)}</span></p>
                        </div>
                      )
                    }}
                  />
                  <ReferenceLine yAxisId="amount" y={0} stroke="rgba(255,255,255,0.1)" />
                  <Bar yAxisId="amount" dataKey="billed" name="발생" fill="hsl(var(--accent))" fillOpacity={0.6} radius={[3, 3, 0, 0]} barSize={10} />
                  <Bar yAxisId="amount" dataKey="received" name="회수" fill="#22C55E" fillOpacity={0.6} radius={[3, 3, 0, 0]} barSize={10} />
                  <Line yAxisId="cum" type="monotone" dataKey="cumulative_outstanding" name="누적 외상" stroke="#F59E0B" strokeWidth={2} dot={{ r: 2.5, fill: "#F59E0B" }} />
                </ComposedChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-sm text-muted-foreground/60">
                {selectedMonth} 의 일별 데이터가 없습니다.
              </div>
            )}
          </div>
        </Card>
      )}

      {/* 거래처별 detail */}
      <Card className="overflow-hidden rounded-2xl">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <h3 className="text-base font-semibold">거래처별 외상매출금 (top {Math.min(50, summary.detail.length)})</h3>
          <p className="text-xs text-muted-foreground">총 {summary.detail.length}개 거래처</p>
        </div>
        <div className="grid grid-cols-[1fr_120px_120px_120px_70px] px-4 py-2 text-[10px] uppercase tracking-wider text-muted-foreground/70 font-semibold border-b border-border/40">
          <span>거래처</span>
          <span className="text-right">발생</span>
          <span className="text-right">회수</span>
          <span className="text-right">외상</span>
          <span className="text-right">회수율</span>
        </div>
        <div className="divide-y divide-border/20 max-h-[500px] overflow-y-auto">
          {summary.detail.slice(0, 50).map((r, i) => {
            const rate = r.collection_rate_pct ?? 0
            const rateColor = rate >= 70 ? "text-[hsl(var(--profit))]" : rate >= 40 ? "text-amber-300" : rate > 0 ? "text-[hsl(var(--loss))]" : "text-muted-foreground/50"
            return (
              <div key={i} className="grid grid-cols-[1fr_120px_120px_120px_70px] px-4 py-2 text-[12px] hover:bg-white/[0.02]">
                <span className="truncate" title={r.canonical}>
                  <span className="text-muted-foreground/50 mr-1.5 font-mono text-[10px]">{i + 1}</span>
                  {r.canonical}
                </span>
                <span className="text-right font-mono tabular-nums">{formatByEntity(r.billed, entityId)}</span>
                <span className="text-right font-mono tabular-nums text-[hsl(var(--profit))]">{formatByEntity(r.received, entityId)}</span>
                <span className="text-right font-mono tabular-nums text-amber-300">{formatByEntity(r.outstanding, entityId)}</span>
                <span className={cn("text-right font-mono tabular-nums", rateColor)}>{r.collection_rate_pct != null ? `${rate.toFixed(0)}%` : "-"}</span>
              </div>
            )
          })}
        </div>
      </Card>

      {summary.no_match_received.length > 0 && (
        <Card className="p-4 rounded-2xl border-amber-500/20 bg-amber-500/[0.04]">
          <h3 className="text-sm font-medium text-amber-300 mb-2">⚠️ alias 없는 입금 ({summary.no_match_received.length}건)</h3>
          <p className="text-xs text-muted-foreground mb-3">
            매출관리 거래처와 매칭 안 된 거래내역 입금. payee_aliases 추가 매칭 필요.
          </p>
          <div className="space-y-1 text-[12px]">
            {summary.no_match_received.slice(0, 10).map((r, i) => (
              <div key={i} className="grid grid-cols-[1fr_140px] gap-2">
                <span className="truncate">{r.canonical}</span>
                <span className="text-right font-mono tabular-nums">{formatByEntity(r.received, entityId)}</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
