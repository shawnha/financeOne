"use client"

import { useState, useCallback, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { fetchAPI } from "@/lib/api"
import { formatKRW, formatUSD } from "@/lib/format"
import { EntityTabs } from "@/components/entity-tabs"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  FileText,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  Printer,
} from "lucide-react"

type LoadState = "idle" | "loading" | "success" | "error" | "empty"

interface LineItem {
  id: number
  statement_type: string
  account_code: string | null
  line_key: string
  label: string
  sort_order: number
  is_section_header: boolean
  auto_amount: number
  auto_debit: number
  auto_credit: number
  manual_amount: number | null
  manual_debit: number | null
  manual_credit: number | null
  note: string | null
}

interface StatementData {
  id: number
  entity_id: number
  fiscal_year: number
  start_month: number
  end_month: number
  status: string
  line_items: LineItem[]
  entity_name: string
}

interface GenerateResult {
  statement_id: number
  fiscal_year: number
  validation: {
    balance_sheet?: { total_assets: number; total_liabilities: number; total_equity: number; is_balanced: boolean; difference: number; net_income: number }
    income_statement?: { total_revenue: number; net_income: number }
    trial_balance?: { is_balanced: boolean; difference: number }
    cash_flow?: { loop_valid: boolean; ending_cash: number }
    deficit_treatment?: { is_deficit: boolean }
    total_assets?: number; total_liabilities?: number; total_equity?: number; is_balanced?: boolean; difference?: number
  }
  is_consolidated?: boolean
  base_currency?: string
  cta_by_entity?: Record<string, number>
  eliminations_count?: number
}

const STATEMENT_TYPES = [
  { key: "balance_sheet", label: "재무상태표" },
  { key: "income_statement", label: "손익계산서" },
  { key: "cash_flow", label: "현금흐름표" },
  { key: "trial_balance", label: "합계잔액시산표" },
  { key: "deficit_treatment", label: "결손금처리계산서" },
] as const

const currentYear = new Date().getFullYear()
const YEARS = Array.from({ length: 5 }, (_, i) => currentYear - i)

