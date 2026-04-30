"use client"

import { Suspense, useMemo } from "react"
import Link from "next/link"
import { AlertCircle, RefreshCw, Upload } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { MonthPicker } from "@/components/month-picker"
import {
  DashboardProvider,
  useDashboard,
} from "@/contexts/dashboard-context"
import { AccrualGatingNotice } from "@/components/dashboard/accrual-gating-notice"
import { AiActivityFeed } from "@/components/dashboard/ai-activity-feed"
import { BentoEntitySelector } from "@/components/dashboard/bento-entity-selector"
import { DecisionQueue } from "@/components/dashboard/decision-queue"
import { DualIndicatorCard } from "@/components/dashboard/dual-indicator-card"
import { SingleIndicatorCard } from "@/components/dashboard/single-indicator-card"

// ── Page entrypoint ──────────────────────────────────────

export default function Page() {
  return (
    <DashboardProvider>
      <Suspense fallback={<DashboardSkeleton />}>
        <DashboardContent />
      </Suspense>
    </DashboardProvider>
  )
}

// ── Skeleton ────────────────────────────────────────────

function DashboardSkeleton() {
  return (
    <div className="p-4 lg:p-6 space-y-3">
      <Skeleton className="h-8 w-40 mb-2" />
      <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-3">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-32" />
        ))}
      </div>
    </div>
  )
}

// ── Content ─────────────────────────────────────────────

function DashboardContent() {
  const { data, state, errorMessage, refresh } = useDashboard()

  if (state === "error") {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-semibold tracking-tight mb-6">대시보드</h1>
        <Card className="p-8 flex flex-col items-center justify-center text-center gap-4">
          <AlertCircle
            className="h-12 w-12 text-[hsl(var(--loss))]"
            aria-hidden
          />
          <p className="text-lg font-medium">데이터를 불러올 수 없습니다.</p>
          <p className="text-sm text-muted-foreground">{errorMessage}</p>
          <Button onClick={refresh} variant="secondary" className="gap-2">
            <RefreshCw className="h-4 w-4" aria-hidden />
            다시 시도
          </Button>
        </Card>
      </div>
    )
  }

  const loading = state === "loading" || !data

  // EMPTY: Group has no balance + no transactions + no entities
  const isEmpty =
    !!data &&
    Number(data.cash_kpi.total_balance) === 0 &&
    Number(data.cash_kpi.monthly_income) === 0 &&
    Number(data.cash_kpi.monthly_expense) === 0 &&
    data.bento.entities.every((e) => Number(e.cash_balance) === 0)

  if (isEmpty) {
    return (
      <div className="p-4 lg:p-6 space-y-4">
        <h1 className="text-2xl font-semibold tracking-tight">대시보드</h1>
        <Card className="p-12 flex flex-col items-center justify-center text-center gap-4">
          <Upload className="h-12 w-12 text-muted-foreground" aria-hidden />
          <p className="text-lg font-medium">첫 거래 데이터를 업로드해보세요</p>
          <p className="text-sm text-muted-foreground">
            Excel 파일을 업로드하면 대시보드가 자동으로 업데이트됩니다.
          </p>
          <Button
            asChild
            className="bg-[hsl(var(--color-cta))] text-white gap-2 hover:bg-[hsl(var(--color-cta))]/90"
          >
            <Link href="/upload">
              <Upload className="h-4 w-4" aria-hidden />
              Excel 업로드
            </Link>
          </Button>
        </Card>
      </div>
    )
  }

  return (
    <div className="p-4 lg:p-6 space-y-3">
      <div className="flex items-end justify-between mb-1 gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">대시보드</h1>
        <div className="flex items-center gap-3">
          <DashboardMonthPicker />
          <button
            onClick={refresh}
            className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 px-2 py-1 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--color-cta))]"
            aria-label="대시보드 새로고침"
          >
            <RefreshCw className="h-3 w-3" aria-hidden />
            새로고침
          </button>
        </div>
      </div>

      {/* Top row: Decision Queue (2col) + AI Activity (1col) */}
      <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-3">
        <DecisionQueue
          data={data?.decision_queue ?? null}
          loading={loading}
        />
        <AiActivityFeed
          data={data?.ai_activity ?? null}
          loading={loading}
        />
      </div>

      {/* Accrual gating notice (only if in_progress) */}
      <AccrualGatingNotice accrualKpi={data?.accrual_kpi ?? null} />

      {/* Bento entity selector */}
      <BentoEntitySelector loading={loading} />

      {/* Dual KPI row: 잔고 / 매출 / 비용 / 순이익 */}
      <KpiRow loading={loading} />

      {/* Quick links to other pages */}
      <div className="flex flex-wrap gap-2 pt-2">
        <Button asChild variant="secondary" size="sm">
          <Link href="/cashflow">현금흐름 상세</Link>
        </Button>
        <Button asChild variant="secondary" size="sm">
          <Link href="/transactions">거래 내역</Link>
        </Button>
        <Button asChild variant="secondary" size="sm">
          <Link href="/statements">재무제표</Link>
        </Button>
        <Button asChild variant="secondary" size="sm">
          <Link href="/upload">Excel 업로드</Link>
        </Button>
      </div>
    </div>
  )
}

