"use client"

import { Suspense } from "react"
import { EntityTabs } from "@/components/entity-tabs"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { DollarSign } from "lucide-react"

export default function ExchangeRatesPage() {
  return (
    <div className="space-y-6">
      <Suspense fallback={<Skeleton className="h-10 w-full border-b" />}>
        <EntityTabs />
      </Suspense>

      <div className="flex items-center gap-2">
        <DollarSign className="h-6 w-6 text-muted-foreground" />
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          환율 관리
        </h1>
      </div>

      <Card>
        <CardContent className="flex flex-col items-center justify-center py-16 text-muted-foreground">
          <DollarSign className="mb-3 h-10 w-10 opacity-40" />
          <p className="text-sm">환율 데이터가 없습니다.</p>
          <p className="mt-1 text-xs">Phase 2에서 구현됩니다.</p>
        </CardContent>
      </Card>
    </div>
  )
}
