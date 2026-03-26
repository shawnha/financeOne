"use client"

import { useEffect, useState, useCallback } from "react"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Checkbox } from "@/components/ui/checkbox"
import { fetchAPI } from "@/lib/api"
import { formatByEntity } from "@/lib/format"
import {
  Area,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
  Line,
  ComposedChart,
  ReferenceLine,
} from "recharts"
import { AlertCircle, RefreshCw, Plus, Download, ChevronDown, ChevronUp } from "lucide-react"
import { cn } from "@/lib/utils"

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
}

interface CardTiming {
  prev_month_card: number
  curr_month_card_actual: number
  curr_month_card_estimate: number
  adjustment: number
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
  forecast_closing: number
  actual_income: number
  actual_expense: number
  actual_closing: number
  diff: number
  items: ForecastItem[]
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

const CATEGORIES_IN = ["매출", "수수료환급", "이자", "기타입금"]
const CATEGORIES_OUT = ["SaaS", "수수료", "임차료", "교통비", "접대비", "복리후생", "카드사용", "기타"]

// ── Month Nav (reused pattern) ─────────────────────────

function MonthNav({
  months,
  selected,
  onSelect,
  color,
}: {
  months: string[]
  selected: string
  onSelect: (m: string) => void
  color: string
}) {
  const idx = months.indexOf(selected)
  return (
    <div className="flex items-center gap-2">
      <Button variant="ghost" size="sm" disabled={idx <= 0} onClick={() => onSelect(months[idx - 1])} className="h-8 w-8 p-0">◀</Button>
      <div className="flex items-center gap-1.5 overflow-x-auto">
        {months.map((m) => (
          <button
            key={m}
            onClick={() => onSelect(m)}
            className={cn(
              "px-3 py-1 rounded-full text-xs font-medium transition-colors whitespace-nowrap",
              m === selected
                ? "text-white"
                : "bg-muted/30 text-muted-foreground hover:bg-muted/50",
            )}
            style={m === selected ? { backgroundColor: color } : undefined}
          >
            {`${parseInt(m.slice(5))}월`}
          </button>
        ))}
      </div>
      <Button variant="ghost" size="sm" disabled={idx >= months.length - 1} onClick={() => onSelect(months[idx + 1])} className="h-8 w-8 p-0">▶</Button>
    </div>
  )
}

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
      <p className={cn("text-2xl font-bold font-mono tabular-nums mt-1", colorClass)}>{value}</p>
      {subtext && <p className="text-xs text-muted-foreground mt-0.5">{subtext}</p>}
    </Card>
  )
}