function StatementsContent() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity") || "1"

  const [loadState, setLoadState] = useState<LoadState>("idle")
  const [error, setError] = useState("")
  const [statementData, setStatementData] = useState<StatementData | null>(null)
  const [validation, setValidation] = useState<GenerateResult["validation"] | null>(null)
  const [result, setResult] = useState<GenerateResult | null>(null)
  const [activeTab, setActiveTab] = useState("balance_sheet")
  const [year, setYear] = useState(currentYear.toString())
  const [generating, setGenerating] = useState(false)

  const isConsolidated = entityId === "consolidated"

  const handleGenerate = useCallback(async () => {
    setGenerating(true)
    setError("")
    try {
      const endpoint = isConsolidated
        ? "/statements/generate-consolidated"
        : "/statements/generate"
      const body = isConsolidated
        ? { fiscal_year: Number(year), start_month: 1, end_month: 12 }
        : { entity_id: Number(entityId), fiscal_year: Number(year), start_month: 1, end_month: 12 }

      const result = await fetchAPI<GenerateResult>(endpoint, {
        method: "POST",
        body: JSON.stringify(body),
      })
      setResult(result)
      setValidation(result.validation)

      // 생성된 재무제표 로드
      const data = await fetchAPI<StatementData>(
        `/statements/${result.statement_id}`,
      )
      setStatementData(data)
      setLoadState("success")
    } catch (err) {
      setError(err instanceof Error ? err.message : "재무제표 생성 실패")
      setLoadState("error")
    } finally {
      setGenerating(false)
    }
  }, [entityId, year])

  const effectiveTab = isConsolidated ? "consolidated_balance_sheet" : activeTab
  const filteredItems = statementData?.line_items.filter(
    (item) => item.statement_type === effectiveTab,
  ) || []

  const isTB = activeTab === "trial_balance"

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <Select value={year} onValueChange={setYear}>
          <SelectTrigger className="w-[120px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {YEARS.map((y) => (
              <SelectItem key={y} value={y.toString()}>
                {y}년
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button onClick={handleGenerate} disabled={generating}>
          {generating ? (
            <RefreshCw className="h-4 w-4 animate-spin" />
          ) : (
            <FileText className="h-4 w-4" />
          )}
          {generating ? "생성 중..." : "재무제표 생성"}
        </Button>

        {statementData && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => window.print()}
          >
            <Printer className="h-4 w-4" />
            인쇄
          </Button>
        )}
      </div>

      {/* Validation Summary */}
      {validation && !isConsolidated && (
        <div className="flex flex-wrap gap-2">
          {validation.balance_sheet && (
            <ValidationBadge
              label="재무상태표"
              valid={validation.balance_sheet.is_balanced}
              detail={validation.balance_sheet.is_balanced ? "균형" : `차이 ${formatKRW(validation.balance_sheet.difference)}`}
            />
          )}
          {validation.trial_balance && (
            <ValidationBadge
              label="시산표"
              valid={validation.trial_balance.is_balanced}
              detail={validation.trial_balance.is_balanced ? "균형" : `차이 ${formatKRW(validation.trial_balance.difference)}`}
            />
          )}
          {validation.cash_flow && (
            <ValidationBadge
              label="현금흐름"
              valid={validation.cash_flow.loop_valid}
              detail={validation.cash_flow.loop_valid ? "검증 통과" : "루프 불일치"}
            />
          )}
        </div>
      )}
      {validation && isConsolidated && (
        <div className="flex flex-wrap gap-2">
          <ValidationBadge
            label="연결 BS"
            valid={validation.is_balanced ?? false}
            detail={validation.is_balanced ? "균형" : `차이 $${validation.difference?.toFixed(2)}`}
          />
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-purple-500/10 text-purple-400 border border-purple-500/30">
            CTA: {Object.keys(result?.cta_by_entity || {}).length}개 법인
          </span>
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-blue-500/10 text-blue-400 border border-blue-500/30">
            상계: {result?.eliminations_count ?? 0}건
          </span>
        </div>
      )}

      {/* IDLE / EMPTY state */}
      {loadState === "idle" && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <FileText className="h-12 w-12 text-muted-foreground" />
            <h3 className="mt-4 text-lg font-semibold text-foreground">
              재무제표를 생성해보세요
            </h3>
            <p className="mt-2 text-sm text-muted-foreground max-w-md">
              연도를 선택하고 생성 버튼을 누르면 분개 데이터를 기반으로
              5종 재무제표가 자동으로 생성됩니다.
            </p>
          </CardContent>
        </Card>
      )}

      {/* ERROR state */}
      {loadState === "error" && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <AlertTriangle className="h-12 w-12 text-destructive" />
            <h3 className="mt-4 text-lg font-semibold text-foreground">
              생성 실패
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">{error}</p>
            <Button variant="outline" className="mt-4" onClick={handleGenerate}>
              <RefreshCw className="h-4 w-4" />
              다시 시도
            </Button>
          </CardContent>
        </Card>
      )}

      {/* SUCCESS state */}
      {loadState === "success" && statementData && (
        <Card>
          <CardHeader className="pb-3">
            {/* Tabs */}
            <div className="flex flex-wrap gap-1 border-b border-border -mx-6 px-6 pb-3">
              {STATEMENT_TYPES.map((st) => (
                <button
                  key={st.key}
                  onClick={() => setActiveTab(st.key)}
                  className={`px-3 py-2 text-sm rounded-t-md transition-colors ${
                    activeTab === st.key
                      ? "bg-secondary text-foreground font-medium border-b-2 border-[hsl(var(--accent))]"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {st.label}
                </button>
              ))}
            </div>
            <CardTitle className="text-lg mt-3 print:text-xl">
              {STATEMENT_TYPES.find((s) => s.key === activeTab)?.label} — {statementData.entity_name} ({year}년)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[50%]">계정과목</TableHead>
                    {isTB ? (
                      <>
                        <TableHead className="text-right w-[25%]">차변</TableHead>
                        <TableHead className="text-right w-[25%]">대변</TableHead>
                      </>
                    ) : (
                      <TableHead className="text-right w-[50%]">금액</TableHead>
                    )}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredItems.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={isTB ? 3 : 2}
                        className="text-center text-muted-foreground py-8"
                      >
                        해당 기간에 데이터가 없습니다
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredItems.map((item) => {
                      const effectiveAmount =
                        item.manual_amount !== null
                          ? item.manual_amount
                          : item.auto_amount
                      const effectiveDebit =
                        item.manual_debit !== null
                          ? item.manual_debit
                          : item.auto_debit
                      const effectiveCredit =
                        item.manual_credit !== null
                          ? item.manual_credit
                          : item.auto_credit

                      return (
                        <TableRow
                          key={item.id}
                          className={
                            item.is_section_header
                              ? "font-semibold bg-muted/30"
                              : ""
                          }
                        >
                          <TableCell
                            className={
                              item.is_section_header ? "font-semibold" : ""
                            }
                          >
                            {item.label}
                            {item.account_code && (
                              <span className="ml-2 text-xs text-muted-foreground font-mono">
                                {item.account_code}
                              </span>
                            )}
                          </TableCell>
                          {isTB ? (
                            <>
                              <TableCell className="text-right font-mono tabular-nums">
                                {effectiveDebit !== 0
                                  ? (isConsolidated ? formatUSD(effectiveDebit) : formatKRW(effectiveDebit))
                                  : ""}
                              </TableCell>
                              <TableCell className="text-right font-mono tabular-nums">
                                {effectiveCredit !== 0
                                  ? (isConsolidated ? formatUSD(effectiveCredit) : formatKRW(effectiveCredit))
                                  : ""}
                              </TableCell>
                            </>
                          ) : (
                            <TableCell
                              className={`text-right font-mono tabular-nums ${
                                effectiveAmount < 0 ? "text-[hsl(var(--loss))]" : ""
                              }`}
                            >
                              {isConsolidated ? formatUSD(effectiveAmount) : formatKRW(effectiveAmount)}
                            </TableCell>
                          )}
                        </TableRow>
                      )
                    })
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function ValidationBadge({
  label,
  valid,
  detail,
}: {
  label: string
  valid: boolean
  detail: string
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium ${
        valid
          ? "bg-green-500/10 text-green-500 border border-green-500/30"
          : "bg-red-500/10 text-red-500 border border-red-500/30"
      }`}
    >
      {valid ? (
        <CheckCircle2 className="h-3.5 w-3.5" />
      ) : (
        <AlertTriangle className="h-3.5 w-3.5" />
      )}
      {label}: {detail}
    </span>
  )
}

function StatementsSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex gap-3">
        <Skeleton className="h-10 w-[120px]" />
        <Skeleton className="h-10 w-[160px]" />
      </div>
      <Card>
        <CardContent className="py-6 space-y-3">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

export default function StatementsPage() {
  return (
    <div className="space-y-6">
      <Suspense fallback={<Skeleton className="h-10 w-full border-b" />}>
        <EntityTabs />
      </Suspense>

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-foreground">재무제표</h1>
      </div>

      <Suspense fallback={<StatementsSkeleton />}>
        <StatementsContent />
      </Suspense>
    </div>
  )
}
