"use client"

import React, { useEffect, useState, useCallback, useMemo, useRef } from "react"
import { useGlobalMonth } from "@/hooks/use-global-month"
import Link from "next/link"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Label,
} from "recharts"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import { fetchAPI } from "@/lib/api"
import { formatByEntity } from "@/lib/format"
import { AlertCircle, RefreshCw, Plus, Download, Trash2, Pencil, ChevronRight, ChevronDown, Link2, AlertTriangle, TrendingDown, TrendingUp } from "lucide-react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { MonthPicker } from "@/components/month-picker"
import { AccountCombobox } from "@/components/account-combobox"

// ── Types ──────────────────────────────────────────────

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
  internal_account_parent_id: number | null
  parent_account_name: string | null
  actual_from_transactions: number | null
  expected_day: number | null
  payment_method: string
}

interface TreeNode {
  item: ForecastItem
  children: TreeNode[]
  /** Sum of children forecast_amounts (only used when children exist) */
  childrenSum: number
  childrenActualSum: number | null
  depth: number
}

interface CardTiming {
  prev_month_card: number
  curr_month_card_actual: number
  curr_month_card_estimate: number
  adjustment: number
}

interface CardSetting {
  source_type: string
  card_name: string
  payment_day: number
}

interface DailyPoint {
  day: number
  balance: number
  events: Array<{ name: string; amount: number; type: string }>
}

interface DailyAlert {
  day: number
  deficit: number
  message: string
}

interface DailyScheduleData {
  year: number
  month: number
  entity_id: number
  opening_balance: number
  points: DailyPoint[]
  alerts: DailyAlert[]
  card_settings: CardSetting[]
  min_balance_threshold: number
}

interface ForecastData {
  year: number
  month: number
  entity_id: number
  opening_balance: number
  forecast_income: number
  forecast_expense: number
  forecast_card_usage: number
  card_timing: CardTiming
  card_settings: CardSetting[]
  forecast_closing: number
  adjusted_forecast_closing: number
  actual_income: number
  actual_expense: number
  actual_closing: number
  diff: number
  actual_daily_points: Array<{ day: number; balance: number }>
  last_actual_day: number
  items: ForecastItem[]
  unmapped_income: number
  unmapped_expense: number
  unmapped_count: number
  warnings: string[]
  over_budget: Array<{
    category: string
    internal_account_id: number
    forecast: number
    actual: number
    diff_pct: number
  }>
}

interface SummaryMonth {
  month: string
  opening_balance: number
  closing_balance: number
}

interface SummaryData {
  months: SummaryMonth[]
  available_months: string[]
}

interface VarianceDriver {
  account_name: string
  internal_account_id: number | null
  amount: number
  tx_count: number
  forecasted: boolean
  forecast_amount: number | null
}

interface VarianceBucket {
  name: string
  amount: number
  detail: string
  drivers?: VarianceDriver[]
}

interface VarianceData {
  year: number
  month: number
  entity_id: number
  forecast_closing: number
  actual_closing: number
  total_diff: number
  buckets: VarianceBucket[]
  data_quality: {
    unmapped_count: number
    missing_snapshots: number
    missing_card_settings: number
    unresolved_forecasts: number
    high_unexplained_variance: boolean
  }
}

type LoadState = "loading" | "empty" | "error" | "success"


// ── KPI Card ───────────────────────────────────────────

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
      const eased = 1 - Math.pow(1 - progress, 3) // ease-out cubic
      setCurrent(target * eased)
      if (progress < 1) rafRef.current = requestAnimationFrame(animate)
    }
    rafRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(rafRef.current)
  }, [target, duration])

  return current
}

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
      <p className={cn("text-lg md:text-xl lg:text-[28px] font-bold font-mono tabular-nums mt-1 truncate", colorClass)}>{displayValue}</p>
      {subtext && <p className={cn("text-[11px] mt-0.5", subtextColor || "text-muted-foreground")}>{subtext}</p>}
    </Card>
  )
}

// ── Card color mapping (DESIGN-3) ────────────────────
const CARD_COLORS: Record<string, { stroke: string; fill: string; label: string }> = {
  lotte_card: { stroke: "#f87171", fill: "rgba(248,113,113,0.3)", label: "롯데 결제일" },
  woori_card: { stroke: "#60a5fa", fill: "rgba(96,165,250,0.3)", label: "우리 결제일" },
}
const DEFAULT_CARD_COLOR = { stroke: "#8B5CF6", fill: "rgba(139,92,246,0.3)", label: "카드 결제일" }

// ── Forecast Balance Chart (daily-schedule API) ──────

// ── Variance Bridge ──────────────────────────────────