// ── Forecast Input Modal ───────────────────────────────

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
  const [amount, setAmount] = useState("")
  const [recurring, setRecurring] = useState(false)
  const [saving, setSaving] = useState(false)

  const categories = type === "in" ? CATEGORIES_IN : CATEGORIES_OUT

  const handleSave = async () => {
    if (!category || !amount) return
    setSaving(true)
    try {
      await fetchAPI("/forecasts", {
        method: "POST",
        body: JSON.stringify({
          entity_id: Number(entityId),
          year,
          month,
          category,
          type,
          forecast_amount: parseFloat(amount),
          is_recurring: recurring,
        }),
      })
      setOpen(false)
      setCategory("")
      setAmount("")
      setRecurring(false)
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
                <input type="radio" checked={type === "in"} onChange={() => { setType("in"); setCategory("") }} className="accent-[hsl(var(--profit))]" />
                <span className="text-sm">입금</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="radio" checked={type === "out"} onChange={() => { setType("out"); setCategory("") }} className="accent-[hsl(var(--loss))]" />
                <span className="text-sm">출금</span>
              </label>
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">카테고리</label>
            <Select value={category} onValueChange={setCategory}>
              <SelectTrigger className="mt-1"><SelectValue placeholder="선택" /></SelectTrigger>
              <SelectContent>
                {categories.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
              </SelectContent>
            </Select>
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
          <label className="flex items-center gap-2 cursor-pointer">
            <Checkbox checked={recurring} onCheckedChange={(v) => setRecurring(!!v)} />
            <span className="text-sm">매월 반복</span>
          </label>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>취소</Button>
            <Button onClick={handleSave} disabled={saving || !category || !amount}>
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
  const [summary, setSummary] = useState<SummaryData | null>(null)
  const [state, setState] = useState<LoadState>("loading")
  const [error, setError] = useState("")
  const [selectedMonth, setSelectedMonth] = useState("")
  const [showComparison, setShowComparison] = useState(false)
  const [showFormula, setShowFormula] = useState(false)

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
      const d = await fetchAPI<ForecastData>(
        `/cashflow/forecast?entity_id=${entityId}&year=${y}&month=${m}`,
        { cache: "no-store" },
      )
      setData(d)
      setState("success")
    } catch (err) {
      setError(err instanceof Error ? err.message : "데이터를 불러올 수 없습니다.")
      setState("error")
    }
  }, [entityId, selectedMonth])

  useEffect(() => { fetchSummary() }, [fetchSummary])
  useEffect(() => { fetchForecast() }, [fetchForecast])

  const months = summary?.available_months ?? []

  // ── LOADING ──
  if (state === "loading" || !selectedMonth) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}
        </div>
        <Skeleton className="h-[300px] rounded-xl" />
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
        <MonthNav months={months} selected={selectedMonth} onSelect={setSelectedMonth} color="hsl(var(--warning))" />
        <div className="flex gap-2">
          <ForecastModal entityId={entityId!} year={y} month={m} onSaved={fetchForecast} />
          <Button variant="outline" size="sm" className="gap-2">
            <Download className="h-4 w-4" /> 내보내기
          </Button>
        </div>
      </div>

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

      {/* Forecast items list */}
      <Card className="overflow-hidden">
        <div className="px-4 py-3 flex items-center justify-between border-b border-border">
          <h3 className="text-sm font-semibold">{m}월 예상 항목</h3>
          <button
            onClick={() => setShowComparison(!showComparison)}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            {showComparison ? "실제 비교 접기 ◂" : "실제 비교 펼치기 ▸"}
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/30 text-xs text-muted-foreground">
                <th className="text-left px-4 py-2">유형</th>
                <th className="text-left px-4 py-2">항목</th>
                <th className="text-right px-4 py-2">예상 금액</th>
                {showComparison && <th className="text-right px-4 py-2">실제 진행</th>}
                <th className="text-right px-4 py-2">예상 잔고</th>
                {showComparison && <th className="text-right px-4 py-2">실제 잔고</th>}
              </tr>
            </thead>
            <tbody>
              {/* Opening row */}
              <tr className="border-t border-border bg-green-500/3">
                <td className="px-4 py-2.5"></td>
                <td className="px-4 py-2.5 font-medium">시작 잔고</td>
                <td className="px-4 py-2.5 text-right font-mono tabular-nums">—</td>
                {showComparison && <td className="px-4 py-2.5"></td>}
                <td className="px-4 py-2.5 text-right font-mono tabular-nums">
                  {formatByEntity(data.opening_balance, entityId)}
                </td>
                {showComparison && (
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums text-[hsl(var(--profit))]">
                    {formatByEntity(data.opening_balance, entityId)}
                  </td>
                )}
              </tr>

              {/* Forecast items */}
              {data.items.map((item) => (
                <tr key={item.id} className="border-t border-border hover:bg-muted/10">
                  <td className="px-4 py-2.5">
                    <Badge variant="outline" className={cn(
                      "text-xs px-2 py-0.5",
                      item.type === "in" ? "bg-green-500/12 text-green-400" : "bg-red-500/12 text-red-400",
                    )}>
                      {item.type === "in" ? "입금" : "출금"}
                    </Badge>
                  </td>
                  <td className="px-4 py-2.5">
                    {item.category}
                    {item.subcategory && <span className="text-muted-foreground ml-1">({item.subcategory})</span>}
                    {item.is_recurring && <span className="text-xs text-muted-foreground ml-2">🔄</span>}
                  </td>
                  <td className={cn(
                    "px-4 py-2.5 text-right font-mono tabular-nums",
                    item.type === "in" ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]",
                  )}>
                    {item.type === "in" ? "+" : "-"}{formatByEntity(item.forecast_amount, entityId)}
                  </td>
                  {showComparison && (
                    <td className="px-4 py-2.5 text-right font-mono tabular-nums text-[hsl(var(--profit))]">
                      {item.actual_amount != null ? formatByEntity(item.actual_amount, entityId) : "—"}
                    </td>
                  )}
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums text-[hsl(var(--warning))]">—</td>
                  {showComparison && <td className="px-4 py-2.5"></td>}
                </tr>
              ))}

              {/* Timing adjustment row */}
              {data.card_timing.adjustment !== 0 && (
                <tr className="border-t border-border bg-purple-500/3">
                  <td className="px-4 py-2.5">
                    <Badge variant="outline" className="text-xs px-2 py-0.5 bg-amber-500/12 text-amber-400">시차보정</Badge>
                  </td>
                  <td className="px-4 py-2.5">카드 시차 보정</td>
                  <td className={cn(
                    "px-4 py-2.5 text-right font-mono tabular-nums",
                    data.card_timing.adjustment >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]",
                  )}>
                    {data.card_timing.adjustment >= 0 ? "+" : ""}{formatByEntity(data.card_timing.adjustment, entityId)}
                  </td>
                  {showComparison && <td className="px-4 py-2.5"></td>}
                  <td className="px-4 py-2.5"></td>
                  {showComparison && <td className="px-4 py-2.5"></td>}
                </tr>
              )}

              {/* Closing row */}
              <tr className="border-t-2 border-t-[hsl(var(--warning))] bg-amber-500/3">
                <td className="px-4 py-2.5"></td>
                <td className="px-4 py-2.5 font-medium">기말 잔고</td>
                <td className="px-4 py-2.5 text-right font-mono tabular-nums">—</td>
                {showComparison && <td className="px-4 py-2.5"></td>}
                <td className="px-4 py-2.5 text-right font-mono tabular-nums text-[hsl(var(--warning))]">
                  {formatByEntity(data.forecast_closing, entityId)}
                </td>
                {showComparison && (
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums text-[hsl(var(--profit))]">
                    {formatByEntity(data.actual_closing, entityId)}
                  </td>
                )}
              </tr>

              {data.items.length === 0 && (
                <tr>
                  <td colSpan={showComparison ? 6 : 4} className="px-4 py-8 text-center text-muted-foreground">
                    예상 항목을 추가해보세요
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Formula (collapsible) */}
      <details>
        <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground transition-colors">
          계산 방법 ▸
        </summary>
        <Card className="mt-2 p-4 bg-muted/30 font-mono text-xs leading-relaxed text-cyan-400">
          <p>{m}월 예상 기말 = {m - 1 || 12}월 확정 기말</p>
          <p className="ml-4">+ {m}월 예상 입금</p>
          <p className="ml-4">- {m}월 예상 출금</p>
          <p className="ml-4">- {m}월 예상 카드 사용액</p>
          <p className="ml-4 text-amber-400">+ ({m - 1 || 12}월 카드 사용액 - {m}월 예상 카드 사용액) ← 시차 보정</p>
        </Card>
      </details>

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
