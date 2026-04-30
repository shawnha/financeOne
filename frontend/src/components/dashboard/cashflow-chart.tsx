"use client"

import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useDashboard } from "@/contexts/dashboard-context"
import { formatCurrency } from "@/lib/format"
import type { ChartData, ChartMonthPoint } from "@/lib/dashboard-types"

interface CashflowChartProps {
  data: ChartData | null
  loading?: boolean
}

export function CashflowChart({ data, loading = false }: CashflowChartProps) {
  const { currency } = useDashboard()

  return (
    <Card className="p-4" aria-labelledby="cashflow-chart-title">
      <CardHeader className="p-0 pb-3 flex flex-row items-center justify-between">
        <CardTitle
          id="cashflow-chart-title"
          className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground"
        >
          📈 현금 흐름 + 매출 추이 (최근 6개월)
        </CardTitle>
        <span className="text-[10px] text-muted-foreground">
          {currency} 기준
        </span>
      </CardHeader>
      <CardContent className="p-0">
        {loading || !data ? (
          <Skeleton className="h-[260px] w-full rounded-md" />
        ) : data.months.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-12">
            6개월 데이터가 없습니다.
          </p>
        ) : (
          <ChartBody months={data.months} currency={currency} />
        )}
      </CardContent>
    </Card>
  )
}

function ChartBody({
  months,
  currency,
}: {
  months: ChartMonthPoint[]
  currency: string
}) {
  // Decimal-as-string → number. cash_out 양수로 그려 별도 stack 으로 표시 (시각 단순)
  const rows = months.map((m) => ({
    month: m.month.slice(5), // "2026-04" → "04"
    cash_in: Number(m.cash_in),
    cash_out: Number(m.cash_out),
    revenue_acc: m.accrual_revenue ? Number(m.accrual_revenue) : 0,
  }))

  const profit = "hsl(var(--profit))"
  const loss = "hsl(var(--loss))"
  const accent = "hsl(var(--ai-accent))"

  return (
    <div style={{ height: 260, width: "100%" }}>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart
          data={rows}
          margin={{ top: 8, right: 16, left: 8, bottom: 8 }}
          barCategoryGap="20%"
          barGap={2}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="hsl(var(--border))"
            vertical={false}
          />
          <XAxis
            dataKey="month"
            tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
            axisLine={{ stroke: "hsl(var(--border))" }}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => abbreviate(v, currency)}
            width={70}
            domain={[0, (dataMax: number) => Math.ceil(dataMax * 1.05)]}
            allowDataOverflow={false}
          />
          <RechartsTooltip
            contentStyle={{
              background: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 6,
              fontSize: 12,
            }}
            formatter={(value: number, name: string) => [
              formatCurrency(value, currency),
              name,
            ]}
          />
          <Legend
            wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
            iconType="circle"
          />
          <Bar
            dataKey="cash_in"
            name="현금 in"
            fill={profit}
            radius={[3, 3, 0, 0]}
            maxBarSize={40}
          />
          <Bar
            dataKey="cash_out"
            name="현금 out"
            fill={loss}
            radius={[3, 3, 0, 0]}
            maxBarSize={40}
          />
          <Line
            type="monotone"
            dataKey="revenue_acc"
            name="매출 (acc)"
            stroke={accent}
            strokeWidth={2}
            dot={{ r: 3, fill: accent }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

function abbreviate(v: number, currency: string): string {
  const abs = Math.abs(v)
  const sign = v < 0 ? "-" : ""
  if (currency === "KRW") {
    if (abs >= 1_0000_0000) return `${sign}${(abs / 1_0000_0000).toFixed(1)}억`
    if (abs >= 10000) return `${sign}${(abs / 10000).toFixed(0)}만`
    return `${sign}${abs.toLocaleString("ko-KR")}`
  }
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(0)}K`
  return `${sign}$${abs.toFixed(0)}`
}
