"use client"

import Link from "next/link"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import type { DecisionQueueSection } from "@/lib/dashboard-types"

interface DecisionQueueProps {
  data: DecisionQueueSection | null
  loading?: boolean
}

const SEVERITY_COLOR = {
  danger: "text-[hsl(var(--loss))]",
  warn: "text-[hsl(var(--warning))]",
  info: "text-foreground",
} as const

export function DecisionQueue({ data, loading = false }: DecisionQueueProps) {
  return (
    <Card className="p-4" aria-labelledby="dq-title">
      <CardHeader className="p-0 pb-3">
        <CardTitle
          id="dq-title"
          className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground flex items-center gap-2"
        >
          <span aria-hidden>🔴</span>
          <span className="flex-1">Decision Queue</span>
          {!loading && data && (
            <span
              className="text-[hsl(var(--warning))] font-bold"
              aria-label={`총 ${data.total}건`}
            >
              {data.total}건
            </span>
          )}
        </CardTitle>
      </CardHeader>

      <CardContent className="p-0">
        {loading || !data ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="flex gap-2 py-1.5">
                <Skeleton className="h-4 w-4 rounded-full" />
                <Skeleton className="h-4 flex-1" />
                <Skeleton className="h-4 w-8" />
              </div>
            ))}
          </div>
        ) : data.items.length === 0 ? (
          <p
            className="text-sm text-muted-foreground py-2"
            role="status"
          >
            ✓ 오늘 검토할 항목이 없습니다.
          </p>
        ) : (
          <ul role="list" className="space-y-0">
            {data.items.map((item, i) => (
              <li key={i} className="border-b border-border last:border-0">
                <Link
                  href={item.deep_link}
                  className="flex items-center gap-3 py-2 px-1 text-sm hover:bg-muted/40 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--color-cta))]"
                  aria-label={`${item.text} ${item.count}건, 자세히 보기`}
                >
                  <span className="text-base" aria-hidden>{item.icon}</span>
                  <span className="flex-1 text-foreground">{item.text}</span>
                  <span
                    className={`font-bold tabular-nums ${SEVERITY_COLOR[item.severity]}`}
                  >
                    {item.count}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
