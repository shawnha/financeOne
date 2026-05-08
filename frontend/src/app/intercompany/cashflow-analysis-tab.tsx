"use client"

import { useEffect, useState, useMemo, useCallback } from "react"
import {
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
  ComposedChart,
  Cell,
  ReferenceLine,
} from "recharts"
import { ArrowDownToLine, TrendingUp, ShoppingCart } from "lucide-react"

import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { fetchAPI } from "@/lib/api"
import { formatByEntity, abbreviateAmount } from "@/lib/format"
import { cn } from "@/lib/utils"

// ── Types ──────────────────────────────────────────────

interface PnlDailyRow {
  day: number
  revenue: number
  sales_count: number
  purchases: number
  purchases_count: number
}

interface PnlDailyResponse {
  year: number
  month: number
  rows: PnlDailyRow[]
}

interface ActualRow {
  type: string
  date: string | null
  description: string
  counterparty?: string
  amount: number
  balance: number
  tx_id: number | null
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

interface LoanEvent {
  day: number
  date: string
  amount: number
  description: string
  counterparty: string
}

interface DailyPoint {
  day: number
  revenue: number
  purchases: number
  loanIn: number  // 차입 입금 (해당일)
}

// 법인 메타 — 사이드바 hardcode 와 동일
const LENDERS = [
  { id: 2, code: "HOK", name: "한아원코리아", currency: "KRW" },
]
const BORROWERS = [
  { id: 13, code: "WHL", name: "한아원홀세일 (도팜인)", currency: "KRW" },
]

// 한아원코리아 → 홀세일 차입금 식별 패턴 (counterparty 기준)
const HOK_LENDER_PATTERN = /주식회사\s*한아|한아원코리아/

function DailyTooltip({
  active,
  payload,
  month,
  borrowerId,
  lenderCode,
  firstLoanDay,
}: {
  active?: boolean
  payload?: Array<{ payload: DailyPoint }>
  month: number
  borrowerId: number
  lenderCode: string
  firstLoanDay: number | null
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="rounded-lg bg-popover border border-border px-3 py-2 shadow-lg text-xs space-y-0.5">
      <p className="text-muted-foreground mb-1">
        {month}월 {p.day}일{firstLoanDay != null && p.day >= firstLoanDay ? " · 차입 이후" : " · 차입 이전"}
      </p>
      {p.revenue > 0 && <p className="font-mono tabular-nums text-cyan-400">매출: {formatByEntity(p.revenue, String(borrowerId))}</p>}
      {p.purchases > 0 && <p className="font-mono tabular-nums text-pink-400">매입: {formatByEntity(p.purchases, String(borrowerId))}</p>}
      {p.loanIn > 0 && (
        <p className="font-mono tabular-nums text-violet-300 pt-0.5 border-t border-border/40 mt-1">
          {lenderCode} 차입: +{formatByEntity(p.loanIn, String(borrowerId))}
        </p>
      )}
    </div>
  )
}

function CumulativeTooltip({
  active,
  payload,
  label,
  month,
  borrowerId,
}: {
  active?: boolean
  payload?: Array<{ value: number; name: string; color: string }>
  label?: string | number
  month: number
  borrowerId: number
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg bg-popover border border-border px-3 py-2 shadow-lg text-xs space-y-0.5">
      <p className="text-muted-foreground mb-1">{month}월 {label}일 누계</p>
      {payload.map((e) => (
        <p key={e.name} className="font-mono tabular-nums" style={{ color: e.color }}>
          {e.name}: {formatByEntity(e.value, String(borrowerId))}
        </p>
      ))}
    </div>
  )
}

// ──────────────────────────────────────────────────────

export function CashflowAnalysisTab() {
  const [lenderId] = useState(2) // HOK
  const [borrowerId] = useState(13) // 홀세일
  const [year, setYear] = useState(2026)
  const [month, setMonth] = useState(4)

  const [loanData, setLoanData] = useState<ActualData | null>(null)
  const [pnlData, setPnlData] = useState<PnlDailyResponse | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [a, p] = await Promise.all([
        fetchAPI<ActualData>(
          `/cashflow/actual?entity_id=${borrowerId}&year=${year}&month=${month}`,
          { cache: "no-store" },
        ),
        fetchAPI<PnlDailyResponse>(
          `/pnl/daily?entity_id=${borrowerId}&year=${year}&month=${month}`,
          { cache: "no-store" },
        ),
      ])
      setLoanData(a)
      setPnlData(p)
    } finally {
      setLoading(false)
    }
  }, [borrowerId, year, month])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const lender = LENDERS.find((l) => l.id === lenderId)!
  const borrower = BORROWERS.find((b) => b.id === borrowerId)!

  // 차입 events 추출
  const loanEvents = useMemo<LoanEvent[]>(() => {
    if (!loanData) return []
    return loanData.rows
      .filter(
        (r) =>
          r.type === "in" &&
          r.internal_account_name === "차입금" &&
          r.counterparty != null &&
          HOK_LENDER_PATTERN.test(r.counterparty),
      )
      .map((r) => ({
        day: parseInt((r.date ?? "").slice(8, 10)),
        date: r.date ?? "",
        amount: r.amount,
        description: r.description,
        counterparty: r.counterparty ?? "",
      }))
      .filter((e) => e.day >= 1 && e.day <= 31)
      .sort((a, b) => a.day - b.day)
  }, [loanData])

  const totalLoans = loanEvents.reduce((s, l) => s + l.amount, 0)
  const firstLoanDay = loanEvents[0]?.day ?? null
  const lastDayOfMonth = useMemo(() => new Date(year, month, 0).getDate(), [year, month])

  // 일별 차트 데이터
  const dailyData = useMemo<DailyPoint[]>(() => {
    const pnlMap = new Map<number, { revenue: number; purchases: number }>()
    if (pnlData) {
      for (const r of pnlData.rows) {
        pnlMap.set(r.day, { revenue: r.revenue, purchases: r.purchases })
      }
    }
    const loanMap = new Map<number, number>()
    for (const e of loanEvents) {
      loanMap.set(e.day, (loanMap.get(e.day) ?? 0) + e.amount)
    }
    const out: DailyPoint[] = []
    for (let d = 1; d <= lastDayOfMonth; d++) {
      const pnl = pnlMap.get(d) ?? { revenue: 0, purchases: 0 }
      out.push({ day: d, ...pnl, loanIn: loanMap.get(d) ?? 0 })
    }
    return out
  }, [pnlData, loanEvents, lastDayOfMonth])

  // 차입 이후 매출/매입 누계
  const postLoanStats = useMemo(() => {
    if (firstLoanDay == null || !pnlData) return null
    let postRev = 0
    let postPur = 0
    let preRev = 0
    let prePur = 0
    for (const r of pnlData.rows) {
      if (r.day >= firstLoanDay) {
        postRev += r.revenue
        postPur += r.purchases
      } else {
        preRev += r.revenue
        prePur += r.purchases
      }
    }
    const preDays = Math.max(firstLoanDay - 1, 1)
    const postDays = Math.max(lastDayOfMonth - firstLoanDay + 1, 1)
    return {
      preRev,
      prePur,
      postRev,
      postPur,
      preDailyRev: preRev / preDays,
      preDailyPur: prePur / preDays,
      postDailyRev: postRev / postDays,
      postDailyPur: postPur / postDays,
      preDays,
      postDays,
    }
  }, [pnlData, firstLoanDay, lastDayOfMonth])

  return (
    <div className="space-y-6">
      {/* Pair selector + period */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-3 text-sm">
          <Card className="px-3 py-2 bg-secondary/40 border-border/40">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground mr-2">
              자금 출처
            </span>
            <span className="font-medium text-violet-300">{lender.code} {lender.name}</span>
          </Card>
          <ArrowDownToLine className="h-4 w-4 text-muted-foreground" />
          <Card className="px-3 py-2 bg-secondary/40 border-border/40">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground mr-2">
              자금 수령
            </span>
            <span className="font-medium">{borrower.name}</span>
          </Card>
          <span className="text-[11px] text-muted-foreground ml-2">
            (다른 pair 는 향후 확장)
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Select value={String(year)} onValueChange={(v) => setYear(Number(v))}>
            <SelectTrigger className="w-[100px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              {[2025, 2026].map((y) => (
                <SelectItem key={y} value={String(y)}>{y}년</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={String(month)} onValueChange={(v) => setMonth(Number(v))}>
            <SelectTrigger className="w-[90px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                <SelectItem key={m} value={String(m)}>{m}월</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {loading ? (
        <Skeleton className="h-[400px] w-full rounded-2xl" />
      ) : loanEvents.length === 0 ? (
        <Card className="p-8 text-center">
          <p className="text-base font-medium text-muted-foreground">
            {year}년 {month}월 — {lender.code} → {borrower.code} 차입 내역 없음
          </p>
          <p className="text-xs text-muted-foreground mt-2">
            다른 월을 선택하거나 차입 거래 매핑을 확인하세요.
          </p>
        </Card>
      ) : (
        <>
          {/* KPI 4개 — 차입 합계 / 차입 이후 매출/매입 / 비교 */}
          <div className="grid grid-cols-4 gap-3 max-md:grid-cols-2">
            <Card className="bg-violet-500/[0.06] border-violet-500/30 rounded-xl p-4">
              <p className="text-[10px] uppercase tracking-wider text-violet-300/80">
                {lender.code} 차입 합계 ({loanEvents.length}건)
              </p>
              <p className="text-xl md:text-2xl font-bold font-mono tabular-nums text-violet-200 mt-1">
                {formatByEntity(totalLoans, String(borrowerId))}
              </p>
              <p className="text-[10px] text-muted-foreground mt-1">
                {loanEvents.map((l) => `${l.day}일`).join(" · ")}
              </p>
            </Card>
            <Card className="rounded-xl p-4 bg-secondary">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                차입 이후 매출
              </p>
              <p className="text-xl md:text-2xl font-bold font-mono tabular-nums text-cyan-400 mt-1">
                {formatByEntity(postLoanStats?.postRev ?? 0, String(borrowerId))}
              </p>
              <p className="text-[10px] text-muted-foreground mt-1">
                {firstLoanDay}일~{lastDayOfMonth}일 ({postLoanStats?.postDays}일)
                {postLoanStats && postLoanStats.preDailyRev > 0 && (
                  <span className="ml-1">
                    · 일평균 {postLoanStats.postDailyRev > postLoanStats.preDailyRev ? "↑" : "↓"}
                    {(((postLoanStats.postDailyRev - postLoanStats.preDailyRev) / postLoanStats.preDailyRev) * 100).toFixed(0)}%
                  </span>
                )}
              </p>
            </Card>
            <Card className="rounded-xl p-4 bg-secondary">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                차입 이후 매입
              </p>
              <p className="text-xl md:text-2xl font-bold font-mono tabular-nums text-pink-400 mt-1">
                {formatByEntity(postLoanStats?.postPur ?? 0, String(borrowerId))}
              </p>
              <p className="text-[10px] text-muted-foreground mt-1">
                {firstLoanDay}일~{lastDayOfMonth}일
                {postLoanStats && postLoanStats.preDailyPur > 0 && (
                  <span className="ml-1">
                    · 일평균 {postLoanStats.postDailyPur > postLoanStats.preDailyPur ? "↑" : "↓"}
                    {(((postLoanStats.postDailyPur - postLoanStats.preDailyPur) / postLoanStats.preDailyPur) * 100).toFixed(0)}%
                  </span>
                )}
              </p>
            </Card>
            <Card className="rounded-xl p-4 bg-secondary">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                차입 이전 비교
              </p>
              <p className="text-sm font-mono tabular-nums mt-2 space-y-0.5">
                <span className="block">
                  매출 일평균: <span className="text-cyan-300">{abbreviateAmount(postLoanStats?.preDailyRev ?? 0)}</span> → <span className="text-cyan-200">{abbreviateAmount(postLoanStats?.postDailyRev ?? 0)}</span>
                </span>
                <span className="block">
                  매입 일평균: <span className="text-pink-300">{abbreviateAmount(postLoanStats?.preDailyPur ?? 0)}</span> → <span className="text-pink-200">{abbreviateAmount(postLoanStats?.postDailyPur ?? 0)}</span>
                </span>
              </p>
            </Card>
          </div>

          {/* Loan list */}
          <Card className="overflow-hidden rounded-2xl">
            <div className="px-4 py-3 border-b border-border">
              <h3 className="text-base font-semibold">차입 내역</h3>
            </div>
            <div className="divide-y divide-border/40">
              {loanEvents.map((e, i) => (
                <div key={i} className="grid grid-cols-[100px_140px_1fr_180px] px-4 py-2.5 items-center text-sm">
                  <span className="font-mono text-muted-foreground">{e.date}</span>
                  <span className="text-violet-300">{lender.code} {lender.name}</span>
                  <span className="truncate text-muted-foreground">{e.description}</span>
                  <span className="text-right font-mono tabular-nums font-bold text-violet-200">
                    {formatByEntity(e.amount, String(borrowerId))}
                  </span>
                </div>
              ))}
              <div className="grid grid-cols-[100px_140px_1fr_180px] px-4 py-3 items-center text-sm bg-violet-500/[0.04] font-semibold">
                <span></span>
                <span></span>
                <span className="text-right text-muted-foreground">합계</span>
                <span className="text-right font-mono tabular-nums text-violet-200">
                  {formatByEntity(totalLoans, String(borrowerId))}
                </span>
              </div>
            </div>
          </Card>

          {/* 일별 매출/매입 + 차입 marker */}
          <Card className="p-6 rounded-2xl">
            <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
              <h3 className="text-sm font-medium">
                일별 매출/매입 추이 ({month}월)
              </h3>
              <p className="text-[11px] text-muted-foreground">
                wholesale_sales / wholesale_purchases 발생주의 base · 차입 시점 보라 marker
              </p>
            </div>
            <div className="h-[280px] max-md:h-[220px]">
              <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <ComposedChart data={dailyData} margin={{ top: 24, right: 12, left: 12, bottom: 5 }}>
                  <defs>
                    <linearGradient id="revGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#06b6d4" stopOpacity={0.7} />
                      <stop offset="100%" stopColor="#06b6d4" stopOpacity={0.05} />
                    </linearGradient>
                    <linearGradient id="purGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#ec4899" stopOpacity={0.7} />
                      <stop offset="100%" stopColor="#ec4899" stopOpacity={0.05} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="4 4" stroke="rgba(255,255,255,0.04)" vertical={false} />
                  <XAxis dataKey="day" tick={{ fill: "#64748b", fontSize: 10 }} interval={2} axisLine={{ stroke: "rgba(255,255,255,0.06)" }} tickLine={false} />
                  <YAxis tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v) => abbreviateAmount(v)} width={60} />
                  <RechartsTooltip content={<DailyTooltip month={month} borrowerId={borrowerId} lenderCode={lender.code} firstLoanDay={firstLoanDay} />} />
                  {/* 차입 marker */}
                  {loanEvents.map((e, i) => (
                    <ReferenceLine
                      key={`loan-${i}`}
                      x={e.day}
                      stroke="#a78bfa"
                      strokeDasharray="4 4"
                      strokeWidth={1.5}
                      label={{ value: `${lender.code} ${abbreviateAmount(e.amount)}`, position: "top", fill: "#c4b5fd", fontSize: 10, fontWeight: 600 }}
                    />
                  ))}
                  <Bar dataKey="revenue" name="매출" fill="#06b6d4" radius={[4, 4, 0, 0]} barSize={8} animationDuration={300}>
                    {dailyData.map((_, i) => <Cell key={`r-${i}`} fill="url(#revGradient)" stroke="#06b6d4" strokeWidth={0.5} />)}
                  </Bar>
                  <Bar dataKey="purchases" name="매입" fill="#ec4899" radius={[4, 4, 0, 0]} barSize={8} animationDuration={300}>
                    {dailyData.map((_, i) => <Cell key={`p-${i}`} fill="url(#purGradient)" stroke="#ec4899" strokeWidth={0.5} />)}
                  </Bar>
                  <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }} formatter={(v: string) => <span style={{ color: "#94a3b8", fontSize: 11 }}>{v}</span>} iconType="circle" iconSize={8} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </Card>

          {/* 차입 이후 누적 추이 (line chart) */}
          {postLoanStats && (
            <Card className="p-6 rounded-2xl">
              <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                <h3 className="text-sm font-medium">
                  차입 이후 매출/매입 누적 추이
                </h3>
                <p className="text-[11px] text-muted-foreground">
                  {firstLoanDay}일부터 누계
                </p>
              </div>
              <div className="h-[200px]">
                <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                  <ComposedChart
                    data={(() => {
                      let cr = 0
                      let cp = 0
                      return dailyData
                        .filter((d) => firstLoanDay != null && d.day >= firstLoanDay)
                        .map((d) => {
                          cr += d.revenue
                          cp += d.purchases
                          return { day: d.day, cumRev: cr, cumPur: cp }
                        })
                    })()}
                    margin={{ top: 10, right: 12, left: 12, bottom: 5 }}
                  >
                    <CartesianGrid strokeDasharray="4 4" stroke="rgba(255,255,255,0.04)" vertical={false} />
                    <XAxis dataKey="day" tick={{ fill: "#64748b", fontSize: 10 }} axisLine={{ stroke: "rgba(255,255,255,0.06)" }} tickLine={false} />
                    <YAxis tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v) => abbreviateAmount(v)} width={60} />
                    <RechartsTooltip content={<CumulativeTooltip month={month} borrowerId={borrowerId} />} />
                    <Line type="monotone" dataKey="cumRev" name="누적 매출" stroke="#06b6d4" strokeWidth={2} dot={{ r: 2 }} animationDuration={300} />
                    <Line type="monotone" dataKey="cumPur" name="누적 매입" stroke="#ec4899" strokeWidth={2} dot={{ r: 2 }} animationDuration={300} />
                    <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }} formatter={(v: string) => <span style={{ color: "#94a3b8", fontSize: 11 }}>{v}</span>} iconType="circle" iconSize={8} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
