"use client"

import { useState } from "react"
import { useSearchParams } from "next/navigation"
import { cn } from "@/lib/utils"
import { Skeleton } from "@/components/ui/skeleton"
import { ActualTab } from "./actual-tab"
import { ForecastTab } from "./forecast-tab"
import { ExpenseTab } from "./expense-tab"

type TabKey = "actual" | "forecast" | "expense"

const TABS: { key: TabKey; label: string; color: string; activeClass: string }[] = [
  {
    key: "actual",
    label: "실제 현금흐름",
    color: "hsl(var(--profit))",
    activeClass: "border-[hsl(var(--profit))] text-[hsl(var(--profit))]",
  },
  {
    key: "forecast",
    label: "예상 현금흐름",
    color: "hsl(var(--warning))",
    activeClass: "border-[hsl(var(--warning))] text-[hsl(var(--warning))]",
  },
  {
    key: "expense",
    label: "비용 (카드 사용)",
    color: "#8B5CF6",
    activeClass: "border-[#8B5CF6] text-[#8B5CF6]",
  },
]

export function CashflowTabs() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity")
  const [activeTab, setActiveTab] = useState<TabKey>("actual")

  // EntityTabs가 entity param을 세팅할 때까지 대기
  if (!entityId) {
    return (
      <div className="p-6 space-y-6">
        <div className="flex gap-6 border-b border-border pb-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-28 rounded-md" />
          ))}
        </div>
        <div className="grid grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-[300px] w-full rounded-xl" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      {/* Tab bar */}
      <div
        className="flex items-center gap-6 border-b border-border"
        role="tablist"
        aria-label="현금흐름 탭"
      >
        {TABS.map((tab) => (
          <button
            key={tab.key}
            role="tab"
            aria-selected={activeTab === tab.key}
            tabIndex={activeTab === tab.key ? 0 : -1}
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              "pb-2 text-sm font-medium transition-colors min-h-[44px]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              activeTab === tab.key
                ? `border-b-2 ${tab.activeClass}`
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "actual" && <ActualTab entityId={entityId} />}
      {activeTab === "forecast" && <ForecastTab entityId={entityId} />}
      {activeTab === "expense" && <ExpenseTab entityId={entityId} />}
    </div>
  )
}
