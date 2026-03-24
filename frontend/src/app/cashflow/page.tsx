"use client"

import { useEffect, useState, useCallback, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { EntityTabs } from "@/components/entity-tabs"
import { fetchAPI } from "@/lib/api"
import { formatKRW, abbreviateAmount, formatByEntity } from "@/lib/format"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
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
} from "recharts"
import { AlertCircle, RefreshCw, Upload } from "lucide-react"
import Link from "next/link"

// ── Types ──────────────────────────────────────────────

interface CashFlowMonth {
  month: string
  opening_balance: number
  income: number
  expense: number
  net: number
  closing_balance: number
}

interface CashFlowData {
  months: CashFlowMonth[]
}

type LoadState = "loading" | "empty" | "error" | "success" | "partial"
type PeriodOption = 6 | 12 | 24

const PERIOD_OPTIONS: { value: PeriodOption; label: string }[] = [
  { value: 6, label: "6개월" },
  { value: 12, label: "12개월" },
  { value: 24, label: "24개월" },
]

// ChartTooltipContent moved inside CashFlowContent for entityId closure

// ── Skeletons ──────────────────────────────────────────

function CashFlowSkeleton() {
  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <Skeleton className="h-8 w-48" />
        <div className="flex gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-16 rounded-md" />
          ))}
        </div>
      </div>
      <Skeleton className="h-[400px] w-full rounded-xl" />
      <Skeleton className="h-[300px] w-full rounded-xl" />
    </div>
  )
}

// ── Cashflow Content ───────────────────────────────────