// ── Month Picker wrapper ─────────────────────────────

function DashboardMonthPicker() {
  const { yearMonth, setYearMonth } = useDashboard()
  // 12개월 옵션 (현재 ~ 11개월 전), 추가로 미래 3개월 선택 가능
  const months = useMemo(() => {
    const now = new Date()
    const arr: string[] = []
    for (let i = 11; i >= -3; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
      arr.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`)
    }
    return arr
  }, [])
  return (
    <MonthPicker
      months={months}
      selected={yearMonth}
      onSelect={setYearMonth}
      allowFuture
    />
  )
}

// ── KPI Row (4 cards) ─────────────────────────────────

function KpiRow({ loading }: { loading: boolean }) {
  const { data } = useDashboard()

  if (loading || !data) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-32" />
        ))}
      </div>
    )
  }

  const { cash_kpi, accrual_kpi } = data

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
      <SingleIndicatorCard
        label="잔고"
        value={cash_kpi.total_balance}
      />
      <DualIndicatorCard
        label="매출"
        accValue={accrual_kpi.revenue_acc}
        cashValue={accrual_kpi.revenue_cash}
        accuracyStatus={accrual_kpi.accuracy_status}
        diffBreakdown={accrual_kpi.diff_breakdown}
        diffKind="revenue"
      />
      <DualIndicatorCard
        label="비용"
        accValue={accrual_kpi.expense_acc}
        cashValue={accrual_kpi.expense_cash}
        accuracyStatus={accrual_kpi.accuracy_status}
        diffBreakdown={accrual_kpi.diff_breakdown}
        diffKind="expense"
      />
      <NetIncomeCard />
    </div>
  )
}

function NetIncomeCard() {
  const { data } = useDashboard()
  if (!data) return null

  const { cash_kpi, accrual_kpi } = data
  const runway = cash_kpi.runway_months
  const showAcc = accrual_kpi.accuracy_status !== "in_progress" && accrual_kpi.net_income_acc != null

  if (showAcc) {
    // 순이익 (acc) + 런웨이 묶음 — DualIndicator 변형
    return (
      <DualIndicatorCard
        label="순이익 / 런웨이"
        accValue={accrual_kpi.net_income_acc}
        cashValue={runway != null ? "0" : "0"}
        accuracyStatus={accrual_kpi.accuracy_status}
        diffBreakdown={null}
        diffKind="revenue"
      />
    )
  }

  // gating 시 런웨이만 표시
  return (
    <SingleIndicatorCard
      label="런웨이"
      value={runway != null ? `${runway}개월` : "N/A"}
      isText
    />
  )
}
