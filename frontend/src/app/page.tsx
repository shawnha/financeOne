"use client"

import { useEffect, useState, useCallback, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { EntityTabs } from "@/components/entity-tabs"
import { fetchAPI } from "@/lib/api"
import { formatKRW } from "@/lib/format"
import {
  BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip,
  ResponsiveContainer, CartesianGrid, Legend,
} from "recharts"
import {
  ArrowUpRight, ArrowDownRight, TrendingUp,
  Upload, AlertCircle, RefreshCw, ChevronRight,
} from "lucide-react"

// ── Types ──────────────────────────────────────────────

interface KPI {
  total_balance: number
  monthly_income: number
  monthly_expense: number
  runway_months: number | null
  income_change_pct: number | null
  expense_change_pct: number | null
}

interface CashFlowPoint {
  month: string
  income: number
  expense: number
  net: number
}

interface Transaction {
  id: number
  date: string
  description: string
  amount: number
  type: string
  source_type: string
  is_confirmed: boolean
  mapping_confidence: number | null
  standard_account_name: string | null
}

interface Counts {
  total: number
  unconfirmed: number
  unmapped: number
}

interface DashboardData {
  kpi: KPI
  cash_flow: CashFlowPoint[]
  recent_transactions: Transaction[]
  counts: Counts
}

type LoadState = "loading" | "empty" | "error" | "success" | "partial"

// ── Helpers ────────────────────────────────────────────

function TrendIndicator({
  value,
  invertColor = false,
}: {
  value: number | null
  invertColor?: boolean
}) {
  if (value === null || value === undefined) return null

  const isPositive = value >= 0
  const isGood = invertColor ? !isPositive : isPositive

  return (
    <span
      className={`inline-flex items-center gap-0.5 text-xs font-medium ${
        isGood ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"
      }`}
    >
      {isPositive ? (
        <ArrowUpRight className="h-3 w-3" />
      ) : (
        <ArrowDownRight className="h-3 w-3" />
      )}
      {Math.abs(value).toFixed(1)}%
    </span>
  )
}

// ── Skeletons ──────────────────────────────────────────

function KPISkeleton() {
  return (
    <Card className="bg-card rounded-xl p-6 shadow">
      <Skeleton className="h-3 w-20 mb-3" />
      <Skeleton className="h-8 w-36 mb-2" />
      <Skeleton className="h-3 w-16" />
    </Card>
  )
}

function ChartSkeleton() {
  return (
    <Card className="bg-card rounded-xl p-6 shadow col-span-1 lg:col-span-2">
      <Skeleton className="h-5 w-24 mb-4" />
      <Skeleton className="h-[300px] w-full rounded-lg" />
    </Card>
  )
}

function TransactionListSkeleton() {
  return (
    <Card className="bg-card rounded-xl p-6 shadow">
      <Skeleton className="h-5 w-24 mb-4" />
      <div className="space-y-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex justify-between">
            <div>
              <Skeleton className="h-4 w-32 mb-1" />
              <Skeleton className="h-3 w-20" />
            </div>
            <Skeleton className="h-4 w-20" />
          </div>
        ))}
      </div>
    </Card>
  )
}

function QuickActionsSkeleton() {
  return (
    <Card className="bg-card rounded-xl p-6 shadow">
      <Skeleton className="h-5 w-24 mb-4" />
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full rounded" />
        ))}
      </div>
    </Card>
  )
}

function DashboardSkeleton() {
  return (
    <div className="p-6 space-y-6">
      <Skeleton className="h-8 w-48 mb-2" />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <KPISkeleton key={i} />
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <ChartSkeleton />
        <TransactionListSkeleton />
        <QuickActionsSkeleton />
      </div>
    </div>
  )
}

// ── KPI Card ───────────────────────────────────────────

function KPICard({
  label,
  value,
  trend,
  invertColor = false,
}: {
  label: string
  value: string
  trend?: number | null
  invertColor?: boolean
}) {
  return (
    <Card className="bg-card rounded-xl p-6 shadow" data-testid="kpi-card">
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <p className="text-[28px] font-mono font-bold tabular-nums leading-tight">
        {value}
      </p>
      {trend !== undefined && (
        <div className="mt-2">
          <TrendIndicator value={trend ?? null} invertColor={invertColor} />
        </div>
      )}
    </Card>
  )
}

// ── Custom Tooltip ─────────────────────────────────────

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
          {entry.name}: {formatKRW(entry.value)}
        </p>
      ))}
    </div>
  )
}

// ── Dashboard Content ──────────────────────────────────

