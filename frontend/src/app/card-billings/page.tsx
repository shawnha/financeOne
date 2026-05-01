"use client"

import { Suspense, useCallback, useEffect, useState } from "react"
import { useSearchParams } from "next/navigation"
import { fetchAPI } from "@/lib/api"
import { EntityTabs } from "@/components/entity-tabs"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { CreditCard, RefreshCw } from "lucide-react"
import { toast } from "sonner"

interface CardBilling {
  id: number
  entity_id: number
  card_org: string
  card_no_masked: string | null
  billing_month: string         // YYYYMM
  billing_date: string | null
  settlement_date: string | null
  total_amount: number
  principal_amount: number | null
  installment_amount: number | null
  interest_amount: number | null
  status: string
  paid_amount: number
  transaction_id: number | null
  updated_at: string
}

const CARD_LABELS: Record<string, string> = {
  kb_card: "KB국민",
  hyundai_card: "현대",
  samsung_card: "삼성",
  nh_card: "NH농협",
  bc_card: "BC",
  shinhan_card: "신한",
  citi_card: "씨티",
  woori_card: "우리",
  lotte_card: "롯데",
  hana_card: "하나",
}

function formatKRW(n: number | null | undefined): string {
  if (n === null || n === undefined) return "-"
  return n.toLocaleString("ko-KR")
}

function formatBillingMonth(ym: string): string {
  if (!ym || ym.length !== 6) return ym
  return `${ym.slice(0, 4)}.${ym.slice(4, 6)}`
}

function CardBillingsContent() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity")
  const [items, setItems] = useState<CardBilling[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    if (!entityId) return
    setLoading(true)
    try {
      const res = await fetchAPI<{ items: CardBilling[]; count: number }>(
        `/integrations/card-billings?entity_id=${entityId}&months=12`,
      )
      setItems(res.items)
    } catch (e) {
      toast.error(`불러오기 실패: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }, [entityId])

  useEffect(() => { load() }, [load])

  // 청구월별 그룹화
  const byMonth = items.reduce((acc, b) => {
    if (!acc[b.billing_month]) acc[b.billing_month] = []
    acc[b.billing_month].push(b)
    return acc
  }, {} as Record<string, CardBilling[]>)
  const months = Object.keys(byMonth).sort((a, b) => b.localeCompare(a))

  if (!entityId) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-muted-foreground">
          법인을 선택해주세요.
        </CardContent>
      </Card>
    )
  }

  return (
    <>
      <EntityTabs />
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CreditCard className="h-5 w-5 text-blue-400" />
            <h1 className="text-xl font-medium">카드 청구서</h1>
            <span className="text-xs text-muted-foreground">최근 12개월</span>
          </div>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={`h-3 w-3 mr-1 ${loading ? "animate-spin" : ""}`} />
            새로고침
          </Button>
        </div>

        {loading && items.length === 0 ? (
          <div className="space-y-2">
            {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-24 w-full" />)}
          </div>
        ) : months.length === 0 ? (
          <Card>
            <CardContent className="py-16 text-center text-muted-foreground space-y-2">
              <CreditCard className="h-8 w-8 mx-auto opacity-40" />
              <p className="text-sm">카드 청구서가 없습니다.</p>
              <p className="text-xs text-muted-foreground/70">
                설정 → Codef → 카드 → 청구서 동기화 후 표시됩니다.
              </p>
            </CardContent>
          </Card>
        ) : (
          months.map((m) => {
            const list = byMonth[m]
            const total = list.reduce((s, b) => s + (b.total_amount || 0), 0)
            return (
              <Card key={m}>
                <CardHeader className="flex flex-row items-center justify-between border-b border-white/[0.05] py-3">
                  <CardTitle className="text-base font-medium">
                    {formatBillingMonth(m)} 청구
                    <span className="ml-2 text-xs text-muted-foreground font-normal">
                      {list.length}건
                    </span>
                  </CardTitle>
                  <div className="text-sm font-mono">
                    합계 <span className="text-foreground">{formatKRW(total)}</span>
                  </div>
                </CardHeader>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead className="text-xs text-muted-foreground border-b border-white/[0.05]">
                      <tr>
                        <th className="text-left px-4 py-2">카드사</th>
                        <th className="text-left px-4 py-2">카드번호</th>
                        <th className="text-left px-4 py-2">결제예정일</th>
                        <th className="text-right px-4 py-2">청구액</th>
                        <th className="text-right px-4 py-2">원금</th>
                        <th className="text-right px-4 py-2">할부잔액</th>
                        <th className="text-right px-4 py-2">이자</th>
                        <th className="text-left px-4 py-2">상태</th>
                      </tr>
                    </thead>
                    <tbody>
                      {list.map((b) => (
                        <tr key={b.id} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                          <td className="px-4 py-2">
                            <Badge variant="outline" className="text-[10px]">
                              {CARD_LABELS[b.card_org] ?? b.card_org}
                            </Badge>
                          </td>
                          <td className="px-4 py-2 font-mono text-muted-foreground">{b.card_no_masked || "-"}</td>
                          <td className="px-4 py-2 text-muted-foreground">{b.settlement_date || "-"}</td>
                          <td className="px-4 py-2 text-right font-mono">{formatKRW(b.total_amount)}</td>
                          <td className="px-4 py-2 text-right font-mono text-muted-foreground">{formatKRW(b.principal_amount)}</td>
                          <td className="px-4 py-2 text-right font-mono text-muted-foreground">{formatKRW(b.installment_amount)}</td>
                          <td className="px-4 py-2 text-right font-mono text-amber-300/80">{formatKRW(b.interest_amount)}</td>
                          <td className="px-4 py-2">
                            {b.status === "paid" ? (
                              <Badge variant="outline" className="text-[10px] border-emerald-500/40 text-emerald-300">완납</Badge>
                            ) : b.status === "overdue" ? (
                              <Badge variant="outline" className="text-[10px] border-red-500/40 text-red-300">연체</Badge>
                            ) : (
                              <Badge variant="outline" className="text-[10px] border-amber-500/40 text-amber-300">청구</Badge>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            )
          })
        )}
      </div>
    </>
  )
}

export default function CardBillingsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-screen w-full" />}>
      <CardBillingsContent />
    </Suspense>
  )
}
