"use client"

import React, { Fragment, useEffect, useState, useCallback, useMemo, useRef } from "react"
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
import { AlertCircle, RefreshCw, RotateCw, Plus, Download, Trash2, Pencil, ChevronRight, ChevronDown, Link2, AlertTriangle, TrendingDown, TrendingUp } from "lucide-react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { MonthPicker } from "@/components/month-picker"
import { AccountCombobox } from "@/components/account-combobox"

// ── Types ──────────────────────────────────────────────

interface ForecastLineItem {
  name: string
  amount: number
  note?: string | null
  is_recurring?: boolean  // 기본 true — 비반복만 명시적 체크 해제
}

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
  line_items: ForecastLineItem[] | null
}

interface UnbudgetedActual {
  internal_account_id: number
  account_name: string
  type: string
  actual_amount: number
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
  worst_case_points?: Array<{ day: number; balance: number }>
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
  predicted_ending: number
  as_of_date: string
  today_day_in_month: number
  opening_source: "confirmed" | "predicted"
  actual_income: number
  actual_expense: number
  actual_closing: number
  diff: number
  actual_daily_points: Array<{
    day: number
    balance: number
    net_change?: number
    transactions?: Array<{ description: string; amount: number; type: string; account?: string }>
  }>
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
  unbudgeted_actuals?: UnbudgetedActual[]
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
      {subtext && <p className={cn("text-[11px] mt-1 font-medium", subtextColor || "text-foreground/75")}>{subtext}</p>}
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

// ── Warnings Card (잔고 부족 + 예산 초과 통합) ─────────

function WarningsCard({
  alerts,
  overBudget,
  entityId,
  formatByEntity,
}: {
  alerts: Array<{ message: string; deficit: number }>
  overBudget: Array<{ category: string; forecast: number; actual: number; diff_pct: number }>
  entityId: string | null
  formatByEntity: (amount: number, entityId: string | null) => string
}) {
  const [expanded, setExpanded] = useState(false)
  const totalWarnings = alerts.length + overBudget.length

  return (
    <Card className="bg-red-500/10 border-red-500/30 rounded-xl overflow-hidden" role="alert">
      {/* Header — always visible, toggles expand */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-red-500/5 transition-colors"
      >
        <AlertCircle className="h-4 w-4 text-red-400 shrink-0" />
        <span className="text-sm font-medium text-red-400 flex-1">
          경고 {totalWarnings}건
        </span>
        {expanded ? (
          <ChevronDown className="h-4 w-4 text-red-400/60" />
        ) : (
          <ChevronRight className="h-4 w-4 text-red-400/60" />
        )}
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          {/* 잔고 부족 섹션 */}
          {alerts.length > 0 && (
            <div>
              <p className="text-[11px] font-medium text-red-400/80 uppercase tracking-wider mb-1.5">잔고 부족 예상</p>
              <div className="space-y-1">
                {alerts.map((alert, i) => (
                  <p key={i} className="text-xs text-red-300">
                    {alert.message} (부족액: {formatByEntity(alert.deficit, entityId)})
                  </p>
                ))}
              </div>
            </div>
          )}

          {/* 구분선 */}
          {alerts.length > 0 && overBudget.length > 0 && (
            <div className="border-t border-red-500/20" />
          )}

          {/* 예산 초과 섹션 */}
          {overBudget.length > 0 && (
            <div>
              <p className="text-[11px] font-medium text-red-400/80 uppercase tracking-wider mb-1.5">예산 초과 항목</p>
              <div className="space-y-1">
                {overBudget.map((item, i) => (
                  <p key={i} className="text-xs text-red-300">
                    {item.category}: 예상 {formatByEntity(item.forecast, entityId)} &rarr; 실제 {formatByEntity(item.actual, entityId)} (+{item.diff_pct}%)
                  </p>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

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
  onClosingBalances,
}: {
  schedule: DailyScheduleData | null
  forecastData: ForecastData
  entityId: string | null
  month: number
  onClosingBalances?: (balances: { original: number; adjusted: number; worstCase: number }) => void
}) {
  const chartData = useMemo(() => {
    if (!schedule) return null

    // Build actual balance + transaction lookup from daily points
    const actualBalanceByDay = new Map<number, number>()
    const actualTxByDay = new Map<number, typeof forecastData.actual_daily_points[0]>()
    if (forecastData.actual_daily_points?.length) {
      let lastBal = forecastData.opening_balance
      for (const pt of forecastData.actual_daily_points) {
        lastBal = pt.balance
        actualBalanceByDay.set(pt.day, lastBal)
        actualTxByDay.set(pt.day, pt)
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

    // 조정 예상 + shifted worst-case: 실제 구간은 실제 잔고, 미래는 남은 변동분 이어감
    const lastActualDay = forecastData.last_actual_day
    const lastActualBalance = lastActualDay > 0 ? (actualBalanceByDay.get(lastActualDay) ?? null) : null
    // index 기반 접근 (day 0 포함이므로 lastActualDay 번째가 해당 day)
    const forecastBalanceByDay = new Map(schedule.points.map((p: { day: number; balance: number }) => [p.day, p.balance]))
    const worstCasePoints = schedule.worst_case_points ?? []
    const worstBalanceByDay = new Map(worstCasePoints.map((p: { day: number; balance: number }) => [p.day, p.balance]))
    const lastForecastAtActualDay = lastActualDay > 0 ? (forecastBalanceByDay.get(lastActualDay) ?? null) : null
    const lastWorstAtActualDay = lastActualDay > 0 ? (worstBalanceByDay.get(lastActualDay) ?? null) : null

    const points = schedule.points.map((p, i) => {
      const dayTx = actualTxByDay.get(p.day)

      // 조정 예상 계산
      let estimated: number
      if (p.day === 0) {
        estimated = p.balance // 기초잔고
      } else if (p.day <= lastActualDay && actualBalanceByDay.has(p.day)) {
        // 실제 데이터 있는 구간: 실제 잔고를 따라감
        estimated = actualBalanceByDay.get(p.day)!
      } else if (lastActualBalance != null && lastForecastAtActualDay != null) {
        // 미래 구간: 마지막 실제 잔고 + (이 날 예상 - 마지막 실제일 예상) = 남은 변동분
        estimated = lastActualBalance + (p.balance - lastForecastAtActualDay)
      } else {
        estimated = p.balance // 실제 데이터 없으면 원래 예상 그대로
      }

      return {
        day: p.day === 0 ? "시작" : `${month}/${p.day}`,
        originalEstimated: p.balance,
        estimated,
        actual: p.day === 0
          ? forecastData.opening_balance
          : p.day <= forecastData.last_actual_day
            ? (actualBalanceByDay.get(p.day) ?? null)
            : null,
        worstCase: (() => {
          const wcBalance = worstBalanceByDay.get(p.day)
          if (wcBalance == null) return null
          // 월 완료(실제 데이터가 전체): static worst-case 그대로 (실제 vs 최악 비교용)
          const daysInMonth = schedule.points.length - 1 // day 0 제외
          if (lastActualDay >= daysInMonth) return wcBalance
          // 진행 중: shifted worst-case
          if (p.day === 0) return wcBalance
          if (p.day <= lastActualDay && actualBalanceByDay.has(p.day)) return actualBalanceByDay.get(p.day)!
          if (lastActualBalance != null && lastWorstAtActualDay != null) {
            return lastActualBalance + (wcBalance - lastWorstAtActualDay)
          }
          return wcBalance
        })(),
        events: p.events,
        actualNetChange: dayTx?.net_change ?? 0,
        actualTransactions: dayTx?.transactions ?? [],
      }
    })

    const lastPoint = points[points.length - 1]
    return {
      points,
      daysInMonth: schedule.points.length - 1,
      cardSettings: schedule.card_settings,
      closingBalances: {
        original: lastPoint?.originalEstimated ?? 0,
        adjusted: lastPoint?.estimated ?? 0,
        worstCase: lastPoint?.worstCase ?? lastPoint?.originalEstimated ?? 0,
      },
    }
  }, [schedule, forecastData, month])

  // 부모에 기말 잔고 전달
  useEffect(() => {
    if (chartData?.closingBalances && onClosingBalances) {
      onClosingBalances(chartData.closingBalances)
    }
  }, [chartData?.closingBalances?.adjusted, chartData?.closingBalances?.original, chartData?.closingBalances?.worstCase, onClosingBalances])

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
                  {point?.worstCase != null && <p className="text-red-400">최악: ₩{point.worstCase.toLocaleString()}</p>}
                  {point?.actual != null && <p className="text-[#22C55E]">실제: ₩{point.actual.toLocaleString()}</p>}
                  {point?.actualTransactions?.length > 0 && (
                    <div className="mt-1 pt-1 border-t border-white/10">
                      <p className="text-muted-foreground mb-0.5">실제 거래:</p>
                      {point.actualTransactions.slice(0, 5).map((t: { description: string; amount: number; type: string; account?: string }, i: number) => (
                        <p key={i} className={t.type === "out" ? "text-red-400" : "text-green-400"}>
                          {t.type === "out" ? "-" : "+"}₩{Math.round(t.amount).toLocaleString()} {t.description}{t.account ? ` (${t.account})` : ""}
                        </p>
                      ))}
                      {point.actualTransactions.length > 5 && (
                        <p className="text-muted-foreground">외 {point.actualTransactions.length - 5}건</p>
                      )}
                    </div>
                  )}
                  {point?.events?.length > 0 && (
                    <div className="mt-1 pt-1 border-t border-white/10">
                      <p className="text-muted-foreground mb-0.5">예상 이벤트:</p>
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
          {/* Original forecast (gray solid line — always visible above Area) */}
          <Line
            type="monotone"
            dataKey="originalEstimated"
            stroke="#71717a"
            strokeWidth={1.5}
            strokeDasharray="8 4"
            strokeOpacity={0.7}
            dot={false}
            activeDot={false}
          />
          {/* Worst-case scenario (red dashed line) */}
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
          {/* Actual balance (green solid line, dots on large movements) */}
          <Line
            type="monotone"
            dataKey="actual"
            stroke="#22C55E"
            strokeWidth={2.5}
            dot={(props: { cx?: number; cy?: number; payload?: { actualNetChange?: number; actualTransactions?: Array<{ description: string; amount: number; type: string }> } }) => {
              const { cx, cy, payload } = props
              if (!cx || !cy || !payload?.actualNetChange) return <g />
              const absChange = Math.abs(payload.actualNetChange)
              // 500만원 이상 변동만 표시
              if (absChange < 5_000_000) return <g />
              const color = payload.actualNetChange > 0 ? "#22C55E" : "#EF4444"
              return (
                <circle cx={cx} cy={cy} r={4} fill={color} stroke="#050508" strokeWidth={1.5} />
              )
            }}
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
        <span className="text-[10px] text-red-400/60">— — 최악 시나리오</span>
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
  const [note, setNote] = useState(editItem?.note ?? "")
  const [lineItems, setLineItems] = useState<ForecastLineItem[]>(editItem?.line_items ?? [])
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
      setNote(editItem.note ?? "")
      setLineItems(editItem.line_items ?? [])
    }
  }, [editItem])

  // 라인 합계 자동 계산 — 유효 라인(이름·금액 둘 다 있는 것)이 1개 이상 있을 때만
  // amount 필드를 덮어쓴다. 그 전에는 기존 금액 유지.
  const validLineCount = useMemo(
    () => lineItems.filter(l => (l.name || "").trim() && (Number(l.amount) || 0) > 0).length,
    [lineItems],
  )
  const lineSum = useMemo(
    () => lineItems.reduce((s, l) => s + (Number(l.amount) || 0), 0),
    [lineItems],
  )
  useEffect(() => {
    if (validLineCount > 0) {
      setAmount(lineSum.toLocaleString())
    }
  }, [lineSum, validLineCount])

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
    setNote("")
    setLineItems([])
  }

  const handleSave = async () => {
    if ((!category && !selectedAccountId) || !amount) return
    // line_items 정제 — 이름·금액 둘 다 있는 것만
    const cleanLines = lineItems
      .map(l => ({
        name: (l.name || "").trim(),
        amount: Number(l.amount) || 0,
        note: l.note?.trim() || null,
      }))
      .filter(l => l.name && l.amount > 0)
    const lineItemsPayload = cleanLines.length > 0 ? cleanLines : null

    setSaving(true)
    try {
      if (isEdit && editItem) {
        const acc = internalAccounts.find((a) => String(a.id) === selectedAccountId)
        await fetchAPI(`/forecasts/${editItem.id}`, {
          method: "PUT",
          body: JSON.stringify({
            type,
            category: acc ? acc.name : (category.trim() || editItem.category),
            internal_account_id: acc ? acc.id : null,
            forecast_amount: Number(amount.replace(/,/g, "")),
            is_recurring: recurring,
            expected_day: expectedDay ? Number(expectedDay) : null,
            payment_method: paymentMethod,
            note: note.trim() || null,
            line_items: lineItemsPayload,
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
            note: note.trim() || null,
            line_items: lineItemsPayload,
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
          {isEdit && (
            <div>
              <label className="text-xs text-muted-foreground">항목 (내부계정)</label>
              <div className="mt-1">
                <AccountCombobox
                  options={internalAccounts}
                  value={selectedAccountId}
                  onChange={(v) => {
                    setSelectedAccountId(v)
                    const acc = internalAccounts.find((a) => String(a.id) === v)
                    if (acc) setCategory(acc.name)
                  }}
                  placeholder="내부계정 선택"
                  showCode
                />
              </div>
            </div>
          )}
          <div>
            <label className="text-xs text-muted-foreground">유형</label>
            <div className="flex gap-2 mt-1">
              <button
                type="button"
                onClick={() => { setType("in"); if (!isEdit) { setCategory(""); setSelectedAccountId("") } }}
                className={cn(
                  "flex-1 py-2 rounded-md text-sm font-medium transition-all border",
                  type === "in"
                    ? "bg-green-500/20 text-green-400 border-green-500/40"
                    : "bg-transparent text-muted-foreground border-border hover:border-green-500/30 hover:text-green-400/70",
                )}
              >
                + 입금
              </button>
              <button
                type="button"
                onClick={() => { setType("out"); if (!isEdit) { setCategory(""); setSelectedAccountId("") } }}
                className={cn(
                  "flex-1 py-2 rounded-md text-sm font-medium transition-all border",
                  type === "out"
                    ? "bg-red-500/20 text-red-400 border-red-500/40"
                    : "bg-transparent text-muted-foreground border-border hover:border-red-500/30 hover:text-red-400/70",
                )}
              >
                - 출금
              </button>
            </div>
          </div>
          {!isEdit && (
            <>
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
                    onCreateAccount={async (name, parentId) => {
                      const code = name.toUpperCase().replace(/[^A-Z가-힣0-9]/g, "").slice(0, 20) || `NEW_${Date.now()}`
                      const res = await fetchAPI<{ id: number; code: string; name: string; parent_id?: number | null; is_recurring?: boolean }>(
                        "/accounts/internal",
                        {
                          method: "POST",
                          body: JSON.stringify({
                            entity_id: Number(entityId),
                            code,
                            name,
                            parent_id: parentId,
                          }),
                        },
                      )
                      // 목록 새로고침
                      const updated = await fetchAPI<InternalAccount[]>(`/accounts/internal?entity_id=${entityId}`, { cache: "no-store" })
                      setInternalAccounts(updated)
                      return { id: res.id, code: res.code, name: res.name ?? name, parent_id: res.parent_id, is_recurring: res.is_recurring }
                    }}
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
            <label className="text-xs text-muted-foreground">
              금액 {validLineCount > 0 && <span className="text-blue-400">· 세부 합계 자동</span>}
            </label>
            <Input
              type="text"
              inputMode="numeric"
              placeholder="0"
              value={amount}
              onChange={(e) => {
                if (validLineCount > 0) return  // 유효 라인 있으면 직접 수정 막음
                const raw = e.target.value.replace(/[^\d]/g, "")
                setAmount(raw ? Number(raw).toLocaleString() : "")
              }}
              readOnly={validLineCount > 0}
              className={cn("mt-1 font-mono", validLineCount > 0 && "bg-muted/30 cursor-not-allowed")}
            />
            {prevActual !== null && !isEdit && validLineCount === 0 && (
              <button
                type="button"
                onClick={() => setAmount(prevActual.toLocaleString())}
                className="mt-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
              >
                전월 {isParentAccount ? "하위 합계" : "실적"}: ₩{prevActual.toLocaleString()} ← 클릭하여 적용
              </button>
            )}
          </div>

          {/* 세부 라인 항목 — 여러 거래처를 합쳐서 하나의 forecast로 */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs text-muted-foreground">
                세부 항목 (선택)
                {validLineCount > 0 && (
                  <span className="ml-2 text-[10px]">— 합계 ₩{lineSum.toLocaleString()}</span>
                )}
              </label>
              <button
                type="button"
                onClick={() => setLineItems((prev) => [...prev, { name: "", amount: 0, is_recurring: true }])}
                className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
              >
                + 세부 추가
              </button>
            </div>
            {lineItems.length > 0 && (
              <div className="space-y-1.5 rounded-md border border-white/[0.05] bg-white/[0.02] p-2">
                {lineItems.map((li, idx) => {
                  const isRec = li.is_recurring ?? true
                  return (
                    <div key={idx} className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() =>
                          setLineItems((prev) =>
                            prev.map((p, i) => (i === idx ? { ...p, is_recurring: !(p.is_recurring ?? true) } : p)),
                          )
                        }
                        className={cn(
                          "h-7 w-7 rounded text-[10px] font-semibold transition-colors shrink-0",
                          isRec
                            ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30"
                            : "bg-white/[0.04] text-muted-foreground border border-white/[0.08] hover:bg-white/[0.08]",
                        )}
                        title={isRec ? "반복 항목 (전월 가져오기 대상)" : "일회성 항목 (이번 달만)"}
                      >
                        {isRec ? "반복" : "일회"}
                      </button>
                      <Input
                        placeholder="이름 (예: A법률사무소)"
                        value={li.name}
                        onChange={(e) => {
                          const v = e.target.value
                          setLineItems((prev) =>
                            prev.map((p, i) => (i === idx ? { ...p, name: v } : p)),
                          )
                        }}
                        className="h-8 text-xs flex-1"
                      />
                      <Input
                        type="text"
                        inputMode="numeric"
                        placeholder="0"
                        value={li.amount ? Number(li.amount).toLocaleString() : ""}
                        onChange={(e) => {
                          const raw = e.target.value.replace(/[^\d]/g, "")
                          const num = raw ? Number(raw) : 0
                          setLineItems((prev) =>
                            prev.map((p, i) => (i === idx ? { ...p, amount: num } : p)),
                          )
                        }}
                        className="h-8 text-xs font-mono w-28 text-right"
                      />
                      <button
                        type="button"
                        onClick={() =>
                          setLineItems((prev) => prev.filter((_, i) => i !== idx))
                        }
                        className="text-muted-foreground hover:text-rose-400 text-sm px-1"
                        title="세부 삭제"
                      >
                        ×
                      </button>
                    </div>
                  )
                })}
                <p className="text-[10px] text-muted-foreground/70 pt-1">
                  좌측 뱃지로 반복 여부 토글 (전월 가져오기 대상 지정). 이름·금액 둘 다 있는 행만 저장.
                </p>
              </div>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">{type === "in" ? "예상 입금일" : "예상 결제일"}</label>
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
          <div>
            <label className="text-xs text-muted-foreground">메모</label>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="필요 시 추가 설명..."
              rows={2}
              className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-ring"
            />
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

// ── ForecastDetailModal — 하위항목 클릭 시 세부 정보 팝업 ──────────

function ForecastDetailModal({
  item,
  allItems,
  entityId,
  year,
  month,
  formatAmount,
  onEdit,
  open,
  onOpenChange,
}: {
  item: ForecastItem
  allItems: ForecastItem[]
  entityId: string
  year: number
  month: number
  formatAmount: (v: number) => string
  onEdit: () => void
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  // 매칭된 실제 거래 가져오기 (거래처별 그룹핑)
  const [matchedTxs, setMatchedTxs] = useState<Array<{
    id: number
    date: string
    amount: number
    counterparty: string | null
    description: string | null
  }>>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open || !item.internal_account_id) return
    setLoading(true)
    fetchAPI<{ items: typeof matchedTxs }>(
      `/transactions?entity_id=${entityId}&year=${year}&month=${month}&internal_account_id=${item.internal_account_id}&type=${item.type}&per_page=500`
    )
      .then((d) => setMatchedTxs(d?.items ?? []))
      .catch(() => setMatchedTxs([]))
      .finally(() => setLoading(false))
  }, [open, item.internal_account_id, item.type, entityId, year, month])

  // 거래처별 그룹핑
  const byCounterparty = matchedTxs.reduce<Record<string, { total: number; count: number; txs: typeof matchedTxs }>>((acc, tx) => {
    const key = tx.counterparty?.trim() || tx.description?.slice(0, 20) || "(이름 없음)"
    if (!acc[key]) acc[key] = { total: 0, count: 0, txs: [] }
    acc[key].total += tx.amount
    acc[key].count += 1
    acc[key].txs.push(tx)
    return acc
  }, {})
  const groupedList = Object.entries(byCounterparty).sort((a, b) => b[1].total - a[1].total)
  // 하위(children) 항목 수집 — virtual parent인 경우
  const children = allItems.filter(
    (i) => i.internal_account_parent_id === item.internal_account_id && i.id !== item.id,
  )
  const actual = item.actual_from_transactions ?? item.actual_amount ?? 0
  const diff = actual - item.forecast_amount
  const pct = item.forecast_amount !== 0 ? Math.round((actual / item.forecast_amount) * 100) : null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[560px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Badge
              variant="outline"
              className={cn(
                "text-[10px] font-semibold px-2 py-0.5",
                item.type === "in" ? "bg-green-500/12 text-green-400" : "bg-red-500/12 text-red-400",
              )}
            >
              {item.type === "in" ? "입금" : "출금"}
            </Badge>
            <span>{item.internal_account_name ?? item.category}</span>
            {item.parent_account_name && (
              <span className="text-xs text-muted-foreground font-normal">
                &larr; {item.parent_account_name}
              </span>
            )}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 pt-2">
          {/* KPI 카드 3개: 예상 / 실제 / 달성률 */}
          <div className="grid grid-cols-3 gap-2">
            <div className="rounded-lg border border-border bg-white/[0.02] px-3 py-2.5">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">예상</div>
              <div className="text-sm font-semibold font-mono tabular-nums">
                {formatAmount(item.forecast_amount)}
              </div>
            </div>
            <div className="rounded-lg border border-border bg-white/[0.02] px-3 py-2.5">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">실제</div>
              <div className={cn(
                "text-sm font-semibold font-mono tabular-nums",
                actual > 0 ? "text-[hsl(var(--profit))]" : "text-muted-foreground",
              )}>
                {formatAmount(actual)}
              </div>
            </div>
            <div className="rounded-lg border border-border bg-white/[0.02] px-3 py-2.5">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">달성률</div>
              <div className={cn(
                "text-sm font-semibold font-mono tabular-nums",
                pct === null ? "text-muted-foreground" :
                pct > 110 ? "text-[hsl(var(--loss))]" :
                pct >= 90 ? "text-[hsl(var(--profit))]" :
                "text-[hsl(var(--warning))]",
              )}>
                {pct !== null ? `${pct}%` : "--"}
              </div>
              {diff !== 0 && (
                <div className={cn(
                  "text-[10px] mt-0.5 font-mono",
                  diff > 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]",
                )}>
                  {diff > 0 ? "+" : ""}{formatAmount(diff)}
                </div>
              )}
            </div>
          </div>

          {/* 메타 정보 */}
          <div className="space-y-1.5 text-sm">
            {item.expected_day != null && (
              <div className="flex justify-between">
                <span className="text-muted-foreground text-xs">예상 일자</span>
                <span className="font-mono">{item.expected_day}일</span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-muted-foreground text-xs">결제 방식</span>
              <span className="text-xs">{item.payment_method === "card" ? "카드" : "은행"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground text-xs">반복 설정</span>
              <span className="text-xs">{item.is_recurring ? "고정 (매월)" : "일회성"}</span>
            </div>
            {item.internal_account_id && (
              <div className="flex justify-between">
                <span className="text-muted-foreground text-xs">내부계정 ID</span>
                <span className="text-xs font-mono">#{item.internal_account_id}</span>
              </div>
            )}
          </div>

          {/* 세부 라인 항목 */}
          {item.line_items && item.line_items.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-muted-foreground mb-1.5">
                세부 라인 ({item.line_items.length}건)
                {(() => {
                  const rec = item.line_items.filter((li) => (li.is_recurring ?? true)).length
                  const once = item.line_items.length - rec
                  if (once === 0) return null
                  return (
                    <span className="ml-2 text-[10px] text-muted-foreground">
                      반복 {rec} · 일회 {once}
                    </span>
                  )
                })()}
              </div>
              <div className="rounded-lg border border-border overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-muted/[0.15]">
                    <tr>
                      <th className="pl-3 pr-1 py-1.5 text-left font-medium text-muted-foreground w-[56px]"></th>
                      <th className="px-3 py-1.5 text-left font-medium text-muted-foreground">이름</th>
                      <th className="px-3 py-1.5 text-right font-medium text-muted-foreground">금액</th>
                    </tr>
                  </thead>
                  <tbody>
                    {item.line_items.map((li, idx) => {
                      const isRec = li.is_recurring ?? true
                      return (
                        <tr key={idx} className="border-t border-border">
                          <td className="pl-3 pr-1 py-1.5">
                            <span className={cn(
                              "inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap leading-none",
                              isRec
                                ? "bg-emerald-500/15 text-emerald-400"
                                : "bg-white/[0.04] text-muted-foreground",
                            )}>
                              {isRec ? "반복" : "일회"}
                            </span>
                          </td>
                          <td className="px-3 py-1.5">{li.name}</td>
                          <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                            {formatAmount(li.amount)}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 실제 거래 거래처별 그룹 */}
          {item.internal_account_id && (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <div className="text-xs font-semibold text-muted-foreground">
                  실제 거래 {loading ? "(로딩중...)" : `(${matchedTxs.length}건, ${groupedList.length}개 거래처)`}
                </div>
                <Link
                  href={`/transactions?entity=${entityId}&year=${year}&month=${month}&internal_account_id=${item.internal_account_id}&type=${item.type}`}
                  className="text-[10px] text-blue-400 hover:underline"
                >
                  전체 보기 &rarr;
                </Link>
              </div>
              {!loading && matchedTxs.length > 0 ? (
                <div className="rounded-lg border border-border overflow-hidden max-h-[260px] overflow-y-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/[0.15] sticky top-0">
                      <tr>
                        <th className="px-3 py-1.5 text-left font-medium text-muted-foreground">거래처</th>
                        <th className="px-3 py-1.5 text-right font-medium text-muted-foreground">건수</th>
                        <th className="px-3 py-1.5 text-right font-medium text-muted-foreground">합계</th>
                      </tr>
                    </thead>
                    <tbody>
                      {groupedList.map(([name, grp]) => (
                        <tr key={name} className="border-t border-border hover:bg-white/[0.02]">
                          <td className="px-3 py-1.5 max-w-[240px] truncate" title={name}>
                            {name}
                          </td>
                          <td className="px-3 py-1.5 text-right font-mono tabular-nums text-muted-foreground">
                            {grp.count}
                          </td>
                          <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                            {formatAmount(grp.total)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : !loading ? (
                <div className="text-xs text-muted-foreground py-2">매칭된 실제 거래가 없습니다</div>
              ) : null}
            </div>
          )}

          {/* 하위 예상 항목 (virtual parent) */}
          {children.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-muted-foreground mb-1.5">
                하위 항목 ({children.length}건)
              </div>
              <div className="rounded-lg border border-border overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-muted/[0.15]">
                    <tr>
                      <th className="px-3 py-1.5 text-left font-medium text-muted-foreground">이름</th>
                      <th className="px-3 py-1.5 text-right font-medium text-muted-foreground">예상</th>
                      <th className="px-3 py-1.5 text-right font-medium text-muted-foreground">실제</th>
                    </tr>
                  </thead>
                  <tbody>
                    {children.map((c) => (
                      <tr key={c.id} className="border-t border-border hover:bg-white/[0.02]">
                        <td className="px-3 py-1.5">
                          {c.internal_account_name ?? c.category}
                        </td>
                        <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                          {formatAmount(c.forecast_amount)}
                        </td>
                        <td className="px-3 py-1.5 text-right font-mono tabular-nums text-muted-foreground">
                          {formatAmount(c.actual_from_transactions ?? c.actual_amount ?? 0)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 메모 */}
          {item.note && (
            <div>
              <div className="text-xs font-semibold text-muted-foreground mb-1.5">메모</div>
              <div className="rounded-lg border border-border bg-white/[0.02] px-3 py-2 text-xs whitespace-pre-wrap">
                {item.note}
              </div>
            </div>
          )}

          {/* 액션 */}
          <div className="flex justify-between gap-2 pt-2 border-t border-border">
            <Link
              href={`/transactions?entity=${entityId}${item.internal_account_id ? `&internal_account_id=${item.internal_account_id}` : ""}`}
              className="text-xs text-blue-400 hover:underline self-center"
            >
              관련 거래 보기 &rarr;
            </Link>
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>닫기</Button>
              <Button size="sm" onClick={onEdit}>수정</Button>
            </div>
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
  const [closingBalances, setClosingBalances] = useState<{ original: number; adjusted: number; worstCase: number } | null>(null)
  const [state, setState] = useState<LoadState>("loading")
  const [error, setError] = useState("")
  const [globalMonth, setGlobalMonth, monthReady] = useGlobalMonth()
  const [selectedMonth, setSelectedMonthLocal] = useState(globalMonth)
  const setSelectedMonth = useCallback((m: string) => { setSelectedMonthLocal(m); setGlobalMonth(m) }, [setGlobalMonth])

  // globalMonth가 localStorage에서 복원되면 동기화
  useEffect(() => { setSelectedMonthLocal(globalMonth) }, [globalMonth])

  const [showComparison, setShowComparison] = useState(false)
  const [formulaOpen, setFormulaOpen] = useState(false)
  const [cardTimingOpen, setCardTimingOpen] = useState(false)
  const [vsActualOpen, setVsActualOpen] = useState(false)
  const [missingRecurring, setMissingRecurring] = useState<Array<{
    internal_account_id: number; name: string; code: string
    inferred_type: string; suggested_amount: number; txn_count: number; payment_method: string
  }>>([])
  const [missingDismissed, setMissingDismissed] = useState(false)
  const [missingLoading, setMissingLoading] = useState(false)
  const [editingItemId, setEditingItemId] = useState<number | null>(null)
  const [editingAmount, setEditingAmount] = useState("")
  const [editModalItem, setEditModalItem] = useState<ForecastItem | null>(null)
  const [detailModalItem, setDetailModalItem] = useState<ForecastItem | null>(null)
  const [collapsedIds, setCollapsedIds] = useState<Set<number> | null>(null) // null = not yet initialized
  const [expandedLeaves, setExpandedLeaves] = useState<Set<number>>(new Set()) // line_items 펼친 forecast.id

  const toggleCollapse = useCallback((accountId: number) => {
    setCollapsedIds(prev => {
      const next = new Set(prev ?? [])
      if (next.has(accountId)) next.delete(accountId)
      else next.add(accountId)
      return next
    })
  }, [])

  const toggleLeafExpand = useCallback((forecastId: number) => {
    setExpandedLeaves(prev => {
      const next = new Set(prev)
      if (next.has(forecastId)) next.delete(forecastId)
      else next.add(forecastId)
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
        line_items: null,
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

  const fetchForecast = useCallback(async (silent = false) => {
    if (!entityId || !selectedMonth || !monthReady) return
    if (!silent) setState("loading")
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
      // recurring 항목이 없으면 전월에서 자동 복사 (비정기만 있어도 복사 트리거)
      if (!d.items.some((item: { is_recurring: boolean }) => item.is_recurring)) {
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

  // missing-recurring 감지 (Decision 1A/2A/3A/5B)
  useEffect(() => {
    if (!entityId || !selectedMonth || !monthReady || state !== "success") return
    const [y, m] = selectedMonth.split("-").map(Number)
    const dismissKey = `dismissed-missing-recurring-${entityId}-${y}-${m}`
    if (localStorage.getItem(dismissKey)) { setMissingDismissed(true); return }
    setMissingDismissed(false)
    fetchAPI<{ items: typeof missingRecurring }>(`/forecasts/missing-recurring?entity_id=${entityId}&year=${y}&month=${m}`)
      .then(res => setMissingRecurring(res.items ?? []))
      .catch(() => setMissingRecurring([]))
  }, [entityId, selectedMonth, monthReady, state])

  const handleExportCSV = useCallback(() => {
    if (!data) return
    const [yy, mm] = selectedMonth.split("-").map(Number)

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
    a.download = `forecast_${yy}-${String(mm).padStart(2, "0")}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }, [data, selectedMonth])

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
        <Button onClick={() => fetchForecast()} variant="secondary" className="gap-2">
          <RefreshCw className="h-4 w-4" /> 다시 시도
        </Button>
      </Card>
    )
  }

  if (!data) return null
  const [y, m] = selectedMonth.split("-").map(Number)

  const diffPct = data.predicted_ending !== 0
    ? ((data.actual_closing - data.predicted_ending) / Math.abs(data.predicted_ending) * 100)
    : 0
  const diffColor = Math.abs(diffPct) <= 5 ? "text-[hsl(var(--profit))]" : Math.abs(diffPct) <= 10 ? "text-[hsl(var(--warning))]" : "text-[hsl(var(--loss))]"

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <MonthPicker months={months} selected={selectedMonth} onSelect={setSelectedMonth} accentColor="hsl(var(--warning))" allowFuture />
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="gap-2" onClick={handleExportCSV}>
            <Download className="h-4 w-4" /> 내보내기
          </Button>
        </div>
      </div>

      {/* Note box (mockup style) */}
      <div className="bg-amber-500/[0.06] border border-amber-500/15 rounded-lg px-4 py-3 text-xs text-[hsl(var(--warning))]">
        <strong className="block mb-1">{y}년 {m}월 예상 현금흐름</strong>
        카드/은행 데이터 업로드마다 &quot;실제 진행&quot; 컬럼이 업데이트됩니다. 월말에 예상과 실제를 비교합니다.
      </div>

      {/* Warnings card — 잔고 부족 + 예산 초과 통합 */}
      {((schedule?.alerts && schedule.alerts.length > 0) || (data.over_budget && data.over_budget.length > 0)) && (
        <WarningsCard
          alerts={schedule?.alerts || []}
          overBudget={data.over_budget || []}
          entityId={entityId}
          formatByEntity={formatByEntity}
        />
      )}

      {/* Forecast vs Actual balance chart (daily-schedule API) */}
      <ForecastBalanceChart schedule={schedule} forecastData={data} entityId={entityId} month={m} onClosingBalances={setClosingBalances} />

      {/* KPI — 5개 동등 column으로 분리 (폭 부족으로 숫자 truncate 방지) */}
      <div className="grid grid-cols-5 gap-3 max-xl:grid-cols-3 max-md:grid-cols-2">
        <KPICard
          label={`기초 (${m - 1 || 12}월 ${data.opening_source === "predicted" ? "예상" : "확정"})`}
          value={formatByEntity(data.opening_balance, entityId)}
          rawAmount={data.opening_balance}
          entityId={entityId}
          subtext={data.opening_source === "predicted" ? "월말 확정 시 자동 갱신" : undefined}
          subtextColor={data.opening_source === "predicted" ? "text-muted-foreground" : undefined}
        />
        <KPICard
          label="원래 예상 기말"
          value={formatByEntity(closingBalances?.original ?? data.forecast_closing, entityId)}
          rawAmount={closingBalances?.original ?? data.forecast_closing}
          entityId={entityId}
          colorClass="text-[#71717a]"
        />
        <KPICard
          label={`예상 기말 (${data.as_of_date?.slice(5) ?? "today"} 합성)`}
          value={formatByEntity(data.predicted_ending, entityId)}
          rawAmount={data.predicted_ending}
          entityId={entityId}
          colorClass="text-[hsl(var(--warning))]"
          subtext={(() => {
            const diff = data.predicted_ending - data.forecast_closing
            if (Math.abs(diff) < 1000) return "원래 예상과 동일"
            return `${diff >= 0 ? "+" : ""}${formatByEntity(diff, entityId)} vs 원래`
          })()}
          subtextColor={(() => {
            const diff = data.predicted_ending - data.forecast_closing
            if (Math.abs(diff) < 1000) return "text-muted-foreground"
            return diff >= 0 ? "text-emerald-300" : "text-rose-300"
          })()}
        />
        <KPICard
          label="실제 진행 기말"
          value={formatByEntity(data.actual_closing, entityId)}
          rawAmount={data.actual_closing}
          entityId={entityId}
          subtext={`차이: ${data.diff >= 0 ? "+" : ""}${formatByEntity(data.diff, entityId)}`}
          subtextColor={data.diff >= 0 ? "text-emerald-300" : "text-rose-300"}
          colorClass="text-[hsl(var(--profit))]"
        />
        <KPICard
          label="카드 사용 (진행)"
          value={formatByEntity(data.card_timing.curr_month_card_actual, entityId)}
          rawAmount={data.card_timing.curr_month_card_actual}
          entityId={entityId}
          subtext={`예상 ${formatByEntity(data.forecast_card_usage, entityId)} 중`}
          subtextColor="text-violet-300"
          colorClass="text-[#8B5CF6]"
        />
      </div>

      {/* Missing recurring banner (Decision 1A/2A/3A/4A/5B/6A) */}
      {!missingDismissed && missingRecurring.length > 0 && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3 min-w-0">
              <AlertTriangle className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
              <div className="min-w-0">
                <p className="text-sm font-medium text-amber-200">
                  반복 항목 {missingRecurring.length}개가 이번 달 예상에 빠져있습니다
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {missingRecurring.slice(0, 8).map(item => (
                    <span key={item.internal_account_id} className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-300 border border-amber-500/20">
                      {item.name}
                      {item.txn_count === 0 && <span className="text-[10px] text-amber-500">(거래없음)</span>}
                      {item.txn_count > 0 && <span className="text-[10px] text-muted-foreground">{formatByEntity(item.suggested_amount, entityId)}</span>}
                    </span>
                  ))}
                  {missingRecurring.length > 8 && (
                    <span className="text-xs text-amber-500">+{missingRecurring.length - 8}개</span>
                  )}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Button
                variant="outline"
                size="sm"
                className="text-xs border-amber-500/30 text-amber-300 hover:bg-amber-500/10"
                disabled={missingLoading}
                onClick={async () => {
                  setMissingLoading(true)
                  try {
                    const res = await fetchAPI<{ added: number }>(`/forecasts/add-missing-recurring`, {
                      method: "POST",
                      body: JSON.stringify({
                        entity_id: Number(entityId),
                        year: Number(selectedMonth.split("-")[0]),
                        month: Number(selectedMonth.split("-")[1]),
                        items: missingRecurring.map(i => ({
                          internal_account_id: i.internal_account_id,
                          type: i.inferred_type,
                          amount: i.suggested_amount,
                          name: i.name,
                          payment_method: i.payment_method,
                        })),
                      }),
                    })
                    toast.success(`반복 항목 ${res.added}건 추가 완료`)
                    setMissingRecurring([])
                    fetchForecast(true)
                  } catch {
                    toast.error("반복 항목 추가 실패")
                  } finally {
                    setMissingLoading(false)
                  }
                }}
              >
                <Plus className="h-3.5 w-3.5 mr-1" />
                전부 추가
              </Button>
              <button
                onClick={() => {
                  const [y, m] = selectedMonth.split("-").map(Number)
                  localStorage.setItem(`dismissed-missing-recurring-${entityId}-${y}-${m}`, "1")
                  setMissingDismissed(true)
                }}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                무시
              </button>
            </div>
          </div>
        </div>
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
                      fetchForecast(true)
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
            {(
              <Button
                variant="outline"
                size="sm"
                className="gap-2 text-xs"
                onClick={async () => {
                  const prevMonth = m - 1 > 0 ? m - 1 : 12
                  const prevYear = m - 1 > 0 ? y : y - 1
                  try {
                    const res = await fetchAPI<{ copied: number }>(
                      `/forecasts/copy-recurring?entity_id=${entityId}&source_year=${prevYear}&source_month=${prevMonth}&target_year=${y}&target_month=${m}&amount_source=actual`,
                      { method: "POST" },
                    )
                    if (res.copied > 0) {
                      toast.success(`전월 반복 항목 ${res.copied}건 가져옴`)
                      fetchForecast(true)
                    } else {
                      toast.info("가져올 반복 항목이 없습니다")
                    }
                  } catch { toast.error("반복 항목 가져오기 실패") }
                }}
              >
                <RotateCw className="h-3.5 w-3.5" />
                전월 반복 가져오기
              </Button>
            )}
            <ForecastModal entityId={entityId!} year={y} month={m} onSaved={() => fetchForecast(true)} />
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

                  // 세부 라인/메모 확장 가능 여부
                  const hasLineItems = !isVirtualParent && item.line_items && item.line_items.length > 0
                  const hasNote = !isVirtualParent && !!item.note && item.note.trim().length > 0
                  const canExpandLeaf = hasLineItems || hasNote
                  const isLeafExpanded = canExpandLeaf && expandedLeaves.has(item.id)

                  const rowClickHandler = isVirtualParent && item.internal_account_id
                    ? () => toggleCollapse(item.internal_account_id!)
                    : (!isVirtualParent
                        ? (e: React.MouseEvent) => {
                            if ((e.target as HTMLElement).closest("button, a, input")) return
                            setDetailModalItem(item)
                          }
                        : undefined)

                  const mainRow = (
                    <tr
                      key={item.id}
                      className={cn(
                        "border-t border-border hover:bg-white/[0.02] transition-colors group",
                        depth > 0 && "bg-muted/[0.03]",
                        isVirtualParent && "bg-white/[0.01] cursor-pointer",
                        canExpandLeaf && "cursor-pointer",
                      )}
                      title={!isVirtualParent ? "클릭하여 세부 보기" : (isCollapsed ? "클릭하여 펼치기" : "클릭하여 접기")}
                      onClick={rowClickHandler}
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
                                fetchForecast(true)
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
                              const actual = displayActual!
                              const forecast = displayAmount
                              const pct = forecast !== 0 ? Math.round((actual / forecast) * 100) : 0
                              const isOver = actual > forecast
                              const barWidth = Math.min(pct, 150)
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
                                  fetchForecast(true)
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
                              const actual = item.actual_from_transactions!
                              const forecast = item.forecast_amount
                              const pct = forecast !== 0 ? Math.round((actual / forecast) * 100) : 0
                              const isOver = actual > forecast
                              const barWidth = Math.min(pct, 150)
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
                                  fetchForecast(true)
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

                  if (!canExpandLeaf) return mainRow

                  const expandedRows: React.ReactNode[] = []
                  if (isLeafExpanded && hasLineItems) {
                    item.line_items!.forEach((li, idx) => {
                      expandedRows.push(
                        <tr key={`${item.id}-li-${idx}`} className="border-t border-border/30 bg-white/[0.015]">
                          <td />
                          <td className="px-4 py-1.5" style={{ paddingLeft: `${(depth + 1) * 20 + 28}px` }}>
                            <div className="flex items-center text-xs text-muted-foreground">
                              <span className="text-muted-foreground/40 mr-2">•</span>
                              <span>{li.name || "(이름 없음)"}</span>
                              {li.note && (
                                <span className="ml-2 text-[10px] text-muted-foreground/60">— {li.note}</span>
                              )}
                            </div>
                          </td>
                          <td className={cn(
                            "px-4 py-1.5 text-right font-mono tabular-nums text-xs text-muted-foreground",
                          )}>
                            {item.type === "in" ? "+" : "-"}{formatByEntity(li.amount, entityId)}
                          </td>
                          <td />
                        </tr>
                      )
                    })
                  }
                  if (isLeafExpanded && hasNote) {
                    expandedRows.push(
                      <tr key={`${item.id}-note`} className="border-t border-border/30 bg-white/[0.015]">
                        <td />
                        <td colSpan={3} className="px-4 py-1.5" style={{ paddingLeft: `${(depth + 1) * 20 + 28}px` }}>
                          <span className="text-[11px] text-muted-foreground italic">📝 {item.note}</span>
                        </td>
                      </tr>
                    )
                  }

                  return (
                    <Fragment key={`frag-${item.id}`}>
                      {mainRow}
                      {expandedRows}
                    </Fragment>
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
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums text-xs text-[hsl(var(--warning))]">
                    {formatByEntity(data.predicted_ending, entityId)}
                  </td>
                  {showComparison && <td className="px-4 py-2.5 text-right font-mono tabular-nums text-xs text-muted-foreground">--</td>}
                  <td></td>
                </tr>
              )}

              {/* Closing row — 시계열 합성 기반 예상 기말 */}
              <tr className="border-t-2 border-t-amber-500/15 bg-amber-500/[0.03]">
                <td className="px-4 py-3"></td>
                <td className="px-4 py-3 font-bold">
                  기말 잔고
                  <span className="ml-2 text-[10px] font-normal text-muted-foreground">
                    ({data.as_of_date} 기준 · 실제+남은예상)
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-mono tabular-nums text-xs">--</td>
                {showComparison && <td className="px-4 py-3 text-right font-mono tabular-nums text-xs">--</td>}
                <td className="px-4 py-3 text-right font-mono tabular-nums text-xs text-[hsl(var(--warning))]">
                  {formatByEntity(data.predicted_ending, entityId)}
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
      <Card className="bg-muted/30 rounded-lg overflow-hidden">
        <button
          type="button"
          onClick={() => setFormulaOpen((v) => !v)}
          className="w-full flex items-center gap-2 px-4 py-2.5 text-left hover:bg-muted/50 transition-colors"
        >
          <span className="text-xs font-semibold text-cyan-400 flex-1">조정 예상 기말 공식</span>
          {formulaOpen ? <ChevronDown className="h-4 w-4 text-cyan-400/60" /> : <ChevronRight className="h-4 w-4 text-cyan-400/60" />}
        </button>
        {formulaOpen && (
          <div className="px-4 pb-4 font-mono text-xs leading-relaxed text-cyan-400">
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
          </div>
        )}
      </Card>

      {/* Comparison boxes */}
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        {/* Card timing box (collapsible) */}
        <Card className="bg-secondary rounded-xl overflow-hidden">
          <button
            type="button"
            onClick={() => setCardTimingOpen((v) => !v)}
            className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-secondary/70 transition-colors"
          >
            <span className="text-xs font-semibold text-purple-400">카드 시차</span>
            <span className="flex-1" />
            <span className="text-xs text-muted-foreground">시차 보정</span>
            <span className={cn(
              "text-sm font-mono tabular-nums font-semibold",
              data.card_timing.adjustment >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]",
            )}>
              {data.card_timing.adjustment >= 0 ? "+" : ""}{formatByEntity(data.card_timing.adjustment, entityId)}
            </span>
            {cardTimingOpen ? <ChevronDown className="h-4 w-4 text-purple-400/60" /> : <ChevronRight className="h-4 w-4 text-purple-400/60" />}
          </button>
          {cardTimingOpen && (
            <div className="px-4 pb-4 space-y-2 text-sm">
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
          )}
        </Card>

        {/* Forecast vs actual box (collapsible) */}
        <Card className="bg-secondary rounded-xl overflow-hidden">
          <button
            type="button"
            onClick={() => setVsActualOpen((v) => !v)}
            className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-secondary/70 transition-colors"
          >
            <span className="text-xs font-semibold text-[hsl(var(--warning))]">예상 vs 실제</span>
            <span className="flex-1" />
            <span className="text-xs text-muted-foreground">차이</span>
            <span className={cn("text-sm font-mono tabular-nums font-semibold", diffColor)}>
              {data.diff >= 0 ? "+" : ""}{formatByEntity(data.diff, entityId)}
            </span>
            {data.adjusted_forecast_closing !== 0 && (
              <span className={cn("text-[11px] font-mono tabular-nums", diffColor)}>
                ({(100 - Math.abs(diffPct)).toFixed(1)}%)
              </span>
            )}
            {vsActualOpen ? <ChevronDown className="h-4 w-4 text-[hsl(var(--warning))]/60" /> : <ChevronRight className="h-4 w-4 text-[hsl(var(--warning))]/60" />}
          </button>
          {vsActualOpen && (
            <div className="px-4 pb-4 space-y-2 text-sm">
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
          )}
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
          onSaved={() => { setEditModalItem(null); fetchForecast(true) }}
          editItem={editModalItem}
          open={!!editModalItem}
          onOpenChange={(v) => { if (!v) setEditModalItem(null) }}
        />
      )}

      {/* Detail Modal — 하위항목 클릭 시 세부 보기 */}
      {detailModalItem && (
        <ForecastDetailModal
          item={detailModalItem}
          allItems={data.items}
          entityId={entityId!}
          year={y}
          month={m}
          formatAmount={(v: number) => formatByEntity(v, entityId)}
          onEdit={() => { setEditModalItem(detailModalItem); setDetailModalItem(null) }}
          open={!!detailModalItem}
          onOpenChange={(v) => { if (!v) setDetailModalItem(null) }}
        />
      )}
    </div>
  )
}
