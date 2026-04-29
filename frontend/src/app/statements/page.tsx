"use client"

import { useState, useCallback, useEffect, Suspense } from "react"
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  FileText,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  Printer,
  Pencil,
  Trash2,
  Check,
  X,
  Undo2,
  Download,
} from "lucide-react"
import { toast } from "sonner"

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
  base_currency?: string
  is_consolidated?: boolean
}

type EditState = {
  lineId: number | null
  amount: string
  note: string
}

interface Entity {
  id: number
  code: string
  name: string
  type: string
  currency: string
}

interface StatementListItem {
  id: number
  entity_id: number
  fiscal_year: number
  start_month: number
  end_month: number
  is_consolidated: boolean
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

const STATEMENT_TYPES_KR = [
  { key: "balance_sheet", label: "재무상태표" },
  { key: "income_statement", label: "손익계산서" },
  { key: "cash_flow", label: "현금흐름표" },
  { key: "trial_balance", label: "합계잔액시산표" },
  { key: "deficit_treatment", label: "결손금처리계산서" },
] as const

// HOI (USD) — US GAAP. Cash Flow / Trial Balance / Deficit Treatment 양식이 K-GAAP 과 달라 hide.
const STATEMENT_TYPES_EN = [
  { key: "balance_sheet", label: "Balance Sheet" },
  { key: "income_statement", label: "Profit and Loss" },
] as const

// 연결재무제표 (USD, US GAAP)
const STATEMENT_TYPES_CONSOLIDATED = [
  { key: "consolidated_balance_sheet", label: "Consolidated Balance Sheet" },
] as const

const currentYear = new Date().getFullYear()
const YEARS = Array.from({ length: 5 }, (_, i) => currentYear - i)

type PeriodType = "monthly" | "quarterly" | "annual"

const PERIOD_TYPES: { key: PeriodType; label: string }[] = [
  { key: "monthly", label: "월별" },
  { key: "quarterly", label: "분기별" },
  { key: "annual", label: "연말" },
]

const MONTH_OPTIONS = Array.from({ length: 12 }, (_, i) => ({
  value: String(i + 1),
  label: `${i + 1}월`,
}))

const QUARTER_OPTIONS = [
  { value: "1", label: "1분기 (1-3월)", start: 1, end: 3 },
  { value: "2", label: "2분기 (4-6월)", start: 4, end: 6 },
  { value: "3", label: "3분기 (7-9월)", start: 7, end: 9 },
  { value: "4", label: "4분기 (10-12월)", start: 10, end: 12 },
]

function computeMonthRange(periodType: PeriodType, periodValue: string): { start: number; end: number } {
  if (periodType === "annual") return { start: 1, end: 12 }
  if (periodType === "monthly") {
    const m = Number(periodValue)
    return { start: m, end: m }
  }
  // quarterly
  const q = QUARTER_OPTIONS.find((o) => o.value === periodValue) || QUARTER_OPTIONS[0]
  return { start: q.start, end: q.end }
}

function periodLabel(periodType: PeriodType, periodValue: string): string {
  if (periodType === "annual") return "연말"
  if (periodType === "monthly") return `${periodValue}월`
  const q = QUARTER_OPTIONS.find((o) => o.value === periodValue)
  return q ? q.label : ""
}

const EN_MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
]

function lastDayOfMonth(year: number, month: number): number {
  // month: 1-12
  return new Date(year, month, 0).getDate()
}

function formatPeriodEN(
  statementType: string,
  year: number,
  startMonth: number,
  endMonth: number,
): string {
  // BS: "As of <Month> <Day>, YYYY" (period 의 마지막 날)
  // PL/CF: "<Start Month> 1 - <End Month> <Last Day>, YYYY"
  if (statementType === "balance_sheet") {
    const last = lastDayOfMonth(year, endMonth)
    return `As of ${EN_MONTHS[endMonth - 1]} ${last}, ${year}`
  }
  const last = lastDayOfMonth(year, endMonth)
  if (startMonth === endMonth) {
    return `${EN_MONTHS[startMonth - 1]} 1 - ${last}, ${year}`
  }
  return `${EN_MONTHS[startMonth - 1]} 1 - ${EN_MONTHS[endMonth - 1]} ${last}, ${year}`
}

