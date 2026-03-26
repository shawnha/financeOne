"use client"

import { Suspense } from "react"
import { EntityTabs } from "@/components/entity-tabs"
import { Skeleton } from "@/components/ui/skeleton"
import { CashflowTabs } from "./cashflow-tabs"

function CashFlowSkeleton() {
  return (
    <div className="p-6 space-y-6">
      {/* Tab bar skeleton */}
      <div className="flex gap-4 border-b border-border pb-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-8 w-28 rounded-md" />
        ))}
      </div>
      {/* KPI skeleton */}
      <div className="grid grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
      {/* Chart skeleton */}
      <Skeleton className="h-[300px] w-full rounded-xl" />
      {/* Table skeleton */}
      <Skeleton className="h-[200px] w-full rounded-xl" />
    </div>
  )
}

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
        <CashflowTabs />
      </Suspense>
    </div>
  )
}
