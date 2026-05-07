"use client"

import { Suspense } from "react"
import { EntityTabs } from "@/components/entity-tabs"
import { Skeleton } from "@/components/ui/skeleton"
import { OpexContent } from "./opex-content"

function OpexSkeleton() {
  return (
    <div className="p-6 space-y-6">
      <div className="grid grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-[260px] w-full rounded-xl" />
      <Skeleton className="h-[200px] w-full rounded-xl" />
    </div>
  )
}

export default function OpexPage() {
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
      <Suspense fallback={<OpexSkeleton />}>
        <OpexContent />
      </Suspense>
    </div>
  )
}
