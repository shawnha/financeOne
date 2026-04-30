"use client"

import { Info } from "lucide-react"
import { Card } from "@/components/ui/card"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { Skeleton } from "@/components/ui/skeleton"
import { useDashboard } from "@/contexts/dashboard-context"
import { formatCurrency } from "@/lib/format"
import type { AccrualDiffBreakdown, AccrualStatus } from "@/lib/dashboard-types"

interface DualIndicatorCardProps {
  label: string
  accValue: string | null | undefined         // Decimal as string from API
  cashValue: string                            // always available
  accuracyStatus: AccrualStatus
  diffBreakdown?: AccrualDiffBreakdown | null
  diffKind: "revenue" | "expense"              // 어느 reconciliation formula 적용
  loading?: boolean
}

function num(v: string | null | undefined): number {
  if (v == null) return 0
  return Number(v)
}

function fmtDelta(amount: number, currency: string): string {
  const sign = amount >= 0 ? "+" : ""
  return `${sign}${formatCurrency(Math.abs(amount), currency)}`
}

export function DualIndicatorCard({
  label,
  accValue,
  cashValue,
  accuracyStatus,
  diffBreakdown,
  diffKind,
  loading = false,
}: DualIndicatorCardProps) {
  const { currency } = useDashboard()

  if (loading) {
    return (
      <Card className="p-4 space-y-2">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-5 w-28" />
        <Skeleton className="h-3 w-24 mt-2" />
      </Card>
    )
  }

  const inProgress = accuracyStatus === "in_progress"
  const showAcc = !inProgress && accValue != null
  const accNum = num(accValue)
  const cashNum = num(cashValue)
  const diff = accNum - cashNum

  // Reconciliation: build human-readable breakdown text
  let diffText = ""
  let tooltipBody = ""
  if (showAcc && diffBreakdown) {
    if (diffKind === "revenue") {
      const ar = num(diffBreakdown.ar_delta)
      const def = num(diffBreakdown.deferred_revenue_delta)
      diffText = `${fmtDelta(diff, currency)} 외상매출/선수금 차이`
      tooltipBody = [
        `매출 (Acc) = invoice 발행 시점`,
        `매출 (Cash) = 통장 입금 시점`,
        `차이 = 외상매출금 ${fmtDelta(ar, currency)}` +
          (def !== 0 ? ` + 선수금 ${fmtDelta(def, currency)}` : ""),
      ].join("\n")
    } else {
      const ap = num(diffBreakdown.ap_delta)
      const acc = num(diffBreakdown.accrued_expense_delta)
      diffText = `${fmtDelta(diff, currency)} 외상매입/카드 미결제`
      tooltipBody = [
        `비용 (Acc) = 카드 사용 + invoice 인식 시점`,
        `비용 (Cash) = 통장 출금 시점`,
        `차이 = 외상매입금 ${fmtDelta(ap, currency)}` +
          (acc !== 0 ? ` + 미지급비용 ${fmtDelta(acc, currency)}` : ""),
      ].join("\n")
    }
  }

  // ARIA label: screen reader 친화 풀 문장
  const srLabel = showAcc
    ? `${label} 발생주의 ${formatCurrency(accNum, currency)} 현금주의 ${formatCurrency(cashNum, currency)} ${diffText}`
    : `${label} 현금주의 ${formatCurrency(cashNum, currency)} 발생주의 정확도 진행 중`

  return (
    <Card className="p-4" data-testid="dual-indicator-card" aria-label={srLabel}>
      <p
        className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mb-2"
      >
        {label}
      </p>

      {showAcc && (
        <div className="flex items-baseline gap-2 mb-1">
          <span
            className="text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded bg-[hsl(var(--ai-accent))]/15 text-[hsl(var(--ai-accent))] min-w-[38px] text-center"
            aria-hidden
          >
            ACC
          </span>
          <span className="font-mono font-semibold tabular-nums text-base text-foreground">
            {formatCurrency(accNum, currency)}
          </span>
        </div>
      )}

      <div className="flex items-baseline gap-2 mb-1">
        <span
          className="text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded bg-[hsl(var(--warning))]/15 text-[hsl(var(--warning))] min-w-[38px] text-center"
          aria-hidden
        >
          CASH
        </span>
        <span className="font-mono font-semibold tabular-nums text-base text-foreground">
          {formatCurrency(cashNum, currency)}
        </span>
      </div>

      {inProgress && (
        <p
          className="text-[10.5px] text-[hsl(var(--warning))] mt-2 pt-2 border-t border-dashed border-border"
          role="status"
        >
          ⚠️ 발생주의 정확도 진행 중 (P3-9)
        </p>
      )}

      {showAcc && diffText && (
        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="flex items-center gap-1 text-[10.5px] text-muted-foreground mt-2 pt-2 border-t border-dashed border-border w-full text-left hover:text-[hsl(var(--ai-accent))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--color-cta))] rounded"
                aria-label={`${diffText} 자세히 보기`}
              >
                <span className="flex-1 truncate">{diffText}</span>
                <Info className="h-3 w-3 shrink-0" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs whitespace-pre-line">
              {tooltipBody}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      )}
    </Card>
  )
}