function DashboardContent() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity")

  const [data, setData] = useState<DashboardData | null>(null)
  const [state, setState] = useState<LoadState>("loading")
  const [errorMessage, setErrorMessage] = useState("")

  const fetchData = useCallback(async () => {
    if (!entityId) return
    setState("loading")
    setErrorMessage("")

    try {
      const result = await fetchAPI<DashboardData>(
        `/dashboard?entity_id=${entityId}`,
        { cache: "no-store" },
      )
      setData(result)

      const isEmpty =
        result.kpi.total_balance === 0 &&
        result.kpi.monthly_income === 0 &&
        result.kpi.monthly_expense === 0 &&
        result.cash_flow.length === 0 &&
        result.recent_transactions.length === 0

      setState(isEmpty ? "empty" : "success")
    } catch (err) {
      setErrorMessage(
        err instanceof Error ? err.message : "데이터를 불러올 수 없습니다.",
      )
      setState("error")
    }
  }, [entityId])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // ── LOADING ──
  if (state === "loading") {
    return <DashboardSkeleton />
  }

  // ── ERROR ──
  if (state === "error") {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold mb-6">대시보드</h1>
        <Card className="bg-card rounded-xl p-8 shadow flex flex-col items-center justify-center text-center gap-4">
          <AlertCircle className="h-12 w-12 text-[hsl(var(--loss))]" />
          <p className="text-lg font-medium">데이터를 불러올 수 없습니다.</p>
          <p className="text-sm text-muted-foreground">{errorMessage}</p>
          <Button onClick={fetchData} variant="secondary" className="gap-2">
            <RefreshCw className="h-4 w-4" />
            다시 시도
          </Button>
        </Card>
      </div>
    )
  }

  // ── EMPTY ──
  if (state === "empty") {
    return (
      <div className="p-6 space-y-6">
        <h1 className="text-2xl font-bold">대시보드</h1>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <KPICard label="총잔고" value={formatKRW(0)} />
          <KPICard label="이번달 수입" value={formatKRW(0)} />
          <KPICard label="이번달 지출" value={formatKRW(0)} />
          <KPICard label="현금 런웨이" value="N/A" />
        </div>

        <Card className="bg-card rounded-xl p-12 shadow flex flex-col items-center justify-center text-center gap-4">
          <Upload className="h-12 w-12 text-muted-foreground" />
          <p className="text-lg font-medium">첫 거래 데이터를 업로드해보세요</p>
          <p className="text-sm text-muted-foreground">
            Excel 파일을 업로드하면 대시보드가 자동으로 업데이트됩니다.
          </p>
          <Button asChild className="bg-[hsl(var(--accent))] text-accent-foreground hover:bg-[hsl(var(--accent))]/90 gap-2">
            <Link href="/upload">
              <Upload className="h-4 w-4" />
              Excel 업로드
            </Link>
          </Button>
        </Card>
      </div>
    )
  }

  // ── SUCCESS (& PARTIAL) ──
  const kpi = data!.kpi
  const cashFlow = data!.cash_flow
  const transactions = data!.recent_transactions.slice(0, 10)
  const counts = data!.counts

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">대시보드</h1>

      {/* KPI Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          label="총잔고"
          value={formatKRW(kpi.total_balance)}
        />
        <KPICard
          label="이번달 수입"
          value={formatKRW(kpi.monthly_income)}
          trend={kpi.income_change_pct}
        />
        <KPICard
          label="이번달 지출"
          value={formatKRW(kpi.monthly_expense)}
          trend={kpi.expense_change_pct}
          invertColor
        />
        <KPICard
          label="현금 런웨이"
          value={kpi.runway_months != null ? `${kpi.runway_months}개월` : "N/A"}
        />
      </div>

      {/* Bento Grid: Chart (2col) + Recent (1col) + Quick Actions (1col) */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Cash Flow Chart */}
        <Card className="bg-card rounded-xl p-6 shadow col-span-1 lg:col-span-2">
          <CardHeader className="p-0 pb-4">
            <CardTitle className="text-base">현금흐름</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="h-[300px]">
              <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <BarChart
                  data={cashFlow}
                  margin={{ top: 5, right: 5, left: 5, bottom: 5 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="#334155"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="month"
                    tick={{ fill: "hsl(220, 9%, 46%)", fontSize: 12 }}
                    axisLine={{ stroke: "#334155" }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: "hsl(220, 9%, 46%)", fontSize: 12 }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(v) => `${(v / 10000).toFixed(0)}만`}
                  />
                  <RechartsTooltip content={<ChartTooltipContent />} />
                  <Legend
                    wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                  />
                  <Bar
                    dataKey="income"
                    name="수입"
                    fill="#22C55E"
                    radius={[4, 4, 0, 0]}
                    animationDuration={300}
                    animationEasing="ease-out"
                  />
                  <Bar
                    dataKey="expense"
                    name="지출"
                    fill="#EF4444"
                    radius={[4, 4, 0, 0]}
                    animationDuration={300}
                    animationEasing="ease-out"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="flex justify-end mt-2">
              <Link
                href="/cashflow"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1 py-2 min-h-[44px]"
              >
                상세 보기
                <ChevronRight className="h-3 w-3" />
              </Link>
            </div>
          </CardContent>
        </Card>

        {/* Recent Transactions */}
        <Card className="bg-card rounded-xl p-6 shadow">
          <CardHeader className="p-0 pb-4">
            <CardTitle className="text-base">최근 거래</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="space-y-3">
              {transactions.map((tx) => (
                <div
                  key={tx.id}
                  className="flex items-start justify-between border-b border-border pb-2 last:border-0 last:pb-0"
                >
                  <div className="min-w-0 flex-1 mr-3">
                    <p className="text-sm font-medium truncate">
                      {tx.description || "\u2014"}
                    </p>
                    <p className="text-xs text-muted-foreground">{tx.date}</p>
                  </div>
                  <div className="text-right shrink-0">
                    <p
                      className={`text-sm font-mono font-semibold tabular-nums ${
                        tx.type === "in"
                          ? "text-[hsl(var(--profit))]"
                          : "text-[hsl(var(--loss))]"
                      }`}
                    >
                      {tx.type === "in" ? "+" : "-"}
                      {formatKRW(tx.amount)}
                    </p>
                    <div className="flex gap-1 justify-end mt-1">
                      {tx.is_confirmed ? (
                        <Badge variant="default" className="text-[10px] px-1 py-0">
                          확정
                        </Badge>
                      ) : (
                        <Badge variant="secondary" className="text-[10px] px-1 py-0">
                          미확정
                        </Badge>
                      )}
                      {tx.mapping_confidence != null && tx.mapping_confidence > 0 && (
                        <Badge variant="outline" className="text-[10px] px-1 py-0">
                          AI {(tx.mapping_confidence * 100).toFixed(0)}%
                        </Badge>
                      )}
                    </div>
                  </div>
                </div>
              ))}

              {transactions.length === 0 && (
                <p className="text-sm text-muted-foreground text-center py-4">
                  거래 내역이 없습니다.
                </p>
              )}
            </div>
            <div className="flex justify-end mt-3">
              <Link
                href={`/transactions?entity=${entityId}`}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1 py-2 min-h-[44px]"
              >
                전체 보기
                <ChevronRight className="h-3 w-3" />
              </Link>
            </div>
          </CardContent>
        </Card>

        {/* Quick Actions */}
        <Card className="bg-card rounded-xl p-6 shadow">
          <CardHeader className="p-0 pb-4">
            <CardTitle className="text-base">빠른 실행</CardTitle>
          </CardHeader>
          <CardContent className="p-0 space-y-3">
            <Button
              asChild
              variant="secondary"
              className={`w-full justify-start gap-3 h-auto py-3 ${
                counts.unconfirmed > 0
                  ? "border border-[hsl(var(--warning))] text-[hsl(var(--warning))]"
                  : ""
              }`}
            >
              <Link href={`/transactions?entity=${entityId}&is_confirmed=false`}>
                <AlertCircle className="h-4 w-4 shrink-0" />
                <span className="text-left">
                  미확정 거래 {counts.unconfirmed}건 확인
                </span>
              </Link>
            </Button>

            <Button
              asChild
              variant="secondary"
              className="w-full justify-start gap-3 h-auto py-3"
            >
              <Link href="/upload">
                <Upload className="h-4 w-4 shrink-0" />
                <span>Excel 업로드</span>
              </Link>
            </Button>

            <Button
              asChild
              variant="secondary"
              className="w-full justify-start gap-3 h-auto py-3"
            >
              <Link href={`/cashflow?entity=${entityId}`}>
                <TrendingUp className="h-4 w-4 shrink-0" />
                <span>현금흐름 상세</span>
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

// ── Page Export ─────────────────────────────────────────

export default function Page() {
  return (
    <div>
      <Suspense fallback={<div className="flex gap-1 border-b border-border">{Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-10 w-32 animate-pulse rounded-t bg-muted" />)}</div>}>
        <EntityTabs />
      </Suspense>
      <Suspense fallback={<DashboardSkeleton />}>
        <DashboardContent />
      </Suspense>
    </div>
  )
}
