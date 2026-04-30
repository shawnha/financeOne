"use client"

import { ArrowDownRight, ArrowUpRight } from "lucide-react"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useDashboard } from "@/contexts/dashboard-context"
import { formatCurrency } from "@/lib/format"

interface SingleIndicatorCardProps {
  label: string
  value: string                    // Decimal as string OR pre-formatted text (e.g., "14개월")
  changePct?: number | null
  invertColor?: boolean            // expense: ↑ = red
  isText?: boolean                 // value 가 이미 string ("14개월")
  loading?: boolean
  ariaLabel?: string
}

export function SingleIndicatorCard({
  label,
  value,
  changePct,
  invertColor = false,
  isText = false,
  loading = false,
  ariaLabel,
}: SingleIndicatorCardProps) {
  const { currency } = useDashboard()

  if (loading) {
    return (
      <Card className="p-4 space-y-2">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-7 w-32" />
        <Skeleton className="h-3 w-12" />
      </Card>
    )
  }

  const display = isText ? value : formatCurrency(Number(value), currency)
  const sr = ariaLabel ?? `${label} ${display}`

  return (
    <Card className="p-4" data-testid="single-indicator-card" aria-label={sr}>
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mb-2">
        {label}
      </p>
      <p className="font-mono font-semibold tabular-nums text-2xl leading-tight text-foreground">
        {display}
      </p>
      {changePct != null && (
        <div className="mt-2">
          <TrendBadge value={changePct} invertColor={invertColor} />
        </div>
      )}
    </Card>
  )
}

function TrendBadge({
  value,
  invertColor,
}: {
  value: number
  invertColor: boolean
}) {
  const isPositive = value >= 0
  const isGood = invertColor ? !isPositive : isPositive
  const colorClass = isGood
    ? "text-[hsl(var(--profit))]"
    : "text-[hsl(var(--loss))]"

  return (
    <span
      className={`inline-flex items-center gap-0.5 text-xs font-medium ${colorClass}`}
      aria-label={`${isPositive ? "증가" : "감소"} ${Math.abs(value).toFixed(1)}%`}
    >
      {isPositive ? (
        <ArrowUpRight className="h-3 w-3" aria-hidden />
      ) : (
        <ArrowDownRight className="h-3 w-3" aria-hidden />
      )}
      {Math.abs(value).toFixed(1)}%
    </span>
  )
}
