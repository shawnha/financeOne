"use client"

import { AlertTriangle } from "lucide-react"
import { Card } from "@/components/ui/card"
import type { AccrualKPI } from "@/lib/dashboard-types"

interface AccrualGatingNoticeProps {
  accrualKpi: AccrualKPI | null
}

/**
 * P3-9 진행도 표시 — accrual KPI 가 in_progress 일 때만 dashboard 상단 배너로 노출.
 * 사용자에게 "왜 발생주의 숫자가 안 보이는지" 명확히 설명.
 */
export function AccrualGatingNotice({ accrualKpi }: AccrualGatingNoticeProps) {
  if (!accrualKpi || accrualKpi.accuracy_status !== "in_progress") {
    return null
  }

  const { accuracy_pass_count, accuracy_total_count, accuracy_threshold } =
    accrualKpi

  return (
    <Card
      className="p-3 mb-3 border-[hsl(var(--warning))]/40 bg-[hsl(var(--warning))]/10"
      role="status"
      aria-live="polite"
      aria-labelledby="gating-title"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle
          className="h-4 w-4 mt-0.5 text-[hsl(var(--warning))] shrink-0"
          aria-hidden
        />
        <div className="flex-1 text-[12px] text-foreground">
          <p id="gating-title" className="font-semibold mb-0.5">
            발생주의 데이터 정확도 진행 중
          </p>
          <p className="text-muted-foreground">
            BS 검증 {accuracy_pass_count}/{accuracy_total_count} PASS (목표:{" "}
            {accuracy_threshold}/{accuracy_total_count}). 이 entity 의 매출/비용 발생주의
            숫자는 정확도 임계값 도달 후 표시됩니다. 현재는 통장 거래 (cash) 만 표시.
          </p>
        </div>
      </div>
    </Card>
  )
}
