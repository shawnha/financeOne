"use client"

import { Suspense } from "react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { CashflowAnalysisTab } from "./cashflow-analysis-tab"
import { ArrowLeftRight } from "lucide-react"

export default function IntercompanyPage() {
  return (
    <Suspense fallback={<div className="p-6 text-muted-foreground">로딩 중...</div>}>
      <div className="p-6 space-y-6">
        <div>
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <ArrowLeftRight className="h-5 w-5 text-[hsl(var(--accent))]" />
            법인간 거래
          </h1>
          <p className="text-xs text-muted-foreground mt-1">
            그룹사 간 자금흐름 분석 + 거래 매칭. 차입/대여 시점 효과 추적.
          </p>
        </div>

        <Tabs defaultValue="cashflow" className="w-full">
          <TabsList>
            <TabsTrigger value="cashflow">자금흐름 분석</TabsTrigger>
            <TabsTrigger value="matching" disabled>
              거래 매칭 (예정)
            </TabsTrigger>
          </TabsList>
          <TabsContent value="cashflow" className="mt-4">
            <CashflowAnalysisTab />
          </TabsContent>
        </Tabs>
      </div>
    </Suspense>
  )
}
