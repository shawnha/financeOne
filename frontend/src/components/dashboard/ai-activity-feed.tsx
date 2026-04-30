"use client"

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import type { AiActivity, CascadeStep } from "@/lib/dashboard-types"

const CASCADE_LABEL: Record<CascadeStep, string> = {
  exact: "정확",
  similar_trgm: "유사",
  entity_keyword: "법인키워드",
  global_keyword: "글로벌",
  ai: "AI",
}

interface AiActivityFeedProps {
  data: AiActivity | null
  loading?: boolean
}

export function AiActivityFeed({ data, loading = false }: AiActivityFeedProps) {
  return (
    <Card
      className="p-4"
      aria-labelledby="ai-feed-title"
      role="region"
    >
      <CardHeader className="p-0 pb-3">
        <CardTitle
          id="ai-feed-title"
          className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground flex items-center gap-2"
        >
          <span aria-hidden>🤖</span>
          <span>AI Activity (Today)</span>
        </CardTitle>
      </CardHeader>

      <CardContent
        className="p-0 space-y-1.5"
        aria-live="polite"
      >
        {loading || !data ? (
          <>
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
          </>
        ) : (
          <>
            <FeedRow
              icon="✓"
              colorClass="text-[hsl(var(--profit))]"
              label="자동 매핑"
              value={`${data.auto_mapped_today}건 (98%+)`}
            />
            <FeedRow
              icon="🟡"
              colorClass="text-[hsl(var(--warning))]"
              label="검토 필요"
              value={`${data.review_needed}건 (70-95%)`}
            />
            <FeedRow
              icon="🔴"
              colorClass="text-[hsl(var(--loss))]"
              label="이상치"
              value={`${data.unusual}건`}
            />

            <div className="pt-2 mt-2 border-t border-dashed border-border space-y-1">
              {data.keyword_added_this_week > 0 && (
                <p className="text-[10.5px] text-muted-foreground">
                  📊 학습: 이번주 keyword {data.keyword_added_this_week}개 →
                  {" "}향후 {data.learning_impact}건 자동화 예상
                </p>
              )}
              {data.cascade.length > 0 && (
                <p className="text-[10.5px] text-muted-foreground">
                  ℹ️ cascade:{" "}
                  {data.cascade
                    .map(
                      (c) =>
                        `${CASCADE_LABEL[c.step]} ${c.pct.toFixed(0)}%`,
                    )
                    .join(" / ")}
                </p>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function FeedRow({
  icon,
  colorClass,
  label,
  value,
}: {
  icon: string
  colorClass: string
  label: string
  value: string
}) {
  return (
    <p className={`text-xs flex items-baseline gap-2 ${colorClass}`}>
      <span aria-hidden className="w-3.5 text-center">
        {icon}
      </span>
      <span>{label}</span>
      <span className="ml-auto font-semibold tabular-nums">{value}</span>
    </p>
  )
}
