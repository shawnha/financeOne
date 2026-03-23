"use client"

import { useEffect, useState, useCallback } from "react"
import { useSearchParams, useRouter, usePathname } from "next/navigation"
import { cn } from "@/lib/utils"
import { fetchAPI } from "@/lib/api"
import { TooltipProvider } from "@/components/ui/tooltip"

interface Entity {
  id: number
  code: string
  name: string
  type: string
  currency: string
}

const ENTITY_COLORS: Record<number, string> = {
  1: "bg-blue-500",   // HOI
  2: "bg-green-500",  // HOK
  3: "bg-amber-500",  // HOR
}

function getEntityDotColor(entityId: number): string {
  return ENTITY_COLORS[entityId] || "bg-gray-500"
}

export function EntityTabs() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const [entities, setEntities] = useState<Entity[]>([])
  const [loading, setLoading] = useState(true)

  const currentEntityId = searchParams.get("entity")
    ? Number(searchParams.get("entity"))
    : null

  useEffect(() => {
    fetchAPI<Entity[]>("/entities")
      .then((data) => {
        setEntities(data)
        // Default to first entity if no entity param
        if (!searchParams.get("entity") && data.length > 0) {
          const params = new URLSearchParams(searchParams.toString())
          params.set("entity", String(data[0].id))
          router.replace(`${pathname}?${params.toString()}`)
        }
      })
      .catch(() => {
        // Fallback entities for when API is unavailable
        setEntities([
          { id: 1, code: "HOI", name: "한아원인터내셔널", type: "parent", currency: "USD" },
          { id: 2, code: "HOK", name: "한아원코리아", type: "subsidiary", currency: "KRW" },
          { id: 3, code: "HOR", name: "한아원리테일", type: "subsidiary", currency: "KRW" },
        ])
        if (!searchParams.get("entity")) {
          const params = new URLSearchParams(searchParams.toString())
          params.set("entity", "1")
          router.replace(`${pathname}?${params.toString()}`)
        }
      })
      .finally(() => setLoading(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleSelect = useCallback(
    (entityId: number) => {
      const params = new URLSearchParams(searchParams.toString())
      params.set("entity", String(entityId))
      router.push(`${pathname}?${params.toString()}`)
    },
    [searchParams, router, pathname],
  )

  const activeId = currentEntityId ?? entities[0]?.id
  const selectedEntity = searchParams.get("entity") || String(activeId)

  if (loading) {
    return (
      <div className="flex gap-1 border-b border-border" role="tablist" aria-label="Entity selector">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-10 w-32 animate-pulse rounded-t bg-muted"
          />
        ))}
      </div>
    )
  }

  return (
    <TooltipProvider delayDuration={300}>
      <div
        className="flex items-end gap-1 border-b border-border"
        role="tablist"
        aria-label="Entity selector"
        data-testid="entity-tabs"
      >
        {entities.map((entity) => (
          <button
            key={entity.id}
            role="tab"
            aria-selected={activeId === entity.id}
            tabIndex={activeId === entity.id ? 0 : -1}
            onClick={() => handleSelect(entity.id)}
            className={cn(
              "flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-colors",
              "min-h-[44px] rounded-t-md",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#22C55E]",
              activeId === entity.id
                ? "border-b-2 border-[hsl(var(--accent))] text-[hsl(var(--accent))]"
                : "text-muted-foreground hover:text-foreground hover:bg-secondary/50",
            )}
          >
            <span
              className={cn(
                "inline-block h-2 w-2 rounded-full",
                getEntityDotColor(entity.id),
              )}
              aria-hidden="true"
            />
            <span>{entity.name}</span>
            <span className="text-xs text-muted-foreground">
              ({entity.currency})
            </span>
          </button>
        ))}

        {/* Consolidated tab */}
        <button
          role="tab"
          aria-selected={selectedEntity === "consolidated"}
          onClick={() => {
            const params = new URLSearchParams(searchParams.toString())
            params.set("entity", "consolidated")
            router.push(`${pathname}?${params.toString()}`)
          }}
          className={cn(
            "flex items-center gap-2 px-4 py-2.5 text-sm font-medium",
            "min-h-[44px] rounded-t-md transition-colors cursor-pointer",
            selectedEntity === "consolidated"
              ? "text-foreground border-b-2 border-[hsl(var(--entity-consolidated))] bg-secondary/50"
              : "text-muted-foreground hover:text-foreground hover:bg-secondary/30",
          )}
        >
          <span
            className="inline-block h-2 w-2 rounded-full bg-[hsl(var(--entity-consolidated))]"
            aria-hidden="true"
          />
          <span>연결</span>
          <span className="text-xs text-muted-foreground">(USD)</span>
        </button>
      </div>
    </TooltipProvider>
  )
}
