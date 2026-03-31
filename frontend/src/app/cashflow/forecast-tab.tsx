"use client"

import { useEffect, useState, useCallback, useMemo } from "react"
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
import { AlertCircle, RefreshCw, Plus, Download, Trash2 } from "lucide-react"
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
  actual_from_transactions: number | null
  expected_day: number | null
  payment_method: string
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
  actual_income: number
  actual_expense: number
  actual_closing: number
  diff: number
  items: ForecastItem[]
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

type LoadState = "loading" | "empty" | "error" | "success"


// ── KPI Card ───────────────────────────────────────────

function KPICard({
  label,
  value,
  subtext,
  colorClass,
  subtextColor,
}: {
  label: string
  value: string
  subtext?: string
  colorClass?: string
  subtextColor?: string
}) {
  return (
    <Card className="bg-secondary rounded-xl p-4">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={cn("text-[17px] font-semibold font-mono tabular-nums mt-1", colorClass)}>{value}</p>
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
    const today = new Date()
    const currentDay = today.getFullYear() === schedule.year && today.getMonth() + 1 === schedule.month
      ? today.getDate() : (schedule.month < today.getMonth() + 1 || schedule.year < today.getFullYear() ? schedule.points.length : 0)

    const actualDailyChange = currentDay > 0
      ? (forecastData.actual_closing - forecastData.opening_balance) / currentDay
      : 0

    const points = schedule.points.map((p) => ({
      day: `${month}/${p.day}`,
      estimated: p.balance,
      actual: p.day <= currentDay
        ? Math.round(forecastData.opening_balance + actualDailyChange * p.day)
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
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={chartData.points} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
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
                  <p className="text-[#F59E0B]">예상: ₩{point?.estimated?.toLocaleString()}</p>
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
          {/* Estimated balance (amber dashed + area) */}
          <Area
            type="monotone"
            dataKey="estimated"
            fill="url(#forecastEstGrad)"
            stroke="#F59E0B"
            strokeWidth={2}
            strokeDasharray="8 4"
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
          {/* Actual balance (green solid + area) */}
          <Area
            type="monotone"
            dataKey="actual"
            fill="url(#forecastActGrad)"
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
          <span className="inline-block w-2 h-2 rounded-full bg-[#F59E0B]" />
          예상 잔고 (시차보정 포함)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-2 h-2 rounded-full bg-[#22C55E]" style={{ boxShadow: "0 0 6px #22C55E" }} />
          실제 잔고 (업로드마다 업데이트)
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
}

function ForecastModal({
  entityId,
  year,
  month,
  onSaved,
}: {
  entityId: string
  year: number
  month: number
  onSaved: () => void
}) {
  const [open, setOpen] = useState(false)
  const [type, setType] = useState<"in" | "out">("in")
  const [category, setCategory] = useState("")
  const [selectedAccountId, setSelectedAccountId] = useState("")
  const [internalAccounts, setInternalAccounts] = useState<InternalAccount[]>([])
  const [amount, setAmount] = useState("")
  const [recurring, setRecurring] = useState(false)
  const [expectedDay, setExpectedDay] = useState("")
  const [paymentMethod, setPaymentMethod] = useState<"bank" | "card">("bank")
  const [saving, setSaving] = useState(false)

  // Fetch internal accounts on mount
  useEffect(() => {
    if (!entityId) return
    fetchAPI<InternalAccount[]>(
      `/internal-accounts?entity_id=${entityId}`,
      { cache: "no-store" },
    ).then(setInternalAccounts).catch(() => {})
  }, [entityId])

  const selectedAccount = internalAccounts.find((a) => String(a.id) === selectedAccountId)

  const handleSave = async () => {
    if ((!category && !selectedAccountId) || !amount) return
    setSaving(true)
    try {
      await fetchAPI("/forecasts", {
        method: "POST",
        body: JSON.stringify({
          entity_id: Number(entityId),
          year,
          month,
          category: selectedAccount?.name ?? category,
          type,
          forecast_amount: parseFloat(amount),
          is_recurring: recurring,
          internal_account_id: selectedAccountId ? Number(selectedAccountId) : null,
          expected_day: expectedDay ? Number(expectedDay) : null,
          payment_method: paymentMethod,
        }),
      })
      setOpen(false)
      setCategory("")
      setSelectedAccountId("")
      setAmount("")
      setRecurring(false)
      setExpectedDay("")
      setPaymentMethod("bank")
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2">
          <Plus className="h-4 w-4" /> 항목 추가
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-[400px]">
        <DialogHeader>
          <DialogTitle>예상 항목 추가</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 mt-2">
          <div>
            <label className="text-xs text-muted-foreground">월</label>
            <p className="font-medium">{year}년 {month}월</p>
          </div>
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
          </div>
          <div>
            <label className="text-xs text-muted-foreground">금액</label>
            <Input
              type="number"
              placeholder="0"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="mt-1 font-mono"
            />
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
  const [selectedMonth, setSelectedMonth] = useState("")
  const [showComparison, setShowComparison] = useState(false)

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
        setSelectedMonth(s.available_months[s.available_months.length - 1])
      }
    } catch {
      // Summary is optional, forecast still works
    }
  }, [entityId]) // eslint-disable-line react-hooks/exhaustive-deps

  const fetchForecast = useCallback(async () => {
    if (!entityId || !selectedMonth) return
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
      setData(d)
      setSchedule(s)
      setState("success")
    } catch (err) {
      setError(err instanceof Error ? err.message : "데이터를 불러올 수 없습니다.")
      setState("error")
    }
  }, [entityId, selectedMonth])

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

  const diffPct = data.forecast_closing !== 0
    ? ((data.actual_closing - data.forecast_closing) / Math.abs(data.forecast_closing) * 100)
    : 0
  const diffColor = Math.abs(diffPct) <= 5 ? "text-[hsl(var(--profit))]" : Math.abs(diffPct) <= 10 ? "text-[hsl(var(--warning))]" : "text-[hsl(var(--loss))]"

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <MonthPicker months={months} selected={selectedMonth} onSelect={setSelectedMonth} accentColor="hsl(var(--warning))" allowFuture />
        <div className="flex gap-2">
          <ForecastModal entityId={entityId!} year={y} month={m} onSaved={fetchForecast} />
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
        <KPICard label={`기초 (${m - 1 || 12}월 확정)`} value={formatByEntity(data.opening_balance, entityId)} />
        <KPICard label="예상 기말" value={formatByEntity(data.forecast_closing, entityId)} colorClass="text-[hsl(var(--warning))]" />
        <KPICard
          label="실제 진행 기준 기말"
          value={formatByEntity(data.actual_closing, entityId)}
          subtext={`차이: ${data.diff >= 0 ? "+" : ""}${formatByEntity(data.diff, entityId)}`}
          colorClass="text-[hsl(var(--profit))]"
        />
        <KPICard
          label="카드 사용 (진행)"
          value={formatByEntity(data.card_timing.curr_month_card_actual, entityId)}
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
          <h3 className="text-sm font-semibold">{m}월 예상 항목</h3>
          <button
            onClick={() => setShowComparison(!showComparison)}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors bg-muted/30 border border-border px-3 py-1.5 rounded-lg"
          >
            {showComparison ? "실제 비교 접기 \u25C2" : "실제 비교 펼치기 \u25B8"}
          </button>
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

              {/* Forecast items */}
              {data.items.map((item) => {
                const actual = item.actual_from_transactions
                const diff = actual != null ? actual - item.forecast_amount : null
                const diffRatio = item.forecast_amount !== 0 && actual != null
                  ? (actual / item.forecast_amount) * 100
                  : null

                return (
                  <tr key={item.id} className="border-t border-border hover:bg-white/[0.02] transition-colors group">
                    <td className="px-4 py-2.5">
                      <Badge variant="outline" className={cn(
                        "text-[10px] font-semibold px-2 py-0.5",
                        item.type === "in" ? "bg-green-500/12 text-green-400" : "bg-red-500/12 text-red-400",
                      )}>
                        {item.type === "in" ? "입금" : "출금"}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5">
                      {item.internal_account_name ?? item.category}
                      {item.subcategory && <span className="text-muted-foreground ml-1">({item.subcategory})</span>}
                      {item.is_recurring && <span className="text-xs text-muted-foreground ml-2">반복</span>}
                    </td>
                    <td className={cn(
                      "px-4 py-2.5 text-right font-mono tabular-nums text-xs",
                      item.type === "in" ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]",
                    )}>
                      {item.type === "in" ? "+" : "-"}{formatByEntity(item.forecast_amount, entityId)}
                    </td>
                    {showComparison && (
                      <td className="px-4 py-2.5 text-right font-mono tabular-nums text-xs">
                        {actual != null
                          ? <span className={item.type === "in" ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}>
                              {item.type === "in" ? "+" : "-"}{formatByEntity(actual, entityId)}
                            </span>
                          : <span className="text-muted-foreground">--</span>}
                      </td>
                    )}
                    <td className="px-4 py-2.5 text-right font-mono tabular-nums text-xs text-[hsl(var(--warning))]">--</td>
                    {showComparison && <td className="px-4 py-2.5 text-right font-mono tabular-nums text-xs"></td>}
                    <td className="px-2 py-2.5">
                      <button
                        onClick={async () => {
                          if (!confirm(`"${item.internal_account_name ?? item.category}" 항목을 삭제하시겠습니까?`)) return
                          try {
                            await fetchAPI(`/forecasts/${item.id}`, { method: "DELETE" })
                            fetchForecast()
                          } catch { /* toast handled by fetchAPI */ }
                        }}
                        className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                        title="삭제"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                )
              })}

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
                  {formatByEntity(data.forecast_closing, entityId)}
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
        <p>{m}월 예상 기말 = {m - 1 || 12}월 확정 기말</p>
        <p className="ml-4">+ {m}월 예상 입금</p>
        <p className="ml-4">- {m}월 예상 출금</p>
        <p className="ml-4">- {m}월 예상 카드 사용액</p>
        <p className="ml-4 text-amber-400">+ ({m - 1 || 12}월 카드 사용액 - {m}월 예상 카드 사용액) &larr; 시차 보정</p>
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
              <span className="text-muted-foreground">예상 기말</span>
              <span className="font-mono tabular-nums text-[hsl(var(--warning))]">{formatByEntity(data.forecast_closing, entityId)}</span>
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
            {data.forecast_closing !== 0 && (
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
    </div>
  )
}