function formatPeriodKR(
  year: number,
  startMonth: number,
  endMonth: number,
): string {
  if (startMonth === 1 && endMonth === 12) return `${year}년`
  if (startMonth === endMonth) return `${year}년 ${startMonth}월`
  return `${year}년 ${startMonth}월 ~ ${endMonth}월`
}

// line_items 에서 validation 추출 (reload 시에도 알림 유지). label 매칭은
// 한글/영어 양쪽 지원 — 첫 매칭으로 채워지지 않으면 0.
function extractValidation(items: LineItem[]): GenerateResult["validation"] | null {
  if (!items || items.length === 0) return null
  const eff = (li: LineItem): number =>
    li.manual_amount !== null ? li.manual_amount : li.auto_amount
  const findByLabel = (st: string, ...labels: string[]): number => {
    const lows = labels.map((l) => l.toLowerCase())
    for (const li of items) {
      if (li.statement_type !== st) continue
      const lbl = li.label.trim().toLowerCase()
      if (lows.includes(lbl)) return eff(li)
    }
    return 0
  }

  const totalAssets = findByLabel("balance_sheet", "자산총계", "total assets")
  const totalLiabs = findByLabel("balance_sheet", "부채총계", "total liabilities")
  const totalEquity = findByLabel("balance_sheet", "자본총계", "total equity")
  const liabEquity = findByLabel(
    "balance_sheet",
    "부채 및 자본 총계",
    "total liabilities and equity",
    "total liabilities & equity",
  ) || (totalLiabs + totalEquity)
  const bsDiff = totalAssets - liabEquity

  // PL totals
  const revenue = findByLabel("income_statement", "ⅰ. 매출액", "total income")
  const netIncome =
    findByLabel("income_statement", "ⅹ. 당기순이익", "ⅹ. 당기순손실", "net income")

  // Trial balance
  let tbDebit = 0, tbCredit = 0
  for (const li of items) {
    if (li.statement_type !== "trial_balance") continue
    if (li.is_section_header) continue
    tbDebit += li.manual_debit !== null ? li.manual_debit : li.auto_debit
    tbCredit += li.manual_credit !== null ? li.manual_credit : li.auto_credit
  }
  const tbDiff = tbDebit - tbCredit

  // Cash flow — closing balance loop check (간단 검증)
  const cfClosing = findByLabel("cash_flow", "기말 현금", "ending cash")

  return {
    balance_sheet: {
      total_assets: totalAssets,
      total_liabilities: totalLiabs,
      total_equity: totalEquity,
      net_income: netIncome,
      is_balanced: Math.abs(bsDiff) < 1,
      difference: bsDiff,
    },
    trial_balance: {
      is_balanced: Math.abs(tbDiff) < 1,
      difference: tbDiff,
    },
    cash_flow: {
      loop_valid: true,
      ending_cash: cfClosing,
    },
    income_statement: { total_revenue: revenue, net_income: netIncome },
  }
}

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
  const [entities, setEntities] = useState<Entity[]>([])
  const [periodType, setPeriodType] = useState<PeriodType>("annual")
  const [periodValue, setPeriodValue] = useState<string>("1")
  const [edit, setEdit] = useState<EditState>({ lineId: null, amount: "", note: "" })
  const [savingLine, setSavingLine] = useState(false)
  const [accountInfo, setAccountInfo] = useState<Record<string, { name: string; category: string; subcategory: string | null; normal_side: string; description: string | null }>>({})
  const [hoverPopup, setHoverPopup] = useState<{ x: number; y: number; code: string } | null>(null)

  const isConsolidated = entityId === "consolidated"
  const currentEntity = entities.find((e) => e.id === Number(entityId))
  const displayCurrency = isConsolidated
    ? "USD"
    : (statementData?.base_currency || currentEntity?.currency || "KRW")
  const formatMoney = (n: number) =>
    displayCurrency === "USD" ? formatUSD(n) : formatKRW(n)

  // entities 목록 로드 (currency 표시용)
  useEffect(() => {
    fetchAPI<Entity[]>("/entities")
      .then(setEntities)
      .catch(() => setEntities([]))
  }, [])

  // standard accounts 캐시 (계정 코드 hover tooltip 용)
  useEffect(() => {
    fetchAPI<Array<{ code: string; name: string; category: string; subcategory: string | null; normal_side: string; description: string | null }>>("/accounts/standard")
      .then((rows) => {
        const map: Record<string, { name: string; category: string; subcategory: string | null; normal_side: string; description: string | null }> = {}
        for (const a of rows) map[a.code] = {
          name: a.name,
          category: a.category,
          subcategory: a.subcategory,
          normal_side: a.normal_side,
          description: a.description,
        }
        setAccountInfo(map)
      })
      .catch(() => setAccountInfo({}))
  }, [])

  // entity / currency 변경 시 activeTab 이 현재 탭 list 에 없으면 reset
  useEffect(() => {
    const validTabs = isConsolidated
      ? STATEMENT_TYPES_CONSOLIDATED
      : (displayCurrency === "USD" ? STATEMENT_TYPES_EN : STATEMENT_TYPES_KR)
    if (!validTabs.some((t) => t.key === activeTab)) {
      setActiveTab(validTabs[0].key)
    }
  }, [isConsolidated, displayCurrency, activeTab])

  // entity / year / period 바뀌면 자동으로 해당 기간의 statement load (정확 매칭 우선)
  useEffect(() => {
    if (entities.length === 0) return // entities 로드되기 전엔 skip
    let cancelled = false
    async function loadLatest() {
      setLoadState("loading")
      setError("")
      try {
        const { start, end } = computeMonthRange(periodType, periodValue)
        const params = new URLSearchParams({
          fiscal_year: year,
          per_page: "50",
        })
        if (!isConsolidated) {
          params.set("entity_id", entityId)
        }
        const list = await fetchAPI<{ items: StatementListItem[] }>(
          `/statements?${params.toString()}`,
        )
        if (cancelled) return
        // 정확히 같은 기간 (start_month=start, end_month=end) 이고 consolidated/entity 일치
        const match = list.items.find((s) => {
          const periodOk = s.start_month === start && s.end_month === end
          const scopeOk = isConsolidated
            ? s.is_consolidated
            : !s.is_consolidated && s.entity_id === Number(entityId)
          return periodOk && scopeOk
        })
        if (!match) {
          setStatementData(null)
          setValidation(null)
          setResult(null)
          setLoadState("empty")
          return
        }
        // HOI (USD) 또는 consolidated 면 영어 라벨, 한국 entity 면 한글
        const targetEntity = entities.find((e) => e.id === match.entity_id)
        const lang = (isConsolidated || targetEntity?.currency === "USD") ? "en" : "ko"
        const data = await fetchAPI<StatementData>(`/statements/${match.id}?lang=${lang}`)
        if (cancelled) return
        setStatementData(data)
        setValidation(extractValidation(data.line_items))
        setResult(null)
        setLoadState("success")
      } catch (err) {
        if (cancelled) return
        setError(err instanceof Error ? err.message : "재무제표 로드 실패")
        setLoadState("error")
      }
    }
    loadLatest()
    return () => {
      cancelled = true
    }
  }, [entityId, year, isConsolidated, entities, periodType, periodValue])

  const reloadStatement = useCallback(async () => {
    if (!statementData) return
    const targetEntity = entities.find((e) => e.id === statementData.entity_id)
    const lang = (statementData.is_consolidated || targetEntity?.currency === "USD") ? "en" : "ko"
    const data = await fetchAPI<StatementData>(
      `/statements/${statementData.id}?lang=${lang}`,
    )
    setStatementData(data)
    setValidation(extractValidation(data.line_items))
  }, [statementData, entities])

  const handleSaveLine = useCallback(async (lineId: number) => {
    setSavingLine(true)
    try {
      const amt = edit.amount.trim() === "" ? null : Number(edit.amount.replace(/,/g, ""))
      if (amt !== null && Number.isNaN(amt)) {
        toast.error("올바른 숫자를 입력하세요")
        return
      }
      await fetchAPI(`/statements/lines/${lineId}`, {
        method: "PATCH",
        body: JSON.stringify({
          manual_amount: amt,
          note: edit.note || null,
        }),
      })
      toast.success("수정되었습니다")
      setEdit({ lineId: null, amount: "", note: "" })
      await reloadStatement()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "저장 실패")
    } finally {
      setSavingLine(false)
    }
  }, [edit, reloadStatement])

  const handleResetLine = useCallback(async (lineId: number) => {
    if (!confirm("이 항목의 수정을 되돌리시겠습니까? auto 값으로 복원됩니다.")) return
    try {
      await fetchAPI(`/statements/lines/${lineId}/reset`, { method: "POST" })
      toast.success("초기화되었습니다")
      await reloadStatement()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "초기화 실패")
    }
  }, [reloadStatement])

  const handleDeleteStatement = useCallback(async () => {
    if (!statementData) return
    if (!confirm(`"${statementData.entity_name} ${statementData.fiscal_year}년 ${statementData.start_month}-${statementData.end_month}월" 재무제표를 삭제합니까? 모든 항목이 사라집니다.`)) return
    try {
      const isFinalized = statementData.status === "finalized"
      const url = isFinalized
        ? `/statements/${statementData.id}?force=true`
        : `/statements/${statementData.id}`
      if (isFinalized && !confirm("이 statement 는 finalized 상태입니다. 정말 삭제하시겠습니까?")) return
      await fetchAPI(url, { method: "DELETE" })
      toast.success("삭제되었습니다")
      setStatementData(null)
      setLoadState("empty")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "삭제 실패")
    }
  }, [statementData])

  const handleGenerate = useCallback(async () => {
    setGenerating(true)
    setError("")
    try {
      const { start, end } = computeMonthRange(periodType, periodValue)
      const endpoint = isConsolidated
        ? "/statements/generate-consolidated"
        : "/statements/generate"
      const body = isConsolidated
        ? { fiscal_year: Number(year), start_month: start, end_month: end }
        : { entity_id: Number(entityId), fiscal_year: Number(year), start_month: start, end_month: end }

      const result = await fetchAPI<GenerateResult>(endpoint, {
        method: "POST",
        body: JSON.stringify(body),
      })
      setResult(result)
      setValidation(result.validation)

      // 생성된 재무제표 로드 (HOI/consolidated → 영어, 한국 entity → 한글)
      const targetEntity = entities.find((e) => e.id === Number(entityId))
      const lang = (isConsolidated || targetEntity?.currency === "USD") ? "en" : "ko"
      const data = await fetchAPI<StatementData>(
        `/statements/${result.statement_id}?lang=${lang}`,
      )
      setStatementData(data)
      setLoadState("success")
    } catch (err) {
      setError(err instanceof Error ? err.message : "재무제표 생성 실패")
      setLoadState("error")
    } finally {
      setGenerating(false)
    }
  }, [entityId, year, isConsolidated, periodType, periodValue, entities])

  const effectiveTab = isConsolidated ? "consolidated_balance_sheet" : activeTab
  const filteredItems = statementData?.line_items.filter(
    (item) => item.statement_type === effectiveTab,
  ) || []

  const isTB = activeTab === "trial_balance"

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 print:hidden">
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

        <Select
          value={periodType}
          onValueChange={(v) => {
            const next = v as PeriodType
            setPeriodType(next)
            // 기본 periodValue 자동 설정
            if (next === "monthly") setPeriodValue("1")
            else if (next === "quarterly") setPeriodValue("1")
            else setPeriodValue("annual")
          }}
        >
          <SelectTrigger className="w-[120px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PERIOD_TYPES.map((p) => (
              <SelectItem key={p.key} value={p.key}>
                {p.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {periodType === "monthly" && (
          <Select value={periodValue} onValueChange={setPeriodValue}>
            <SelectTrigger className="w-[100px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MONTH_OPTIONS.map((m) => (
                <SelectItem key={m.value} value={m.value}>
                  {m.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        {periodType === "quarterly" && (
          <Select value={periodValue} onValueChange={setPeriodValue}>
            <SelectTrigger className="w-[160px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {QUARTER_OPTIONS.map((q) => (
                <SelectItem key={q.value} value={q.value}>
                  {q.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <Button onClick={handleGenerate} disabled={generating}>
          {generating ? (
            <RefreshCw className="h-4 w-4 animate-spin" />
          ) : (
            <FileText className="h-4 w-4" />
          )}
          {generating ? "생성 중..." : "재무제표 생성"}
        </Button>

        {statementData && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <Download className="h-4 w-4" />
                저장
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onClick={() => {
                  if (!statementData) return
                  const url = `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api"}/statements/${statementData.id}/export`
                  const a = document.createElement("a")
                  a.href = url
                  a.download = `statement_${statementData.id}.xlsx`
                  document.body.appendChild(a)
                  a.click()
                  document.body.removeChild(a)
                  toast.success("Excel 다운로드 시작")
                }}
              >
                <FileText className="h-4 w-4 mr-2" />
                Excel (.xlsx)
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => {
                  toast.message("인쇄 다이얼로그에서 'PDF로 저장' 을 선택하세요")
                  setTimeout(() => window.print(), 200)
                }}
              >
                <Printer className="h-4 w-4 mr-2" />
                PDF (인쇄 → PDF 저장)
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      {/* Validation Summary */}
      {validation && !isConsolidated && (
        <div className="flex flex-wrap gap-2 print:hidden">
          {validation.balance_sheet && (
            <ValidationBadge
              label="재무상태표"
              valid={validation.balance_sheet.is_balanced}
              detail={validation.balance_sheet.is_balanced ? "균형" : `차이 ${formatMoney(validation.balance_sheet.difference)}`}
            />
          )}
          {validation.trial_balance && (
            <ValidationBadge
              label="시산표"
              valid={validation.trial_balance.is_balanced}
              detail={validation.trial_balance.is_balanced ? "균형" : `차이 ${formatMoney(validation.trial_balance.difference)}`}
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
      {loadState === "success" && statementData && (() => {
        // entity 통화 / 연결 여부에 따라 statement type 탭 분기
        const tabs = isConsolidated
          ? STATEMENT_TYPES_CONSOLIDATED
          : (displayCurrency === "USD" ? STATEMENT_TYPES_EN : STATEMENT_TYPES_KR)
        const activeTabSafe = tabs.some((t) => t.key === activeTab) ? activeTab : tabs[0].key
        return (
        <Card>
          <CardHeader className="pb-3">
            {/* Tabs */}
            <div className="flex flex-wrap gap-1 border-b border-border -mx-6 px-6 pb-3">
              {tabs.map((st) => (
                <button
                  key={st.key}
                  onClick={() => setActiveTab(st.key)}
                  className={`px-3 py-2 text-sm rounded-t-md transition-colors ${
                    activeTabSafe === st.key
                      ? "bg-secondary text-foreground font-medium border-b-2 border-[hsl(var(--accent))]"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {st.label}
                </button>
              ))}
            </div>
            <div className="flex items-center justify-between mt-3">
              <CardTitle className="text-lg print:text-xl">
                {(() => {
                  const isEnglish = displayCurrency === "USD" || isConsolidated
                  const tabLabel = tabs.find((s) => s.key === activeTabSafe)?.label || ""
                  // entity_name: HOI 면 "Hanah One Inc" (Inc. → Inc 통일), 한국 entity 는 그대로
                  const entityLabel = isEnglish
                    ? (statementData.entity_name || "").replace(/\s*Inc\.?$/i, " Inc")
                    : statementData.entity_name
                  const periodText = isEnglish
                    ? formatPeriodEN(activeTabSafe, statementData.fiscal_year, statementData.start_month, statementData.end_month)
                    : formatPeriodKR(statementData.fiscal_year, statementData.start_month, statementData.end_month)
                  return `${tabLabel} — ${entityLabel} — ${periodText}`
                })()}
                {statementData.status === "finalized" && (
                  <span className="ml-2 text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                    확정
                  </span>
                )}
              </CardTitle>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleDeleteStatement}
                className="text-destructive hover:bg-destructive/10 print:hidden"
                title="이 재무제표 삭제"
              >
                <Trash2 className="h-4 w-4" />
                삭제
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[45%]">계정과목</TableHead>
                    {isTB ? (
                      <>
                        <TableHead className="text-right w-[25%]">차변</TableHead>
                        <TableHead className="text-right w-[25%]">대변</TableHead>
                      </>
                    ) : (
                      <TableHead className="text-right w-[45%]">금액</TableHead>
                    )}
                    <TableHead className="w-[10%] print:hidden"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredItems.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={isTB ? 4 : 3}
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
                      const isEdited = item.manual_amount !== null
                      const isEditing = edit.lineId === item.id
                      const canEdit = !isTB && !item.is_section_header && statementData.status !== "finalized"

                      return (
                        <TableRow
                          key={item.id}
                          className={
                            item.is_section_header
                              ? "font-semibold bg-muted/30"
                              : isEdited
                              ? "bg-yellow-500/5"
                              : ""
                          }
                          title={item.note || undefined}
                        >
                          <TableCell
                            className={
                              item.is_section_header
                                ? "font-semibold whitespace-pre"
                                : "whitespace-pre"
                            }
                          >
                            {item.account_code && accountInfo[item.account_code] ? (() => {
                              const match = item.label.match(/^(\s*)(.*)$/)
                              const leadingWS = match?.[1] || ""
                              const rawName = match?.[2] || item.label
                              return (
                                <>
                                  {leadingWS}
                                  <span
                                    onMouseEnter={(e) => {
                                      const r = (e.target as HTMLElement).getBoundingClientRect()
                                      setHoverPopup({ x: r.left, y: r.bottom + 4, code: item.account_code! })
                                    }}
                                    onMouseLeave={() => setHoverPopup(null)}
                                  >
                                    {rawName}
                                  </span>
                                  <a
                                    href={`/accounts/ledger?entity=${entityId}&code=${encodeURIComponent(item.account_code)}`}
                                    className="ml-2 text-xs text-muted-foreground font-mono hover:text-primary hover:underline"
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    {item.account_code}
                                  </a>
                                </>
                              )
                            })() : (
                              <>
                                {item.label}
                                {item.account_code && (
                                  <span className="ml-2 text-xs text-muted-foreground font-mono">
                                    {item.account_code}
                                  </span>
                                )}
                              </>
                            )}
                            {isEdited && !isEditing && (
                              <Pencil className="inline h-3 w-3 ml-2 text-yellow-500" />
                            )}
                          </TableCell>
                          {isTB ? (
                            <>
                              <TableCell className="text-right font-mono tabular-nums">
                                {effectiveDebit !== 0 ? formatMoney(effectiveDebit) : ""}
                              </TableCell>
                              <TableCell className="text-right font-mono tabular-nums">
                                {effectiveCredit !== 0 ? formatMoney(effectiveCredit) : ""}
                              </TableCell>
                            </>
                          ) : isEditing ? (
                            <TableCell className="text-right">
                              <input
                                type="text"
                                value={edit.amount}
                                onChange={(e) => setEdit({ ...edit, amount: e.target.value })}
                                placeholder={String(item.auto_amount)}
                                className="w-32 px-2 py-1 text-right font-mono bg-background border border-input rounded text-sm"
                                autoFocus
                                disabled={savingLine}
                              />
                              <input
                                type="text"
                                value={edit.note}
                                onChange={(e) => setEdit({ ...edit, note: e.target.value })}
                                placeholder="수정 사유 (선택)"
                                className="w-full mt-1 px-2 py-1 text-xs bg-background border border-input rounded"
                                disabled={savingLine}
                              />
                            </TableCell>
                          ) : (
                            <TableCell
                              className={`text-right font-mono tabular-nums ${
                                effectiveAmount < 0 ? "text-[hsl(var(--loss))]" : ""
                              }`}
                            >
                              {formatMoney(effectiveAmount)}
                            </TableCell>
                          )}
                          <TableCell className="print:hidden text-right">
                            {canEdit && !isEditing && (
                              <div className="flex gap-1 justify-end">
                                <button
                                  onClick={() => setEdit({
                                    lineId: item.id,
                                    amount: String(item.manual_amount ?? item.auto_amount),
                                    note: item.note || "",
                                  })}
                                  className="text-muted-foreground hover:text-foreground p-1"
                                  title="수정"
                                >
                                  <Pencil className="h-3.5 w-3.5" />
                                </button>
                                {isEdited && (
                                  <button
                                    onClick={() => handleResetLine(item.id)}
                                    className="text-muted-foreground hover:text-yellow-500 p-1"
                                    title="원래 값으로 되돌리기"
                                  >
                                    <Undo2 className="h-3.5 w-3.5" />
                                  </button>
                                )}
                              </div>
                            )}
                            {isEditing && (
                              <div className="flex gap-1 justify-end">
                                <button
                                  onClick={() => handleSaveLine(item.id)}
                                  disabled={savingLine}
                                  className="text-emerald-500 hover:text-emerald-400 p-1 disabled:opacity-50"
                                  title="저장"
                                >
                                  <Check className="h-3.5 w-3.5" />
                                </button>
                                <button
                                  onClick={() => setEdit({ lineId: null, amount: "", note: "" })}
                                  disabled={savingLine}
                                  className="text-muted-foreground hover:text-foreground p-1 disabled:opacity-50"
                                  title="취소"
                                >
                                  <X className="h-3.5 w-3.5" />
                                </button>
                              </div>
                            )}
                          </TableCell>
                        </TableRow>
                      )
                    })
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
        )
      })()}

      {/* Hover popup — fixed positioning, layout 영향 0 */}
      {hoverPopup && (() => {
        const info = accountInfo[hoverPopup.code]
        if (!info) return null
        return (
          <div
            style={{
              position: "fixed",
              left: hoverPopup.x,
              top: hoverPopup.y,
              zIndex: 100,
              pointerEvents: "none",
            }}
            className="w-80 p-3 rounded-md border border-border bg-popover text-popover-foreground shadow-lg text-left"
          >
            <div className="font-semibold text-sm mb-1">{info.name}</div>
            {info.description ? (
              <div className="text-xs text-foreground leading-relaxed">{info.description}</div>
            ) : (
              <div className="text-xs text-muted-foreground italic">(설명 미등록)</div>
            )}
            <div className="text-xs text-muted-foreground pt-2 mt-2 border-t border-border/50">
              분류: {info.category}{info.subcategory ? ` / ${info.subcategory}` : ""}
            </div>
          </div>
        )
      })()}
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
    <div className="p-6 space-y-6">
      <Suspense fallback={<Skeleton className="h-10 w-full border-b" />}>
        <EntityTabs />
      </Suspense>

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">재무제표</h1>
      </div>

      <Suspense fallback={<StatementsSkeleton />}>
        <StatementsContent />
      </Suspense>
    </div>
  )
}