function VarianceBridge({ entityId, year, month }: { entityId: string | null; year: number; month: number }) {
  const [data, setData] = useState<VarianceData | null>(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [expandedBucket, setExpandedBucket] = useState<string | null>(null)

  const fetchVariance = useCallback(async () => {
    if (!entityId) return
    setLoading(true)
    try {
      const res = await fetchAPI<VarianceData>(
        `/cashflow/variance?entity_id=${entityId}&year=${year}&month=${month}`,
      )
      setData(res)
    } catch {
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [entityId, year, month])

  useEffect(() => {
    if (open && !data) fetchVariance()
  }, [open, data, fetchVariance])

  // Reset data when month changes
  useEffect(() => {
    setData(null)
  }, [year, month])

  if (!entityId) return null

  const dqIssues = data ? [
    data.data_quality.unmapped_count > 0 && `미매핑 거래 ${data.data_quality.unmapped_count}건`,
    data.data_quality.missing_snapshots > 0 && `기초잔고 스냅샷 누락 ${data.data_quality.missing_snapshots}건`,
    data.data_quality.missing_card_settings > 0 && `카드 설정 미등록 ${data.data_quality.missing_card_settings}건`,
    data.data_quality.unresolved_forecasts > 0 && `예상 항목 미반영 ${data.data_quality.unresolved_forecasts}건`,
    data.data_quality.high_unexplained_variance && "설명 안 되는 잔차가 큼",
  ].filter(Boolean) as string[] : []

  const maxBucketAbs = data ? Math.max(...data.buckets.map(b => Math.abs(b.amount)), 1) : 1

  return (
    <Card className="rounded-2xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-muted/30 transition-colors"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2">
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          <h3 className="text-lg font-semibold">차이 분석</h3>
          {dqIssues.length > 0 && (
            <Badge variant="outline" className="text-amber-400 border-amber-500/30 text-[10px]">
              {dqIssues.length}건 주의
            </Badge>
          )}
        </div>
        {data && (
          <span className={cn("text-sm font-mono tabular-nums", data.total_diff >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]")}>
            {data.total_diff >= 0 ? "+" : ""}{formatByEntity(data.total_diff, entityId)}
          </span>
        )}
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-4 border-t border-border pt-4">
          {loading && (
            <div className="space-y-2">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          )}

          {!loading && data && (
            <>
              {/* Waterfall — horizontal flow */}
              <div className="space-y-1">
                {/* Start → End summary */}
                <div className="flex items-center justify-between text-xs text-muted-foreground mb-2">
                  <span>예상 기말 <span className="text-foreground font-medium">{formatByEntity(data.forecast_closing, entityId)}</span></span>
                  <span>실제 기말 <span className="text-foreground font-medium">{formatByEntity(data.actual_closing, entityId)}</span></span>
                </div>
                {/* Bucket bars */}
                {data.buckets.filter(b => Math.abs(b.amount) >= 1).map((bucket, i) => {
                  const barWidth = Math.min(100, Math.abs(bucket.amount) / maxBucketAbs * 100)
                  const isPositive = bucket.amount >= 0
                  return (
                    <div key={i} className="grid grid-cols-[120px_1fr_100px] items-center gap-2 h-8">
                      <span className="text-xs text-muted-foreground text-right truncate">{bucket.name}</span>
                      <div className="flex items-center h-full">
                        {isPositive ? (
                          <div className="flex items-center h-full w-full">
                            <div className="w-1/2" />
                            <div className="h-5 rounded-r-sm bg-[hsl(var(--profit))]" style={{ width: `${barWidth / 2}%` }} />
                          </div>
                        ) : (
                          <div className="flex items-center justify-end h-full w-full">
                            <div className="h-5 rounded-l-sm bg-[hsl(var(--loss))]" style={{ width: `${barWidth / 2}%` }} />
                            <div className="w-1/2" />
                          </div>
                        )}
                      </div>
                      <span className={cn("text-xs font-mono tabular-nums text-right", isPositive ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]")}>
                        {isPositive ? "+" : ""}{formatByEntity(bucket.amount, entityId)}
                      </span>
                    </div>
                  )
                })}
                {/* Center line label */}
                <div className="grid grid-cols-[120px_1fr_100px] items-center gap-2 mt-1">
                  <span />
                  <div className="flex justify-center">
                    <span className="text-[10px] text-muted-foreground/50">← 감소 | 증가 →</span>
                  </div>
                  <span />
                </div>
              </div>

              {/* Driver Table */}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-muted/30 text-[10px] text-muted-foreground uppercase tracking-wider">
                      <th className="text-left px-3 py-2">버킷</th>
                      <th className="text-left px-3 py-2">설명</th>
                      <th className="text-right px-3 py-2">금액</th>
                      <th className="text-right px-3 py-2">비중</th>
                      <th className="w-24 px-3 py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.buckets.filter(b => Math.abs(b.amount) >= 1).map((bucket, i) => {
                      const pct = data.total_diff !== 0 ? Math.abs(bucket.amount / data.total_diff * 100) : 0
                      const barWidth = Math.min(100, Math.abs(bucket.amount) / maxBucketAbs * 100)
                      const hasDrivers = bucket.drivers && bucket.drivers.length > 0
                      const isExpanded = expandedBucket === bucket.name
                      return (
                        <React.Fragment key={i}>
                          <tr
                            className={cn("border-t border-border/50 hover:bg-muted/20", hasDrivers && "cursor-pointer")}
                            onClick={() => hasDrivers && setExpandedBucket(isExpanded ? null : bucket.name)}
                          >
                            <td className="px-3 py-2 font-medium">
                              <span className="flex items-center gap-1">
                                {hasDrivers && (isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />)}
                                {bucket.name}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-muted-foreground text-xs max-w-[200px] truncate">{bucket.detail}</td>
                            <td className={cn("px-3 py-2 text-right font-mono tabular-nums", bucket.amount >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]")}>
                              {bucket.amount >= 0 ? "+" : ""}{formatByEntity(bucket.amount, entityId)}
                            </td>
                            <td className="px-3 py-2 text-right text-xs text-muted-foreground">{pct.toFixed(0)}%</td>
                            <td className="px-3 py-2">
                              <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                                <div
                                  className={cn("h-full rounded-full", bucket.amount >= 0 ? "bg-[hsl(var(--profit))]" : "bg-[hsl(var(--loss))]")}
                                  style={{ width: `${barWidth}%` }}
                                />
                              </div>
                            </td>
                          </tr>
                          {isExpanded && bucket.drivers && (() => {
                            const unforecasted = bucket.drivers.filter(d => !d.forecasted)
                            const forecasted = bucket.drivers.filter(d => d.forecasted)
                            return (
                              <>
                                {/* 예상에 없음 */}
                                {unforecasted.length > 0 && (
                                  <>
                                    <tr className="bg-[hsl(var(--loss))]/5">
                                      <td colSpan={5} className="pl-8 pr-3 py-1.5 text-xs font-semibold text-[hsl(var(--loss))]">
                                        예상에 없음 ({unforecasted.length}건, 합계 {formatByEntity(unforecasted.reduce((s, d) => s + d.amount, 0), entityId)})
                                      </td>
                                    </tr>
                                    {unforecasted.map((driver, j) => (
                                      <tr key={`u-${j}`} className="bg-[hsl(var(--loss))]/5">
                                        <td className="pl-10 pr-3 py-1 text-xs text-[hsl(var(--loss))]">✗ {driver.account_name}</td>
                                        <td className="px-3 py-1 text-xs text-muted-foreground">{driver.tx_count}건</td>
                                        <td className="px-3 py-1 text-right text-xs font-mono tabular-nums text-[hsl(var(--loss))]">
                                          {formatByEntity(driver.amount, entityId)}
                                        </td>
                                        <td colSpan={2} />
                                      </tr>
                                    ))}
                                  </>
                                )}
                                {/* 예상에 있음 */}
                                {forecasted.length > 0 && (
                                  <>
                                    <tr className="bg-muted/10">
                                      <td colSpan={5} className="pl-8 pr-3 py-1.5 text-xs font-semibold text-muted-foreground">
                                        예상에 있음 ({forecasted.length}건)
                                      </td>
                                    </tr>
                                    {forecasted.map((driver, j) => {
                                      const diff = driver.forecast_amount != null ? driver.amount - driver.forecast_amount : null
                                      return (
                                        <tr key={`f-${j}`} className="bg-muted/5">
                                          <td className="pl-10 pr-3 py-1 text-xs text-muted-foreground">{driver.account_name}</td>
                                          <td className="px-3 py-1 text-xs text-muted-foreground">
                                            예상 {driver.forecast_amount != null ? formatByEntity(driver.forecast_amount, entityId) : "-"}
                                          </td>
                                          <td className="px-3 py-1 text-right text-xs font-mono tabular-nums text-muted-foreground">
                                            {formatByEntity(driver.amount, entityId)}
                                          </td>
                                          <td className="px-3 py-1 text-right text-xs font-mono tabular-nums" colSpan={2}>
                                            {diff != null && Math.abs(diff) >= 1 && (
                                              <span className={diff > 0 ? "text-[hsl(var(--loss))]" : "text-[hsl(var(--profit))]"}>
                                                {diff > 0 ? "+" : ""}{formatByEntity(diff, entityId)}
                                              </span>
                                            )}
                                          </td>
                                        </tr>
                                      )
                                    })}
                                  </>
                                )}
                              </>
                            )
                          })()}
                        </React.Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* Data Quality */}
              {dqIssues.length > 0 && (
                <div className="bg-amber-500/[0.06] border border-amber-500/15 rounded-lg px-4 py-3">
                  <div className="flex items-center gap-2 mb-2">
                    <AlertTriangle className="h-4 w-4 text-amber-400" />
                    <span className="text-xs font-semibold text-amber-400">데이터 품질</span>
                  </div>
                  <div className="space-y-1">
                    {dqIssues.map((issue, i) => (
                      <p key={i} className="text-xs text-amber-300/80">{issue}</p>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </Card>
  )
}


function ForecastBalanceChart({
  schedule,
  forecastData,
  entityId,
  month,
}: {
  schedule: DailyScheduleData | null
  forecastData: ForecastData
  entityId: string | null
  month: number
}) {
  const chartData = useMemo(() => {
    if (!schedule) return null

    // Build actual balance lookup from daily points (step chart)
    const actualBalanceByDay = new Map<number, number>()
    if (forecastData.actual_daily_points?.length) {
      // Fill forward: each day keeps the last known balance
      let lastBal = forecastData.opening_balance
      for (const pt of forecastData.actual_daily_points) {
        lastBal = pt.balance
        actualBalanceByDay.set(pt.day, lastBal)
      }
      // Fill forward for intermediate days
      let prev = forecastData.opening_balance
      for (let d = 1; d <= schedule.points.length; d++) {
        if (actualBalanceByDay.has(d)) {
          prev = actualBalanceByDay.get(d)!
        } else if (d <= forecastData.last_actual_day) {
          actualBalanceByDay.set(d, prev)
        }
      }
    }

    // Calculate adjusted forecast: apply unmapped impact proportionally on unmapped tx dates
    // Simple approach: distribute unmapped net evenly across the schedule
    const unmappedNet = (forecastData.unmapped_income ?? 0) - (forecastData.unmapped_expense ?? 0)

    const points = schedule.points.map((p) => ({
      day: `${month}/${p.day}`,
      originalEstimated: p.balance,
      estimated: p.balance + (unmappedNet * p.day / schedule.points.length),
      actual: p.day <= forecastData.last_actual_day
        ? (actualBalanceByDay.get(p.day) ?? null)
        : null,
      events: p.events,
    }))

    return { points, daysInMonth: schedule.points.length, cardSettings: schedule.card_settings }
  }, [schedule, forecastData, month])

  if (!chartData) return <Skeleton className="h-[220px] rounded-2xl" />

  const fmt = (v: number) => {
    if (Math.abs(v) >= 1_000_000) return `₩${(v / 1_000_000).toFixed(0)}M`
    if (Math.abs(v) >= 1_000) return `₩${(v / 1_000).toFixed(0)}K`
    return `₩${v}`
  }

  return (
    <Card className="bg-secondary rounded-2xl p-6">
      <ResponsiveContainer width="100%" height={250} minWidth={0}>
        <ComposedChart data={chartData.points} margin={{ top: 28, right: 20, left: 10, bottom: 5 }}>
          <defs>
            <linearGradient id="forecastEstGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#F59E0B" stopOpacity={0.15} />
              <stop offset="100%" stopColor="#F59E0B" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="forecastActGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#22C55E" stopOpacity={0.15} />
              <stop offset="100%" stopColor="#22C55E" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="4 4" stroke="rgba(255,255,255,0.03)" vertical={false} />
          <XAxis
            dataKey="day"
            tick={{ fontSize: 10, fill: "#64748b" }}
            tickLine={false}
            axisLine={{ stroke: "rgba(255,255,255,0.06)" }}
            interval={Math.max(1, Math.floor(chartData.daysInMonth / 5))}
          />
          <YAxis
            tick={{ fontSize: 10, fill: "#64748b" }}
            tickLine={false}
            axisLine={false}
            tickFormatter={fmt}
            width={60}
          />
          <Tooltip
            contentStyle={{ background: "#161b22", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: "#94a3b8" }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null
              const point = payload[0]?.payload
              return (
                <div className="bg-[#161b22] border border-white/10 rounded-lg p-3 text-xs">
                  <p className="text-muted-foreground mb-1">{label}</p>
                  <p className="text-[#F59E0B]">조정 예상: ₩{point?.estimated?.toLocaleString()}</p>
                  {point?.originalEstimated != null && point.originalEstimated !== point.estimated && (
                    <p className="text-[#71717a]">원래 예상: ₩{point.originalEstimated.toLocaleString()}</p>
                  )}
                  {point?.actual != null && <p className="text-[#22C55E]">실제: ₩{point.actual.toLocaleString()}</p>}
                  {point?.events?.length > 0 && (
                    <div className="mt-1 pt-1 border-t border-white/10">
                      {point.events.map((e: { name: string; amount: number; type: string }, i: number) => (
                        <p key={i} className={e.type === "out" ? "text-red-400" : "text-green-400"}>
                          {e.type === "out" ? "-" : "+"}{e.name}: ₩{Math.round(e.amount).toLocaleString()}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              )
            }}
          />
          {/* Card payment day markers (DESIGN-3) */}
          {chartData.cardSettings.map((card) => {
            const color = CARD_COLORS[card.source_type] || DEFAULT_CARD_COLOR
            const day = `${month}/${Math.min(card.payment_day, chartData.daysInMonth)}`
            return (
              <ReferenceLine
                key={card.source_type}
                x={day}
                stroke={color.stroke}
                strokeDasharray="3 3"
                strokeWidth={1}
              >
                <Label
                  value={color.label}
                  position="top"
                  fill={color.stroke}
                  fontSize={9}
                  fontWeight={500}
                  className="hidden sm:block"
                />
              </ReferenceLine>
            )
          })}
          {/* Min balance threshold line */}
          <ReferenceLine
            y={0}
            stroke="rgba(239,68,68,0.3)"
            strokeDasharray="6 3"
            strokeWidth={1}
          />
          {/* Original forecast (thin gray dashed line — reference only) */}
          <Line
            type="monotone"
            dataKey="originalEstimated"
            stroke="#71717a"
            strokeWidth={1.2}
            strokeDasharray="6 4"
            strokeOpacity={0.4}
            dot={false}
            activeDot={false}
          />
          {/* Adjusted forecast (amber area + dashed border) */}
          <Area
            type="monotone"
            dataKey="estimated"
            fill="url(#forecastEstGrad)"
            stroke="#F59E0B"
            strokeWidth={1.8}
            strokeDasharray="6 4"
            strokeOpacity={0.6}
            dot={(props: { cx?: number; cy?: number; payload?: { events?: Array<{ name: string; type: string }> } }) => {
              const { cx, cy, payload } = props
              if (!payload?.events?.length || !cx || !cy) return <g />
              const label = payload.events.map((e) => e.name).join(", ")
              return (
                <g>
                  <circle cx={cx} cy={cy} r={3.5} fill="#F59E0B" stroke="#050508" strokeWidth={1.5} />
                  <text x={cx} y={cy - 10} textAnchor="middle" fill="#F59E0B" fontSize={8} fontWeight={500}>
                    {label.length > 12 ? label.slice(0, 12) + "…" : label}
                  </text>
                </g>
              )
            }}
            activeDot={{ r: 4, fill: "#F59E0B", stroke: "#050508", strokeWidth: 2 }}
          />
          {/* Actual balance (green solid line, smooth, stops at last upload day) */}
          <Line
            type="monotone"
            dataKey="actual"
            stroke="#22C55E"
            strokeWidth={2.5}
            dot={false}
            activeDot={{ r: 4, fill: "#22C55E", stroke: "#050508", strokeWidth: 2 }}
            connectNulls={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="flex flex-wrap gap-5 mt-2 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-4 h-0.5 bg-[#22C55E] rounded" />
          실제 잔고
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-4 h-2 rounded-sm" style={{ background: "linear-gradient(180deg, rgba(245,158,11,0.25), rgba(245,158,11,0.03))", borderTop: "1.5px dashed #F59E0B" }} />
          조정 예상 (미분류 반영)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-4 h-0 border-t border-dashed" style={{ borderColor: "rgba(113,113,122,0.4)" }} />
          원래 예상
        </span>
        {chartData.cardSettings.map((card) => {
          const color = CARD_COLORS[card.source_type] || DEFAULT_CARD_COLOR
          return (
            <span key={card.source_type} className="flex items-center gap-1.5">
              <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: color.stroke }} />
              {card.card_name} ({card.payment_day}일)
            </span>
          )
        })}
      </div>
    </Card>
  )
}

// ── Forecast Input Modal ───────────────────────────────

interface InternalAccount {
  id: number
  code: string
  name: string
  parent_id: number | null
  is_recurring?: boolean
}

function ForecastModal({
  entityId,
  year,
  month,
  onSaved,
  editItem,
  open: controlledOpen,
  onOpenChange: controlledOnOpenChange,
}: {
  entityId: string
  year: number
  month: number
  onSaved: () => void
  editItem?: ForecastItem | null
  open?: boolean
  onOpenChange?: (open: boolean) => void
}) {
  const [internalOpen, setInternalOpen] = useState(false)
  const open = controlledOpen ?? internalOpen
  const setOpen = controlledOnOpenChange ?? setInternalOpen

  const isEdit = !!editItem
  const [type, setType] = useState<"in" | "out">(editItem?.type as "in" | "out" || "in")
  const [category, setCategory] = useState(editItem?.category || "")
  const [selectedAccountId, setSelectedAccountId] = useState(editItem?.internal_account_id ? String(editItem.internal_account_id) : "")
  const [internalAccounts, setInternalAccounts] = useState<InternalAccount[]>([])
  const [amount, setAmount] = useState(editItem ? String(editItem.forecast_amount) : "")
  const [recurring, setRecurring] = useState(editItem?.is_recurring || false)
  const [expectedDay, setExpectedDay] = useState(editItem?.expected_day ? String(editItem.expected_day) : "")
  const [paymentMethod, setPaymentMethod] = useState<"bank" | "card">((editItem?.payment_method as "bank" | "card") || "bank")
  const [saving, setSaving] = useState(false)

  // Sync state when editItem changes
  useEffect(() => {
    if (editItem) {
      setType(editItem.type as "in" | "out")
      setCategory(editItem.category || "")
      setSelectedAccountId(editItem.internal_account_id ? String(editItem.internal_account_id) : "")
      setAmount(editItem.forecast_amount.toLocaleString())
      setRecurring(editItem.is_recurring)
      setExpectedDay(editItem.expected_day ? String(editItem.expected_day) : "")
      setPaymentMethod((editItem.payment_method as "bank" | "card") || "bank")
    }
  }, [editItem])

  // Fetch internal accounts on mount
  useEffect(() => {
    if (!entityId) return
    fetchAPI<InternalAccount[]>(
      `/accounts/internal?entity_id=${entityId}`,
      { cache: "no-store" },
    ).then(setInternalAccounts).catch(() => {})
  }, [entityId])

  const selectedAccount = internalAccounts.find((a) => String(a.id) === selectedAccountId)

  // 전월 실적 조회 (suggest-from-actuals는 내부적으로 전월 계산)
  const [prevActual, setPrevActual] = useState<number | null>(null)
  const [prevSuggestions, setPrevSuggestions] = useState<Array<{ internal_account_id: number; total: number; type: string }>>([])
  useEffect(() => {
    if (!entityId || isEdit) return
    fetchAPI<{ suggestions: Array<{ internal_account_id: number; total: number; type: string }> }>(
      `/forecasts/suggest-from-actuals?entity_id=${entityId}&year=${year}&month=${month}`,
    ).then((data) => {
      setPrevSuggestions(data.suggestions || [])
    }).catch(() => setPrevSuggestions([]))
  }, [entityId, year, month, isEdit])

  // 선택된 계정의 전월 실적 (상위 항목이면 하위 합산)
  const childAccounts = useMemo(() => {
    if (!selectedAccountId) return []
    return internalAccounts.filter(a => a.parent_id === Number(selectedAccountId))
  }, [selectedAccountId, internalAccounts])

  const isParentAccount = childAccounts.length > 0

  useEffect(() => {
    if (!selectedAccountId || isEdit) { setPrevActual(null); return }
    if (isParentAccount) {
      // Sum children's prev actuals
      const childIds = new Set(childAccounts.map(c => c.id))
      const childTotal = prevSuggestions
        .filter(s => childIds.has(s.internal_account_id))
        .reduce((sum, s) => sum + s.total, 0)
      setPrevActual(childTotal > 0 ? childTotal : null)
    } else {
      const match = prevSuggestions.find((s) => String(s.internal_account_id) === selectedAccountId)
      setPrevActual(match ? match.total : null)
    }
  }, [selectedAccountId, prevSuggestions, isEdit, isParentAccount, childAccounts])

  const resetForm = () => {
    setCategory("")
    setSelectedAccountId("")
    setAmount("")
    setRecurring(false)
    setExpectedDay("")
    setPaymentMethod("bank")
  }

  const handleSave = async () => {
    if ((!category && !selectedAccountId) || !amount) return
    setSaving(true)
    try {
      if (isEdit && editItem) {
        await fetchAPI(`/forecasts/${editItem.id}`, {
          method: "PUT",
          body: JSON.stringify({
            type,
            forecast_amount: Number(amount.replace(/,/g, "")),
            is_recurring: recurring,
            expected_day: expectedDay ? Number(expectedDay) : null,
            payment_method: paymentMethod,
          }),
        })
      } else if (isParentAccount && childAccounts.length > 0) {
        // 상위 항목 선택 → 하위 항목들을 각각 자동 생성
        const totalAmount = Number(amount.replace(/,/g, ""))
        for (const child of childAccounts) {
          // 하위 계정별 전월 실적 비율로 금액 분배
          const childPrev = prevSuggestions.find(s => s.internal_account_id === child.id)
          const childAmount = prevActual && prevActual > 0 && childPrev
            ? Math.round(totalAmount * (childPrev.total / prevActual))
            : Math.round(totalAmount / childAccounts.length)
          await fetchAPI("/forecasts", {
            method: "POST",
            body: JSON.stringify({
              entity_id: Number(entityId),
              year,
              month,
              category: child.name,
              type,
              forecast_amount: childAmount,
              is_recurring: recurring,
              internal_account_id: child.id,
              expected_day: expectedDay ? Number(expectedDay) : null,
              payment_method: paymentMethod,
            }),
          })
        }
        toast.success(`${childAccounts.length}개 하위 항목이 자동 생성되었습니다`)
      } else {
        await fetchAPI("/forecasts", {
          method: "POST",
          body: JSON.stringify({
            entity_id: Number(entityId),
            year,
            month,
            category: selectedAccount?.name ?? category,
            type,
            forecast_amount: Number(amount.replace(/,/g, "")),
            is_recurring: recurring,
            internal_account_id: selectedAccountId ? Number(selectedAccountId) : null,
            expected_day: expectedDay ? Number(expectedDay) : null,
            payment_method: paymentMethod,
          }),
        })
      }
      setOpen(false)
      if (!isEdit) resetForm()
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v && !isEdit) resetForm() }}>
      {!isEdit && (
        <DialogTrigger asChild>
          <Button variant="outline" size="sm" className="gap-2">
            <Plus className="h-4 w-4" /> 항목 추가
          </Button>
        </DialogTrigger>
      )}
      <DialogContent className="max-w-[400px]">
        <DialogHeader>
          <DialogTitle>{isEdit ? "예상 항목 수정" : "예상 항목 추가"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 mt-2">
          <div>
            <label className="text-xs text-muted-foreground">월</label>
            <p className="font-medium">{year}년 {month}월</p>
          </div>
          {isEdit ? (
            <div>
              <label className="text-xs text-muted-foreground">항목</label>
              <p className="font-medium mt-1">
                <Badge variant="outline" className={cn("text-[10px] mr-2", type === "in" ? "text-green-400" : "text-red-400")}>
                  {type === "in" ? "입금" : "출금"}
                </Badge>
                {editItem?.internal_account_name ?? editItem?.category}
              </p>
            </div>
          ) : (
            <>
              <div>
                <label className="text-xs text-muted-foreground">유형</label>
                <div className="flex gap-4 mt-1">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" checked={type === "in"} onChange={() => { setType("in"); setCategory(""); setSelectedAccountId("") }} className="accent-[hsl(var(--profit))]" />
                    <span className="text-sm">입금</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" checked={type === "out"} onChange={() => { setType("out"); setCategory(""); setSelectedAccountId("") }} className="accent-[hsl(var(--loss))]" />
                    <span className="text-sm">출금</span>
                  </label>
                </div>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">내부계정</label>
                <div className="mt-1">
                  <AccountCombobox
                    options={internalAccounts}
                    value={selectedAccountId}
                    onChange={(v) => {
                      setSelectedAccountId(v)
                      if (v) setCategory("")
                    }}
                    placeholder="계정 선택"
                    showCode
                  />
                </div>
                {isParentAccount && !isEdit && (
                  <div className="mt-2 p-2 rounded-md bg-blue-500/10 border border-blue-500/20 text-xs">
                    <p className="text-blue-400 font-medium mb-1">상위 항목 — 하위 {childAccounts.length}개 자동 생성</p>
                    <div className="text-blue-300/70 space-y-0.5">
                      {childAccounts.map(c => {
                        const prev = prevSuggestions.find(s => s.internal_account_id === c.id)
                        return (
                          <div key={c.id} className="flex justify-between">
                            <span>└ {c.name}</span>
                            {prev && <span className="font-mono">₩{prev.total.toLocaleString()}</span>}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
          <div>
            <label className="text-xs text-muted-foreground">금액</label>
            <Input
              type="text"
              inputMode="numeric"
              placeholder="0"
              value={amount}
              onChange={(e) => {
                const raw = e.target.value.replace(/[^\d]/g, "")
                setAmount(raw ? Number(raw).toLocaleString() : "")
              }}
              className="mt-1 font-mono"
            />
            {prevActual !== null && !isEdit && (
              <button
                type="button"
                onClick={() => setAmount(prevActual.toLocaleString())}
                className="mt-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
              >
                전월 {isParentAccount ? "하위 합계" : "실적"}: ₩{prevActual.toLocaleString()} ← 클릭하여 적용
              </button>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">예상 결제일</label>
              <select
                value={expectedDay}
                onChange={(e) => setExpectedDay(e.target.value)}
                className="mt-1 w-full h-9 rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="">미지정</option>
                {Array.from({ length: 31 }, (_, i) => (
                  <option key={i + 1} value={i + 1}>{i + 1}일</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">결제수단</label>
              <select
                value={paymentMethod}
                onChange={(e) => setPaymentMethod(e.target.value as "bank" | "card")}
                className="mt-1 w-full h-9 rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="bank">은행이체</option>
                <option value="card">카드</option>
              </select>
            </div>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <Checkbox checked={recurring} onCheckedChange={(v) => setRecurring(!!v)} />
            <span className="text-sm">매월 반복</span>
          </label>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>취소</Button>
            <Button onClick={handleSave} disabled={saving || (!category && !selectedAccountId) || !amount}>
              {saving ? "저장 중..." : "저장"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── Component ──────────────────────────────────────────

export function ForecastTab({ entityId }: { entityId: string | null }) {
  const [data, setData] = useState<ForecastData | null>(null)
  const [schedule, setSchedule] = useState<DailyScheduleData | null>(null)
  const [summary, setSummary] = useState<SummaryData | null>(null)
  const [state, setState] = useState<LoadState>("loading")
  const [error, setError] = useState("")
  const [globalMonth, setGlobalMonth, monthReady] = useGlobalMonth()
  const [selectedMonth, setSelectedMonthLocal] = useState(globalMonth)
  const setSelectedMonth = useCallback((m: string) => { setSelectedMonthLocal(m); setGlobalMonth(m) }, [setGlobalMonth])

  // globalMonth가 localStorage에서 복원되면 동기화
  useEffect(() => { setSelectedMonthLocal(globalMonth) }, [globalMonth])

  const [showComparison, setShowComparison] = useState(false)
  const [editingItemId, setEditingItemId] = useState<number | null>(null)
  const [editingAmount, setEditingAmount] = useState("")
  const [editModalItem, setEditModalItem] = useState<ForecastItem | null>(null)
  const [collapsedIds, setCollapsedIds] = useState<Set<number> | null>(null) // null = not yet initialized

  const toggleCollapse = useCallback((accountId: number) => {
    setCollapsedIds(prev => {
      const next = new Set(prev ?? [])
      if (next.has(accountId)) next.delete(accountId)
      else next.add(accountId)
      return next
    })
  }, [])

  /** Build tree from flat forecast items — group siblings by shared parent_id */
  const treeItems = useMemo(() => {
    if (!data) return []
    const items = data.items

    // Group items by internal_account_parent_id
    // Items with the same parent_id (and parent_id != null) become siblings under a virtual group
    const groupMap = new Map<number, ForecastItem[]>()
    const ungrouped: ForecastItem[] = []

    for (const item of items) {
      const parentId = item.internal_account_parent_id
      if (parentId != null) {
        const siblings = groupMap.get(parentId) || []
        siblings.push(item)
        groupMap.set(parentId, siblings)
      } else {
        ungrouped.push(item)
      }
    }

    // Build tree: groups with 2+ siblings get a virtual parent node, singletons stay flat
    const nodes: TreeNode[] = []

    // Process grouped items first (by type order: in before out)
    const processedIds = new Set<number>()
    for (const [parentId, siblings] of Array.from(groupMap.entries())) {
      // Always group items that share a parent — even single items get a group header
      const parentName = siblings[0].parent_account_name ?? siblings[0].category
      const type = siblings[0].type
      const childrenSum = siblings.reduce((s: number, c: ForecastItem) => s + c.forecast_amount, 0)
      const childActuals = siblings.map((c: ForecastItem) => c.actual_from_transactions)
      const childrenActualSum: number | null = childActuals.some((a: number | null) => a != null)
        ? childActuals.reduce((s: number, a: number | null) => s + (a ?? 0), 0)
        : null

      // Virtual parent item (not a real forecast — used for display only)
      const virtualParent: ForecastItem = {
        id: -parentId, // negative to avoid collision
        category: parentName,
        subcategory: null,
        type,
        forecast_amount: 0, // will show childrenSum
        actual_amount: null,
        is_recurring: false,
        note: null,
        internal_account_id: parentId,
        internal_account_name: parentName,
        internal_account_parent_id: null,
        parent_account_name: null,
        actual_from_transactions: null,
        expected_day: null,
        payment_method: "bank",
      }

      nodes.push({
        item: virtualParent,
        children: siblings.map((c: ForecastItem) => ({
          item: c,
          children: [],
          childrenSum: 0,
          childrenActualSum: null,
          depth: 1,
        })),
        childrenSum,
        childrenActualSum,
        depth: 0,
      })
      siblings.forEach((s: ForecastItem) => { if (s.id) processedIds.add(s.id) })
    }

    // Add ungrouped items
    for (const item of ungrouped) {
      if (!processedIds.has(item.id)) {
        nodes.push({
          item,
          children: [],
          childrenSum: 0,
          childrenActualSum: null,
          depth: 0,
        })
      }
    }

    // Sort: type "in" first, then "out"
    nodes.sort((a, b) => {
      if (a.item.type !== b.item.type) return a.item.type === "in" ? -1 : 1
      return 0
    })

    return nodes
  }, [data])

  // Auto-collapse groups on initial load
  useEffect(() => {
    if (collapsedIds === null && treeItems.length > 0) {
      const ids = new Set<number>()
      for (const node of treeItems) {
        if (node.children.length > 0 && node.item.internal_account_id != null) {
          ids.add(node.item.internal_account_id)
        }
      }
      setCollapsedIds(ids)
    }
  }, [treeItems, collapsedIds])

  // Fetch summary for month navigation
  const fetchSummary = useCallback(async () => {
    if (!entityId) return
    try {
      const s = await fetchAPI<SummaryData>(
        `/cashflow/summary?entity_id=${entityId}&months=12`,
        { cache: "no-store" },
      )
      setSummary(s)
      if (s.available_months.length && !selectedMonth) {
        // 예상 현금흐름: 마지막 데이터 월의 다음 달을 기본 선택
        const lastMonth = s.available_months[s.available_months.length - 1]
        const [ly, lm] = lastMonth.split("-").map(Number)
        const nextMonth = lm === 12
          ? `${ly + 1}-01`
          : `${ly}-${String(lm + 1).padStart(2, "0")}`
        setSelectedMonth(nextMonth)
      }
    } catch {
      // Summary is optional, forecast still works
    }
  }, [entityId]) // eslint-disable-line react-hooks/exhaustive-deps

  const fetchForecast = useCallback(async () => {
    if (!entityId || !selectedMonth || !monthReady) return
    setState("loading")
    const [y, m] = selectedMonth.split("-").map(Number)
    try {
      const [d, s] = await Promise.all([
        fetchAPI<ForecastData>(
          `/cashflow/forecast?entity_id=${entityId}&year=${y}&month=${m}`,
          { cache: "no-store" },
        ),
        fetchAPI<DailyScheduleData>(
          `/cashflow/daily-schedule?entity_id=${entityId}&year=${y}&month=${m}`,
          { cache: "no-store" },
        ).catch(() => null),
      ])
      // 항목이 비어있으면 전월 반복 항목 자동 복사 (actual 금액 우선)
      if (d.items.length === 0) {
        const prevMonth = m - 1 > 0 ? m - 1 : 12
        const prevYear = m - 1 > 0 ? y : y - 1
        try {
          const copyResult = await fetchAPI<{ copied: number }>(
            `/forecasts/copy-recurring?entity_id=${entityId}&source_year=${prevYear}&source_month=${prevMonth}&target_year=${y}&target_month=${m}&amount_source=actual`,
            { method: "POST" },
          )
          if (copyResult.copied > 0) {
            // 복사됐으면 다시 fetch
            const [d2, s2] = await Promise.all([
              fetchAPI<ForecastData>(
                `/cashflow/forecast?entity_id=${entityId}&year=${y}&month=${m}`,
                { cache: "no-store" },
              ),
              fetchAPI<DailyScheduleData>(
                `/cashflow/daily-schedule?entity_id=${entityId}&year=${y}&month=${m}`,
                { cache: "no-store" },
              ).catch(() => null),
            ])
            setData(d2)
            setSchedule(s2)
            setState("success")
            return
          }
        } catch { /* 복사 실패해도 빈 상태로 표시 */ }
      }

      setData(d)
      setSchedule(s)
      setCollapsedIds(null)
      setState("success")
    } catch (err) {
      setError(err instanceof Error ? err.message : "데이터를 불러올 수 없습니다.")
      setState("error")
    }
  }, [entityId, selectedMonth, monthReady])

  useEffect(() => { fetchSummary() }, [fetchSummary])
  useEffect(() => { fetchForecast() }, [fetchForecast])

  // 예상 탭: available_months + 마지막 완료월 기준 미래 2개월
  const baseMonths = summary?.available_months ?? []
  const months = (() => {
    const set = new Set(baseMonths)
    const now = new Date()
    const lastComplete = new Date(now.getFullYear(), now.getMonth(), 0)
    const base = baseMonths.length > 0
      ? (() => { const [y, m] = baseMonths[baseMonths.length - 1].split("-").map(Number); return new Date(y, m - 1, 1) })()
      : new Date(lastComplete.getFullYear(), lastComplete.getMonth(), 1)
    for (let i = 1; i <= 2; i++) {
      const d = new Date(base.getFullYear(), base.getMonth() + i, 1)
      set.add(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`)
    }
    return Array.from(set).sort()
  })()

  // ── LOADING ──
  if (state === "loading" || !selectedMonth) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}
        </div>
        <Skeleton className="h-[200px] rounded-xl" />
      </div>
    )
  }

  if (state === "error") {
    return (
      <Card className="p-8 flex flex-col items-center text-center gap-4">
        <AlertCircle className="h-12 w-12 text-[hsl(var(--loss))]" />
        <p className="font-medium">데이터를 불러올 수 없습니다.</p>
        <p className="text-sm text-muted-foreground">{error}</p>
        <Button onClick={fetchForecast} variant="secondary" className="gap-2">
          <RefreshCw className="h-4 w-4" /> 다시 시도
        </Button>
      </Card>
    )
  }

  if (!data) return null
  const [y, m] = selectedMonth.split("-").map(Number)

  const diffPct = data.adjusted_forecast_closing !== 0
    ? ((data.actual_closing - data.adjusted_forecast_closing) / Math.abs(data.adjusted_forecast_closing) * 100)
    : 0
  const diffColor = Math.abs(diffPct) <= 5 ? "text-[hsl(var(--profit))]" : Math.abs(diffPct) <= 10 ? "text-[hsl(var(--warning))]" : "text-[hsl(var(--loss))]"

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <MonthPicker months={months} selected={selectedMonth} onSelect={setSelectedMonth} accentColor="hsl(var(--warning))" allowFuture />
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="gap-2">
            <Download className="h-4 w-4" /> 내보내기
          </Button>
        </div>
      </div>

      {/* Note box (mockup style) */}
      <div className="bg-amber-500/[0.06] border border-amber-500/15 rounded-lg px-4 py-3 text-xs text-[hsl(var(--warning))]">
        <strong className="block mb-1">{y}년 {m}월 예상 현금흐름</strong>
        카드/은행 데이터 업로드마다 &quot;실제 진행&quot; 컬럼이 업데이트됩니다. 월말에 예상과 실제를 비교합니다.
      </div>

      {/* Alerts from daily schedule (DESIGN-2) */}
      {schedule?.alerts && schedule.alerts.length > 0 && (
        <Card className="bg-red-500/10 border-red-500/30 rounded-xl p-4" role="alert" aria-live="polite">
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle className="h-4 w-4 text-red-400" />
            <span className="text-sm font-medium text-red-400">잔고 부족 예상</span>
          </div>
          <div className="space-y-1">
            {schedule.alerts.slice(0, 3).map((alert, i) => (
              <p key={i} className="text-xs text-red-300">
                {alert.message} (부족액: {formatByEntity(alert.deficit, entityId)})
              </p>
            ))}
            {schedule.alerts.length > 3 && (
              <p className="text-xs text-red-300/70">외 {schedule.alerts.length - 3}건 더 보기</p>
            )}
          </div>
          <div className="flex gap-2 mt-3 max-sm:flex-col">
            <Button variant="outline" size="sm" className="text-xs border-red-500/30 text-red-400 hover:bg-red-500/10">
              예상 항목 조정
            </Button>
            <Button variant="outline" size="sm" className="text-xs border-red-500/30 text-red-400 hover:bg-red-500/10">
              입금 추가
            </Button>
          </div>
        </Card>
      )}

      {/* Forecast vs Actual balance chart (daily-schedule API) */}
      <ForecastBalanceChart schedule={schedule} forecastData={data} entityId={entityId} month={m} />

      {/* KPI */}
      <div className="grid grid-cols-4 gap-3 max-md:grid-cols-2">
        <KPICard label={`기초 (${m - 1 || 12}월 확정)`} value={formatByEntity(data.opening_balance, entityId)} rawAmount={data.opening_balance} entityId={entityId} />
        <KPICard
          label="조정 예상 기말"
          value={formatByEntity(data.adjusted_forecast_closing, entityId)}
          rawAmount={data.adjusted_forecast_closing}
          entityId={entityId}
          colorClass="text-[hsl(var(--warning))]"
          subtext={data.unmapped_count > 0 ? `미분류 ${data.unmapped_count}건 반영` : undefined}
          subtextColor="text-amber-400"
        />
        <KPICard
          label="실제 진행 기준 기말"
          value={formatByEntity(data.actual_closing, entityId)}
          rawAmount={data.actual_closing}
          entityId={entityId}
          subtext={`차이: ${data.diff >= 0 ? "+" : ""}${formatByEntity(data.diff, entityId)}`}
          colorClass="text-[hsl(var(--profit))]"
        />
        <KPICard
          label="카드 사용 (진행)"
          value={formatByEntity(data.card_timing.curr_month_card_actual, entityId)}
          rawAmount={data.card_timing.curr_month_card_actual}
          entityId={entityId}
          subtext={`예상 ${formatByEntity(data.forecast_card_usage, entityId)} 중`}
          colorClass="text-[#8B5CF6]"
        />
      </div>

      {/* Over-budget warning */}
      {data.over_budget && data.over_budget.length > 0 && (
        <Card className="bg-red-500/10 border-red-500/30 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle className="h-4 w-4 text-red-400" />
            <span className="text-sm font-medium text-red-400">예산 초과 항목</span>
          </div>
          <div className="space-y-1">
            {data.over_budget.map((item, i) => (
              <p key={i} className="text-xs text-red-300">
                {item.category}: 예상 {formatByEntity(item.forecast, entityId)} &rarr; 실제 {formatByEntity(item.actual, entityId)} (+{item.diff_pct}%)
              </p>
            ))}
          </div>
        </Card>
      )}

      {/* Forecast items list (no chart -- table only per mockup) */}
      <Card className="overflow-hidden rounded-2xl">
        <div className="px-4 py-3 flex items-center justify-between border-b border-border">
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-semibold">{m}월 예상 항목</h3>
            {data.items.filter(i => !i.internal_account_id).length > 0 && (
              <button
                onClick={async () => {
                  try {
                    const res = await fetchAPI<{ matched: number; unmatched: string[] }>(
                      `/forecasts/backfill-accounts?entity_id=${entityId}&year=${y}&month=${m}`,
                      { method: "POST" },
                    )
                    if (res.matched > 0) {
                      toast.success(`${res.matched}건 내부계정 자동 연결 완료`)
                      fetchForecast()
                    }
                    if (res.unmatched.length > 0) {
                      toast.info(`미연결: ${res.unmatched.join(", ")} — 내부계정을 먼저 추가해주세요`)
                    }
                  } catch { toast.error("자동 연결에 실패했습니다") }
                }}
                className="flex items-center gap-1 text-[10px] text-amber-400 hover:text-amber-300 bg-amber-500/10 border border-amber-500/30 px-2 py-1 rounded-md transition-colors"
              >
                <Link2 className="h-3 w-3" />
                미연결 {data.items.filter(i => !i.internal_account_id).length}건 자동 연결
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowComparison(!showComparison)}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors bg-muted/30 border border-border px-3 py-1.5 rounded-lg"
              aria-expanded={showComparison}
              aria-label="실제 비교 컬럼 표시"
            >
              {showComparison ? "실제 비교 접기 \u25C2" : "실제 비교 펼치기 \u25B8"}
            </button>
            <ForecastModal entityId={entityId!} year={y} month={m} onSaved={fetchForecast} />
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/30 text-[10px] text-muted-foreground uppercase tracking-wider">
                <th className="text-left px-4 py-2">유형</th>
                <th className="text-left px-4 py-2">항목</th>
                <th className="text-right px-4 py-2">예상 금액</th>
                {showComparison && <th className="text-right px-4 py-2 text-[hsl(var(--profit))]">실제 진행</th>}
                <th className="text-right px-4 py-2 text-[hsl(var(--warning))]">예상 잔고</th>
                {showComparison && <th className="text-right px-4 py-2 text-[hsl(var(--profit))]">실제 잔고</th>}
                <th className="w-10 px-2 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {/* Opening row */}
              <tr className="border-t border-border bg-green-500/[0.03]">
                <td className="px-4 py-2.5"></td>
                <td className="px-4 py-2.5 font-medium">시작 잔고</td>
                <td className="px-4 py-2.5 text-right font-mono tabular-nums">--</td>
                {showComparison && <td className="px-4 py-2.5 text-right font-mono tabular-nums">--</td>}
                <td className="px-4 py-2.5 text-right font-mono tabular-nums">
                  {formatByEntity(data.opening_balance, entityId)}
                </td>
                {showComparison && (
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums text-[hsl(var(--profit))]">
                    {formatByEntity(data.opening_balance, entityId)}
                  </td>
                )}
                <td></td>
              </tr>

              {/* Forecast items (tree view) */}
              {(() => {
                let runningBalance = data.opening_balance
                let runningActual = data.opening_balance
                const rows: React.ReactNode[] = []

                const renderItemRow = (
                  item: ForecastItem,
                  depth: number,
                  hasChildren: boolean,
                  isCollapsed: boolean,
                  displayAmount: number,
                  displayActual: number | null,
                ) => {
                  const actual = displayActual ?? item.actual_from_transactions
                  const effectiveAmount = hasChildren && isCollapsed ? displayAmount : item.forecast_amount
                  const effectiveActual = hasChildren && isCollapsed ? displayActual : item.actual_from_transactions

                  // 누적 잔고 계산
                  // virtual parent (id < 0): collapsed → childrenSum, expanded → skip (children count)
                  // real item: always counts
                  const isVirtualParent = item.id < 0
                  const balanceAmount = (hasChildren && isCollapsed)
                    ? displayAmount
                    : (isVirtualParent ? 0 : item.forecast_amount) // virtual expanded parent → 0
                  const balanceActual = (hasChildren && isCollapsed)
                    ? displayActual
                    : (isVirtualParent ? null : item.actual_from_transactions)
                  if (item.type === "in") {
                    runningBalance += balanceAmount
                    if (balanceActual != null) runningActual += balanceActual
                  } else {
                    runningBalance -= balanceAmount
                    if (balanceActual != null) runningActual -= balanceActual
                  }
                  const itemBalance = runningBalance
                  const itemActualBalance = balanceActual != null ? runningActual : null

                  return (
                    <tr
                      key={item.id}
                      className={cn(
                        "border-t border-border hover:bg-white/[0.02] transition-colors group",
                        depth > 0 && "bg-muted/[0.03]",
                        isVirtualParent && "bg-white/[0.01] cursor-pointer",
                      )}
                      onClick={isVirtualParent && item.internal_account_id ? () => toggleCollapse(item.internal_account_id!) : undefined}
                    >
                      <td className="px-4 py-2.5">
                        {depth === 0 && !isVirtualParent && (
                          <Badge
                            variant="outline"
                            className={cn(
                              "text-[10px] font-semibold px-2 py-0.5 cursor-pointer hover:opacity-80 transition-opacity",
                              item.type === "in" ? "bg-green-500/12 text-green-400" : "bg-red-500/12 text-red-400",
                            )}
                            onClick={async () => {
                              const newType = item.type === "in" ? "out" : "in"
                              try {
                                await fetchAPI(`/forecasts/${item.id}`, {
                                  method: "PUT",
                                  body: JSON.stringify({ type: newType }),
                                })
                                fetchForecast()
                              } catch { /* error */ }
                            }}
                            title="클릭하여 입금/출금 전환"
                          >
                            {item.type === "in" ? "입금" : "출금"}
                          </Badge>
                        )}
                        {isVirtualParent && (
                          <Badge
                            variant="outline"
                            className={cn(
                              "text-[10px] font-semibold px-2 py-0.5",
                              item.type === "in" ? "bg-green-500/12 text-green-400" : "bg-red-500/12 text-red-400",
                            )}
                          >
                            {item.type === "in" ? "입금" : "출금"}
                          </Badge>
                        )}
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center" style={depth > 0 ? { paddingLeft: `${depth * 20}px` } : undefined}>
                          {hasChildren && (
                            <button
                              onClick={(e) => { e.stopPropagation(); item.internal_account_id && toggleCollapse(item.internal_account_id) }}
                              className="mr-1.5 p-2 -ml-2 text-muted-foreground hover:text-foreground transition-colors rounded hover:bg-white/[0.05]"
                              aria-expanded={!isCollapsed}
                              aria-label={`${item.internal_account_name ?? item.category} ${isCollapsed ? '펼치기' : '접기'}`}
                            >
                              {isCollapsed
                                ? <ChevronRight className="h-4 w-4" />
                                : <ChevronDown className="h-4 w-4" />}
                            </button>
                          )}
                          {depth > 0 && <span className="text-muted-foreground/30 mr-1.5">└</span>}
                          <span className={cn(hasChildren && "font-medium")}>
                            {item.internal_account_name ?? item.category}
                          </span>
                          {!isVirtualParent && !item.internal_account_id && (
                            <span className="ml-1.5 text-amber-400" title="내부계정 미연결 — 자동 연결 버튼을 눌러주세요">
                              <AlertTriangle className="h-3 w-3 inline" />
                            </span>
                          )}
                          {item.subcategory && <span className="text-muted-foreground ml-1">({item.subcategory})</span>}
                          {item.is_recurring && <span className="text-xs text-muted-foreground ml-2">반복</span>}
                          {item.expected_day && <span className="text-[10px] text-muted-foreground/60 ml-1.5">{item.expected_day}일</span>}
                          {item.payment_method === "card" && <span className="text-[10px] text-purple-400/60 ml-1">카드</span>}
                          {hasChildren && isCollapsed && (
                            <span className="text-[10px] text-muted-foreground ml-2">({displayAmount === item.forecast_amount ? "" : "하위 합산"})</span>
                          )}
                        </div>
                      </td>
                      <td className={cn(
                        "px-4 py-2.5 text-right font-mono tabular-nums text-xs",
                        item.type === "in" ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]",
                      )}>
                        {(hasChildren && isCollapsed) || isVirtualParent ? (
                          <div className="flex flex-col items-end">
                            <span className={cn(isVirtualParent && !isCollapsed && "text-muted-foreground")}>
                              {item.type === "in" ? "+" : "-"}{formatByEntity(displayAmount, entityId)}
                            </span>
                            {displayActual != null && displayActual !== 0 && (() => {
                              const diff = displayActual! - displayAmount
                              if (Math.abs(diff) < 1) return null
                              const pct = displayAmount !== 0 ? Math.round((diff / displayAmount) * 100) : null
                              const isOver = diff > 0
                              return (
                                <span className={cn("text-[10px] font-normal", isOver ? "text-[hsl(var(--loss))]" : "text-[hsl(var(--profit))]")}>
                                  실제 {formatByEntity(displayActual!, entityId)}
                                  {pct != null && ` (${isOver ? "+" : ""}${pct}%)`}
                                </span>
                              )
                            })()}
                          </div>
                        ) : editingItemId === item.id ? (
                          <input
                            type="text"
                            autoFocus
                            className="w-28 text-right bg-transparent border-b border-foreground/30 outline-none font-mono text-xs py-0.5"
                            value={editingAmount}
                            onChange={(e) => {
                              const raw = e.target.value.replace(/[^\d]/g, "")
                              setEditingAmount(raw ? Number(raw).toLocaleString() : "")
                            }}
                            onBlur={async () => {
                              const amt = Number(editingAmount.replace(/,/g, ""))
                              if (!isNaN(amt) && amt !== item.forecast_amount) {
                                try {
                                  await fetchAPI(`/forecasts/${item.id}`, {
                                    method: "PUT",
                                    body: JSON.stringify({ forecast_amount: amt }),
                                  })
                                  fetchForecast()
                                } catch { /* error */ }
                              }
                              setEditingItemId(null)
                            }}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") (e.target as HTMLInputElement).blur()
                              if (e.key === "Escape") setEditingItemId(null)
                            }}
                          />
                        ) : (
                          <div className="flex flex-col items-end">
                            <span
                              className="cursor-pointer hover:underline decoration-dotted"
                              onClick={() => {
                                setEditingItemId(item.id)
                                setEditingAmount(item.forecast_amount.toLocaleString())
                              }}
                              title="클릭하여 수정"
                            >
                              {item.type === "in" ? "+" : "-"}{formatByEntity(item.forecast_amount, entityId)}
                            </span>
                            {item.actual_from_transactions != null && item.actual_from_transactions !== 0 && (() => {
                              const diff = item.actual_from_transactions! - item.forecast_amount
                              if (Math.abs(diff) < 1) return null
                              const pct = item.forecast_amount !== 0 ? Math.round((diff / item.forecast_amount) * 100) : null
                              const isOver = diff > 0
                              return (
                                <span className={cn("text-[10px] font-normal", isOver ? "text-[hsl(var(--loss))]" : "text-[hsl(var(--profit))]")}>
                                  실제 {formatByEntity(item.actual_from_transactions!, entityId)}
                                  {pct != null && ` (${isOver ? "+" : ""}${pct}%)`}
                                </span>
                              )
                            })()}
                          </div>
                        )}
                      </td>
                      {showComparison && (
                        <td className="px-4 py-2.5 text-right font-mono tabular-nums text-xs">
                          {(hasChildren && isCollapsed ? displayActual : item.actual_from_transactions) != null
                            ? <span className={item.type === "in" ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}>
                                {item.type === "in" ? "+" : "-"}{formatByEntity((hasChildren && isCollapsed ? displayActual : item.actual_from_transactions)!, entityId)}
                              </span>
                            : <span className="text-muted-foreground">--</span>}
                        </td>
                      )}
                      <td className={cn(
                        "px-4 py-2.5 text-right font-mono tabular-nums text-xs",
                        depth > 0 ? "text-muted-foreground/60" : "text-[hsl(var(--warning))]",
                      )}>
                        {formatByEntity(itemBalance, entityId)}
                      </td>
                      {showComparison && (
                        <td className={cn(
                          "px-4 py-2.5 text-right font-mono tabular-nums text-xs",
                          depth > 0 ? "text-muted-foreground/60" : "text-[hsl(var(--profit))]",
                        )}>
                          {itemActualBalance != null ? formatByEntity(itemActualBalance, entityId) : "--"}
                        </td>
                      )}
                      <td className="px-2 py-2.5">
                        {!isVirtualParent && (
                          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button
                              onClick={() => setEditModalItem(item)}
                              className="text-muted-foreground hover:text-foreground"
                              title="수정"
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                            <button
                              onClick={async () => {
                                if (!confirm(`"${item.internal_account_name ?? item.category}" 항목을 삭제하시겠습니까?`)) return
                                try {
                                  await fetchAPI(`/forecasts/${item.id}`, { method: "DELETE" })
                                  fetchForecast()
                                } catch { /* toast handled by fetchAPI */ }
                              }}
                              className="text-muted-foreground hover:text-destructive"
                              title="삭제"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                }

                for (const node of treeItems) {
                  const hasChildren = node.children.length > 0
                  const isCollapsed = hasChildren && node.item.internal_account_id != null && (collapsedIds ?? new Set()).has(node.item.internal_account_id)
                  const displayAmount = hasChildren
                    ? node.item.forecast_amount + node.childrenSum
                    : node.item.forecast_amount
                  const displayActual = hasChildren
                    ? (node.childrenActualSum != null
                        ? (node.item.actual_from_transactions ?? 0) + node.childrenActualSum
                        : node.item.actual_from_transactions)
                    : node.item.actual_from_transactions

                  if (hasChildren && isCollapsed) {
                    // Collapsed: show parent with summed amounts, skip children
                    rows.push(renderItemRow(node.item, 0, true, true, displayAmount, displayActual))
                  } else {
                    // Parent row
                    rows.push(renderItemRow(node.item, 0, hasChildren, false, displayAmount, displayActual))
                    // Children
                    if (hasChildren) {
                      for (const child of node.children) {
                        // Children don't affect running balance (parent already counted)
                        rows.push(renderItemRow(child.item, 1, false, false, child.item.forecast_amount, child.item.actual_from_transactions))
                      }
                    }
                  }
                }
                return rows
              })()}

              {/* Unmapped transactions row — affects forecast balance */}
              {(data.unmapped_income > 0 || data.unmapped_expense > 0) && (() => {
                const unmappedNet = data.unmapped_income - data.unmapped_expense
                // Calculate adjusted balance: forecast_closing already excludes unmapped,
                // so adjusted = forecast_closing + unmappedNet, then subtract timing to get pre-timing value
                const adjustedPreTiming = data.forecast_closing - data.card_timing.adjustment + unmappedNet
                return (
                  <tr className="border-t border-dashed border-amber-500/30 bg-amber-500/[0.04] hover:bg-amber-500/[0.07] transition-colors">
                    <td className="px-4 py-2.5">
                      <Badge variant="outline" className="text-[10px] font-semibold px-2 py-0.5 bg-amber-500/12 text-amber-400">미분류</Badge>
                    </td>
                    <td className="px-4 py-2.5">
                      <Link
                        href={`/transactions?entity=${entityId}&year=${data.year}&month=${data.month}&filter=unmapped`}
                        className="flex items-center gap-1.5 group/link"
                      >
                        <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                        <span className="text-xs text-amber-400 underline decoration-dotted underline-offset-2 group-hover/link:decoration-solid">
                          미분류 실제 거래 {data.unmapped_count}건 &rarr;
                        </span>
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono tabular-nums text-xs text-muted-foreground">--</td>
                    {showComparison && (
                      <td className="px-4 py-2.5 text-right font-mono tabular-nums text-xs">
                        <div className="space-y-0.5">
                          {data.unmapped_income > 0 && (
                            <div className="text-[hsl(var(--profit))]">+{formatByEntity(data.unmapped_income, entityId)}</div>
                          )}
                          {data.unmapped_expense > 0 && (
                            <div className="text-[hsl(var(--loss))]">-{formatByEntity(data.unmapped_expense, entityId)}</div>
                          )}
                        </div>
                      </td>
                    )}
                    <td className={cn(
                      "px-4 py-2.5 text-right font-mono tabular-nums text-xs text-[hsl(var(--warning))]",
                    )}>
                      {formatByEntity(adjustedPreTiming, entityId)}
                    </td>
                    {showComparison && <td className="px-4 py-2.5 text-right font-mono tabular-nums text-xs text-muted-foreground">--</td>}
                    <td></td>
                  </tr>
                )
              })()}

              {/* Timing adjustment row */}
              {data.card_timing.adjustment !== 0 && (
                <tr className="border-t border-border bg-purple-500/[0.03]">
                  <td className="px-4 py-2.5">
                    <Badge variant="outline" className="text-[10px] font-semibold px-2 py-0.5 bg-amber-500/12 text-amber-400">시차보정</Badge>
                  </td>
                  <td className="px-4 py-2.5">카드 시차 보정</td>
                  <td className={cn(
                    "px-4 py-2.5 text-right font-mono tabular-nums text-xs",
                    data.card_timing.adjustment >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]",
                  )}>
                    {data.card_timing.adjustment >= 0 ? "+" : ""}{formatByEntity(data.card_timing.adjustment, entityId)}
                  </td>
                  {showComparison && <td className="px-4 py-2.5 text-right font-mono tabular-nums text-xs text-muted-foreground">--</td>}
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums text-xs text-[hsl(var(--warning))]">--</td>
                  {showComparison && <td className="px-4 py-2.5 text-right font-mono tabular-nums text-xs text-muted-foreground">--</td>}
                  <td></td>
                </tr>
              )}

              {/* Closing row */}
              <tr className="border-t-2 border-t-amber-500/15 bg-amber-500/[0.03]">
                <td className="px-4 py-3"></td>
                <td className="px-4 py-3 font-bold">기말 잔고</td>
                <td className="px-4 py-3 text-right font-mono tabular-nums text-xs">--</td>
                {showComparison && <td className="px-4 py-3 text-right font-mono tabular-nums text-xs">--</td>}
                <td className="px-4 py-3 text-right font-mono tabular-nums text-xs text-[hsl(var(--warning))]">
                  {formatByEntity(data.adjusted_forecast_closing, entityId)}
                </td>
                {showComparison && (
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-xs text-[hsl(var(--profit))]">
                    {formatByEntity(data.actual_closing, entityId)}
                  </td>
                )}
                <td></td>
              </tr>

              {data.items.length === 0 && (
                <tr>
                  <td colSpan={showComparison ? 7 : 5} className="px-4 py-8 text-center text-muted-foreground">
                    예상 항목을 추가해보세요
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Formula (collapsible) */}
      <Card className="p-4 bg-muted/30 font-mono text-xs leading-relaxed text-cyan-400 rounded-lg">
        <p>{m}월 조정 예상 기말 = {m - 1 || 12}월 확정 기말</p>
        <p className="ml-4">+ {m}월 예상 입금</p>
        <p className="ml-4">- {m}월 예상 출금</p>
        <p className="ml-4">- {m}월 예상 카드 사용액</p>
        <p className="ml-4 text-amber-400">+ ({m}월 예상 카드 사용액 - {m - 1 || 12}월 카드 사용액) &larr; 시차 보정</p>
        {data.unmapped_count > 0 && (
          <>
            <p className="ml-4 text-amber-400">+ 미분류 실제 입금 ({formatByEntity(data.unmapped_income, entityId)})</p>
            <p className="ml-4 text-amber-400">- 미분류 실제 출금 ({formatByEntity(data.unmapped_expense, entityId)})</p>
          </>
        )}
      </Card>

      {/* Comparison boxes */}
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        {/* Card timing box */}
        <Card className="bg-secondary rounded-xl p-4">
          <h4 className="text-xs font-semibold text-purple-400 mb-3">카드 시차</h4>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">{m - 1 || 12}월 카드 (확정)</span>
              <span className="font-mono tabular-nums">{formatByEntity(data.card_timing.prev_month_card, entityId)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">{m}월 카드 (진행)</span>
              <span className="font-mono tabular-nums">{formatByEntity(data.card_timing.curr_month_card_actual, entityId)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">{m}월 카드 (예상)</span>
              <span className="font-mono tabular-nums">{formatByEntity(data.card_timing.curr_month_card_estimate, entityId)}</span>
            </div>
            <div className="border-t border-border pt-2 flex justify-between font-medium">
              <span>시차 보정</span>
              <span className={cn("font-mono tabular-nums", data.card_timing.adjustment >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]")}>
                {data.card_timing.adjustment >= 0 ? "+" : ""}{formatByEntity(data.card_timing.adjustment, entityId)}
              </span>
            </div>
          </div>
        </Card>

        {/* Forecast vs actual box */}
        <Card className="bg-secondary rounded-xl p-4">
          <h4 className="text-xs font-semibold text-[hsl(var(--warning))] mb-3">예상 vs 실제</h4>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">조정 예상 기말</span>
              <span className="font-mono tabular-nums text-[hsl(var(--warning))]">{formatByEntity(data.adjusted_forecast_closing, entityId)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">실제 기말</span>
              <span className="font-mono tabular-nums">{formatByEntity(data.actual_closing, entityId)}</span>
            </div>
            <div className="border-t border-border pt-2 flex justify-between font-medium">
              <span>차이</span>
              <span className={cn("font-mono tabular-nums", diffColor)}>
                {data.diff >= 0 ? "+" : ""}{formatByEntity(data.diff, entityId)}
              </span>
            </div>
            {data.adjusted_forecast_closing !== 0 && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">정확도</span>
                <span className={cn("font-mono tabular-nums", diffColor)}>
                  {(100 - Math.abs(diffPct)).toFixed(1)}%
                </span>
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* Variance Bridge */}
      <VarianceBridge entityId={entityId} year={y} month={m} />

      {/* Edit Modal */}
      {editModalItem && (
        <ForecastModal
          entityId={entityId!}
          year={y}
          month={m}
          onSaved={() => { setEditModalItem(null); fetchForecast() }}
          editItem={editModalItem}
          open={!!editModalItem}
          onOpenChange={(v) => { if (!v) setEditModalItem(null) }}
        />
      )}
    </div>
  )
}