function CashFlowContent() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity")

  // Tooltip inside component for entityId closure
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

  const [data, setData] = useState<CashFlowData | null>(null)
  const [state, setState] = useState<LoadState>("loading")
  const [errorMessage, setErrorMessage] = useState("")
  const [months, setMonths] = useState<PeriodOption>(12)

  const fetchData = useCallback(async () => {
    if (!entityId) return
    setState("loading")
    setErrorMessage("")

    try {
      const result = await fetchAPI<CashFlowData>(
        `/dashboard/cashflow?entity_id=${entityId}&months=${months}`,
        { cache: "no-store" },
      )
      setData(result)
      setState(result.months.length === 0 ? "empty" : "success")
    } catch (err) {
      setErrorMessage(
        err instanceof Error ? err.message : "데이터를 불러올 수 없습니다.",
      )
      setState("error")
    }
  }, [entityId, months])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // ── Period Selector (always rendered) ──
  const periodSelector = (
    <div className="flex gap-2">
      {PERIOD_OPTIONS.map((opt) => (
        <Button
          key={opt.value}
          variant={months === opt.value ? "default" : "secondary"}
          size="sm"
          onClick={() => setMonths(opt.value)}
          className={
            months === opt.value
              ? "bg-[hsl(var(--accent))] text-accent-foreground hover:bg-[hsl(var(--accent))]/90"
              : ""
          }
        >
          {opt.label}
        </Button>
      ))}
    </div>
  )

  // ── LOADING ──
  if (state === "loading") {
    return <CashFlowSkeleton />
  }

  // ── ERROR ──
  if (state === "error") {
    return (
      <div className="p-6 space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold tracking-tight">현금흐름</h1>
          {periodSelector}
        </div>
        <Card className="p-8 flex flex-col items-center justify-center text-center gap-4">
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
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold tracking-tight">현금흐름</h1>
          {periodSelector}
        </div>
        <Card className="p-12 flex flex-col items-center justify-center text-center gap-4">
          <Upload className="h-12 w-12 text-muted-foreground" />
          <p className="text-lg font-medium">현금흐름 데이터가 없습니다</p>
          <p className="text-sm text-muted-foreground">
            거래 데이터를 업로드하면 현금흐름이 자동으로 계산됩니다.
          </p>
          <Button
            asChild
            className="bg-[hsl(var(--accent))] text-accent-foreground hover:bg-[hsl(var(--accent))]/90 gap-2"
          >
            <Link href="/upload">
              <Upload className="h-4 w-4" />
              Excel 업로드
            </Link>
          </Button>
        </Card>
      </div>
    )
  }

  // ── SUCCESS ──
  const monthsData = data!.months

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">현금흐름</h1>
        {periodSelector}
      </div>

      {/* Area Chart */}
      <Card className="p-6">
        <CardHeader className="p-0 pb-4">
          <CardTitle className="text-base">수입 / 지출 추이</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="h-[400px]">
            <ResponsiveContainer width="100%" height="100%" minWidth={0}>
              <ComposedChart
                data={monthsData}
                margin={{ top: 10, right: 10, left: 10, bottom: 5 }}
              >
                <defs>
                  <linearGradient id="incomeGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="hsl(var(--chart-1))" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="hsl(var(--chart-1))" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="expenseGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="hsl(var(--chart-2))" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="hsl(var(--chart-2))" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="hsl(var(--border))"
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
                  tickFormatter={(v) => abbreviateAmount(v)}
                />
                <RechartsTooltip content={<ChartTooltipContent />} />
                <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
                <Area
                  type="monotone"
                  dataKey="income"
                  name="수입"
                  stroke="hsl(var(--chart-1))"
                  fill="url(#incomeGrad)"
                  strokeWidth={2}
                  animationDuration={300}
                  animationEasing="ease-out"
                />
                <Area
                  type="monotone"
                  dataKey="expense"
                  name="지출"
                  stroke="hsl(var(--chart-2))"
                  fill="url(#expenseGrad)"
                  strokeWidth={2}
                  animationDuration={300}
                  animationEasing="ease-out"
                />
                <Line
                  type="monotone"
                  dataKey="net"
                  name="순현금흐름"
                  stroke="#3B82F6"
                  strokeWidth={2}
                  dot={false}
                  animationDuration={300}
                  animationEasing="ease-out"
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Monthly Breakdown Table */}
      <Card className="overflow-hidden">
        <CardHeader className="p-6 pb-0">
          <CardTitle className="text-base">월별 상세</CardTitle>
        </CardHeader>
        <CardContent className="p-0 mt-4">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/30 sticky top-0">
                  <TableHead className="font-medium">월</TableHead>
                  <TableHead className="text-right font-medium">기초잔고</TableHead>
                  <TableHead className="text-right font-medium">수입</TableHead>
                  <TableHead className="text-right font-medium">지출</TableHead>
                  <TableHead className="text-right font-medium">순현금흐름</TableHead>
                  <TableHead className="text-right font-medium">기말잔고</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {monthsData.map((row, idx) => (
                  <TableRow
                    key={row.month}
                    className={idx % 2 === 1 ? "bg-muted/10" : ""}
                  >
                    <TableCell className="font-medium">{row.month}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {formatByEntity(row.opening_balance, entityId)}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums text-[hsl(var(--profit))]">
                      {formatByEntity(row.income, entityId)}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums text-[hsl(var(--loss))]">
                      {formatByEntity(row.expense, entityId)}
                    </TableCell>
                    <TableCell
                      className={`text-right font-mono tabular-nums ${
                        row.net >= 0
                          ? "text-[hsl(var(--profit))]"
                          : "text-[hsl(var(--loss))]"
                      }`}
                    >
                      {formatByEntity(row.net, entityId)}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {formatByEntity(row.closing_balance, entityId)}
                    </TableCell>
                  </TableRow>
                ))}

                {monthsData.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={6}
                      className="text-center text-muted-foreground py-8"
                    >
                      데이터가 없습니다.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ── Page Export ─────────────────────────────────────────

export default function CashFlowPage() {
  return (
    <div>
      <Suspense
        fallback={
          <div className="flex gap-1 border-b border-border">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-10 w-32 animate-pulse rounded-t bg-muted"
              />
            ))}
          </div>
        }
      >
        <EntityTabs />
      </Suspense>
      <Suspense fallback={<CashFlowSkeleton />}>
        <CashFlowContent />
      </Suspense>
    </div>
  )
}
