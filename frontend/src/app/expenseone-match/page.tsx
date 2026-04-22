"use client"

import { Suspense, useCallback, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { EntityTabs } from "@/components/entity-tabs"
import { MonthPicker } from "@/components/month-picker"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { fetchAPI } from "@/lib/api"
import { formatKRW } from "@/lib/format"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { useGlobalMonth } from "@/hooks/use-global-month"
import {
  Receipt,
  AlertCircle,
  Check,
  Link2,
  Unlink,
  CreditCard,
  Wallet,
  RefreshCw,
  ExternalLink,
  CalendarDays,
  User as UserIcon,
  Building2,
} from "lucide-react"

// ── Types ──────────────────────────────────────────────

interface ExpenseMatchInfo {
  match_id: number
  transaction_id: number
  confidence: number | null
  method: string | null
  is_manual: boolean
  is_confirmed: boolean
  reasoning: string | null
}

interface ExpenseIgnoredInfo {
  id: number
  reason: string | null
  ignored_at: string | null
}

interface Expense {
  expense_id: string
  type: string
  status: string
  title: string
  description: string | null
  amount: number
  category: string | null
  merchant_name: string | null
  transaction_date: string | null
  card_last_four: string | null
  bank_name: string | null
  account_holder: string | null
  is_urgent: boolean
  is_pre_paid: boolean
  approved_at: string | null
  company_id: string | null
  company_name: string | null
  submitter_name: string | null
  entity_id: number | null
  match: ExpenseMatchInfo | null
  ignored: ExpenseIgnoredInfo | null
}

interface Candidate {
  transaction_id: number
  entity_id: number
  entity_name: string | null
  date: string | null
  amount: number
  type: string
  source_type: string
  counterparty: string | null
  card_number: string | null
  description: string | null
  day_diff: number | null
  amount_diff: number | null
  card_tail_match?: boolean
  name_similar?: boolean
  match_hint?: "strong" | "likely" | "weak"
  already_linked_expense: string | null
}

interface CandidatesResponse {
  expense_summary: {
    expense_id: string
    type: string
    amount: number
    date: string
    card_last_four: string | null
    account_holder: string | null
    merchant_name: string | null
    title: string
    entity_id: number | null
  } | null
  candidates: Candidate[]
}

type StatusFilter = "unmatched" | "matched" | "ignored" | "all"
type TypeFilter = "all" | "CORPORATE_CARD" | "DEPOSIT_REQUEST"

const ENTITY_NAMES: Record<number, string> = {
  1: "한아원인터내셔널",
  2: "한아원코리아",
  3: "한아원리테일",
}

// ── Helpers ────────────────────────────────────────────

function formatDate(iso: string | null): string {
  if (!iso) return "-"
  const d = iso.slice(0, 10)
  const [, m, day] = d.split("-")
  return `${Number(m)}/${Number(day)}`
}

function typeBadge(type: string) {
  if (type === "CORPORATE_CARD") {
    return (
      <Badge variant="outline" className="gap-1 text-xs">
        <CreditCard className="h-3 w-3" /> 법인카드
      </Badge>
    )
  }
  if (type === "DEPOSIT_REQUEST") {
    return (
      <Badge variant="outline" className="gap-1 text-xs">
        <Wallet className="h-3 w-3" /> 입금요청
      </Badge>
    )
  }
  return <Badge variant="outline" className="text-xs">{type}</Badge>
}

function sourceLabel(source: string): string {
  const map: Record<string, string> = {
    lotte_card: "롯데카드",
    woori_card: "우리카드",
    shinhan_card: "신한카드",
    codef_lotte_card: "롯데카드",
    codef_woori_card: "우리카드",
    codef_shinhan_card: "신한카드",
    woori_bank: "우리은행",
    codef_woori_bank: "우리은행",
    codef_ibk_bank: "기업은행",
  }
  return map[source] || source
}

function matchStatusBadge(match: ExpenseMatchInfo | null) {
  if (!match) {
    return (
      <Badge variant="outline" className="gap-1 border-amber-500/40 text-amber-300 text-xs">
        <AlertCircle className="h-3 w-3" /> 미매칭
      </Badge>
    )
  }
  if (match.is_confirmed) {
    return (
      <Badge variant="outline" className="gap-1 border-emerald-500/40 text-emerald-300 text-xs">
        <Check className="h-3 w-3" /> 확정
      </Badge>
    )
  }
  const conf = match.confidence ? Math.round(match.confidence * 100) : null
  return (
    <Badge variant="outline" className="gap-1 border-blue-500/40 text-blue-300 text-xs">
      <Link2 className="h-3 w-3" /> 자동 {conf !== null ? `${conf}%` : ""}
    </Badge>
  )
}

// ── Sub-components ─────────────────────────────────────

function ExpenseCard({
  exp,
  selected,
  onClick,
  onIgnore,
  onUnignore,
}: {
  exp: Expense
  selected: boolean
  onClick: () => void
  onIgnore: (expenseId: string) => Promise<void>
  onUnignore: (expenseId: string) => Promise<void>
}) {
  const isIgnored = !!exp.ignored
  return (
    <div
      onClick={onClick}
      className={cn(
        "w-full text-left rounded-lg border px-3 py-2.5 cursor-pointer",
        "transition-all duration-200",
        selected
          ? "border-accent/50 bg-white/[0.04]"
          : "border-white/[0.05] hover:border-white/[0.1] hover:bg-white/[0.02]",
        isIgnored && "opacity-60",
      )}
    >
      <div className="flex items-start justify-between gap-2 mb-1">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {typeBadge(exp.type)}
          {exp.is_urgent && (
            <Badge variant="outline" className="text-[10px] border-rose-500/40 text-rose-300">긴급</Badge>
          )}
          {isIgnored && (
            <Badge variant="outline" className="text-[10px] border-muted-foreground/30 text-muted-foreground">
              무시됨
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {matchStatusBadge(exp.match)}
          {!exp.match && !isIgnored && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                if (window.confirm(`"${exp.title}" 경비를 무시 처리할까요? 언제든 복원할 수 있습니다.`)) {
                  onIgnore(exp.expense_id)
                }
              }}
              className="text-[10px] px-1.5 py-0.5 rounded border border-white/[0.08] text-muted-foreground hover:text-rose-300 hover:border-rose-500/30"
              title="무시 (사이드바 카운트에서 제외)"
            >
              무시
            </button>
          )}
          {isIgnored && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onUnignore(exp.expense_id)
              }}
              className="text-[10px] px-1.5 py-0.5 rounded border border-white/[0.08] text-muted-foreground hover:text-emerald-300 hover:border-emerald-500/30"
              title="복원"
            >
              복원
            </button>
          )}
        </div>
      </div>
      <div className="font-medium text-sm text-foreground truncate">{exp.title || "(제목 없음)"}</div>
      <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground">
        <span className="font-mono text-foreground">{formatKRW(exp.amount)}</span>
        <span>·</span>
        <span>{formatDate(exp.transaction_date)}</span>
        {exp.card_last_four && (
          <>
            <span>·</span>
            <span className="font-mono">****{exp.card_last_four}</span>
          </>
        )}
        {exp.account_holder && (
          <>
            <span>·</span>
            <span>{exp.account_holder}</span>
          </>
        )}
      </div>
      <div className="flex items-center gap-1.5 mt-1 text-[11px] text-muted-foreground/70">
        {exp.submitter_name && (
          <>
            <UserIcon className="h-3 w-3" />
            <span>{exp.submitter_name}</span>
          </>
        )}
        {exp.company_name && (
          <>
            <span>·</span>
            <Building2 className="h-3 w-3" />
            <span>{exp.company_name}</span>
          </>
        )}
      </div>
      {exp.ignored?.reason && (
        <div className="mt-1 text-[10px] text-muted-foreground/60 italic truncate">
          무시 사유: {exp.ignored.reason}
        </div>
      )}
    </div>
  )
}

function CandidatePanel({
  expense,
  crossEntity,
  setCrossEntity,
  onConfirm,
  onUnlink,
  onConfirmAuto,
  onClose,
}: {
  expense: Expense
  crossEntity: boolean
  setCrossEntity: (v: boolean) => void
  onConfirm: (expenseId: string, transactionId: number) => Promise<void>
  onUnlink: (expenseId: string) => Promise<void>
  onConfirmAuto: (expenseId: string) => Promise<void>
  onClose: () => void
}) {
  const [cands, setCands] = useState<Candidate[]>([])
  const [loading, setLoading] = useState(false)
  const [busyTxId, setBusyTxId] = useState<number | null>(null)
  const [amountTolerance, setAmountTolerance] = useState<0 | 1 | 3>(0)
  const [dateWindow, setDateWindow] = useState<number>(10)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        date_window: String(dateWindow),
        cross_entity: String(crossEntity),
        amount_tolerance_pct: String(amountTolerance),
      })
      const data = await fetchAPI<CandidatesResponse>(
        `/expenseone-match/expenses/${expense.expense_id}/candidates?${params}`,
      )
      setCands(data.candidates)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "후보 로드 실패")
    } finally {
      setLoading(false)
    }
  }, [expense.expense_id, crossEntity, amountTolerance, dateWindow])

  useEffect(() => {
    load()
  }, [load])

  const doConfirm = async (txId: number) => {
    setBusyTxId(txId)
    try {
      await onConfirm(expense.expense_id, txId)
    } finally {
      setBusyTxId(null)
    }
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.05]">
        <div className="flex items-center gap-2">
          <Receipt className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium text-sm">매칭 후보</span>
          {loading && <RefreshCw className="h-3 w-3 animate-spin text-muted-foreground" />}
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>닫기</Button>
      </div>

      {/* Expense summary header */}
      <div className="px-4 py-3 bg-white/[0.02] border-b border-white/[0.03] text-sm space-y-1">
        <div className="flex items-center gap-2">
          {typeBadge(expense.type)}
          <span className="font-medium text-foreground truncate">{expense.title}</span>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="font-mono text-foreground">{formatKRW(expense.amount)}</span>
          <span>{formatDate(expense.transaction_date)}</span>
          {expense.card_last_four && <span className="font-mono">****{expense.card_last_four}</span>}
          {expense.account_holder && <span>{expense.account_holder}</span>}
          {expense.entity_id && <span className="text-accent">{ENTITY_NAMES[expense.entity_id]}</span>}
        </div>
        {expense.description && (
          <div className="text-xs text-muted-foreground/80 line-clamp-2 pt-1">{expense.description}</div>
        )}
      </div>

      {/* 현재 매칭 */}
      {expense.match && (
        <div className="px-4 py-3 border-b border-white/[0.05] bg-emerald-500/[0.04]">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs">
              {matchStatusBadge(expense.match)}
              <span className="text-muted-foreground">→ 거래 #{expense.match.transaction_id}</span>
              {expense.match.reasoning && (
                <span className="text-muted-foreground/70 truncate">· {expense.match.reasoning}</span>
              )}
            </div>
            <div className="flex items-center gap-1.5">
              {!expense.match.is_confirmed && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs"
                  onClick={async () => {
                    await onConfirmAuto(expense.expense_id)
                  }}
                >
                  <Check className="h-3 w-3 mr-1" /> 확정
                </Button>
              )}
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-xs text-rose-300 hover:text-rose-200"
                onClick={async () => {
                  await onUnlink(expense.expense_id)
                }}
              >
                <Unlink className="h-3 w-3 mr-1" /> 풀기
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* 매칭 검색 조건 — 금액 허용 / 날짜 윈도우 / 법인 무시 */}
      <div className="flex items-center justify-between gap-3 px-4 py-2 border-b border-white/[0.03] text-xs flex-wrap">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1">
            <span className="text-muted-foreground">금액</span>
            {([0, 1, 3] as const).map((pct) => (
              <button
                key={pct}
                type="button"
                onClick={() => setAmountTolerance(pct)}
                className={cn(
                  "px-2 h-6 rounded-md border text-[11px] transition-colors",
                  amountTolerance === pct
                    ? "bg-accent/20 border-accent/40 text-accent"
                    : "border-white/[0.08] text-muted-foreground hover:bg-white/[0.04]",
                )}
              >
                {pct === 0 ? "정확" : `±${pct}%`}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1">
            <span className="text-muted-foreground">날짜</span>
            {[3, 7, 15, 30].map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDateWindow(d)}
                className={cn(
                  "px-2 h-6 rounded-md border text-[11px] transition-colors",
                  dateWindow === d
                    ? "bg-accent/20 border-accent/40 text-accent"
                    : "border-white/[0.08] text-muted-foreground hover:bg-white/[0.04]",
                )}
              >
                ±{d}d
              </button>
            ))}
          </div>
        </div>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={crossEntity}
            onChange={(e) => setCrossEntity(e.target.checked)}
            className="accent-accent"
          />
          <span>법인 무시</span>
        </label>
      </div>

      {/* 후보 리스트 */}
      <CardContent className="p-0 max-h-[520px] overflow-y-auto">
        {loading && cands.length === 0 ? (
          <div className="p-4 space-y-2">
            {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-14 w-full" />)}
          </div>
        ) : cands.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-muted-foreground text-sm gap-2">
            <AlertCircle className="h-6 w-6 opacity-40" />
            <p>매칭 가능한 거래가 없습니다.</p>
            <p className="text-xs text-muted-foreground/60">
              금액이 정확히 일치하는 거래만 표시됩니다. 날짜 오차 ±10일 기준.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-white/[0.03]">
            {cands.map((c) => {
              const blocked = Boolean(c.already_linked_expense)
              const isBusy = busyTxId === c.transaction_id
              return (
                <li key={c.transaction_id} className="px-4 py-3 hover:bg-white/[0.02]">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 text-xs mb-1">
                        <Badge variant="outline" className="text-[10px]">{sourceLabel(c.source_type)}</Badge>
                        {c.match_hint === "strong" && (
                          <Badge variant="outline" className="text-[10px] border-emerald-500/40 text-emerald-300" title="카드 끝자리 + 금액 정확 일치">
                            강력 매칭
                          </Badge>
                        )}
                        {c.match_hint === "likely" && (
                          <Badge variant="outline" className="text-[10px] border-amber-500/40 text-amber-300" title="카드 끝자리 또는 내용 유사 — 사용자 확인 권장">
                            확인 필요
                          </Badge>
                        )}
                        {c.card_tail_match && (
                          <Badge variant="outline" className="text-[10px] border-blue-500/40 text-blue-300" title="카드 끝자리 일치">
                            끝자리✓
                          </Badge>
                        )}
                        {c.entity_id !== expense.entity_id && c.entity_name && (
                          <Badge variant="outline" className="text-[10px] border-amber-500/40 text-amber-300">
                            {c.entity_name}
                          </Badge>
                        )}
                        <span className="text-muted-foreground flex items-center gap-1">
                          <CalendarDays className="h-3 w-3" />
                          {formatDate(c.date)}
                          {c.day_diff !== null && c.day_diff !== 0 && (
                            <span className="text-muted-foreground/60">±{c.day_diff}d</span>
                          )}
                        </span>
                      </div>
                      <div className="text-sm font-medium text-foreground truncate">
                        {c.counterparty || "(거래처 없음)"}
                      </div>
                      <div className="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
                        <span className="font-mono text-foreground">{formatKRW(c.amount)}</span>
                        {c.amount_diff !== null && c.amount_diff !== 0 && (
                          <span className="text-amber-300/80 font-mono">
                            {c.amount > expense.amount ? "+" : "−"}{formatKRW(Math.abs(c.amount_diff))}
                          </span>
                        )}
                        {c.card_number && <span className="font-mono">{c.card_number}</span>}
                      </div>
                      {blocked && (
                        <div className="text-[11px] text-amber-300/80 mt-1">
                          이미 다른 경비에 매칭됨
                        </div>
                      )}
                    </div>
                    <Button
                      size="sm"
                      variant={blocked ? "outline" : "default"}
                      disabled={blocked || isBusy}
                      onClick={() => doConfirm(c.transaction_id)}
                      className="shrink-0"
                    >
                      {isBusy ? (
                        <RefreshCw className="h-3 w-3 animate-spin" />
                      ) : (
                        <Link2 className="h-3 w-3 mr-1" />
                      )}
                      매칭
                    </Button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

// ── Main ───────────────────────────────────────────────

function ExpenseOneMatchContent() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity") || "1"

  const [expenses, setExpenses] = useState<Expense[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("unmatched")
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all")
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [crossEntity, setCrossEntity] = useState(true)

  const [selectedMonth, setSelectedMonth, monthReady] = useGlobalMonth()

  // 최근 13개월(선택 월 기준 ±6) 을 MonthPicker 후보로
  const availableMonths = useMemo(() => {
    const base = selectedMonth ? new Date(`${selectedMonth}-01`) : new Date()
    const arr: string[] = []
    for (let delta = -12; delta <= 3; delta++) {
      const d = new Date(base.getFullYear(), base.getMonth() + delta, 1)
      arr.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`)
    }
    return arr
  }, [selectedMonth])

  const fetchExpenses = useCallback(
    async (background = false) => {
      if (!monthReady) return
      if (!background) setLoading(true)
      setError(null)
      try {
        const params = new URLSearchParams({
          status: statusFilter,
          entity_id: entityId,
          limit: "300",
        })
        if (typeFilter !== "all") params.set("expense_type", typeFilter)
        if (selectedMonth) params.set("month", selectedMonth)
        const data = await fetchAPI<{ expenses: Expense[]; total: number }>(
          `/expenseone-match/expenses?${params}`,
        )
        setExpenses(data.expenses)
      } catch (err) {
        setError(err instanceof Error ? err.message : "데이터 로드 실패")
      } finally {
        setLoading(false)
      }
    },
    [entityId, statusFilter, typeFilter, selectedMonth, monthReady],
  )

  useEffect(() => {
    fetchExpenses()
  }, [fetchExpenses])

  useEffect(() => {
    setSelectedId(null)
  }, [entityId, statusFilter, typeFilter, selectedMonth])

  const selected = useMemo(
    () => expenses.find((e) => e.expense_id === selectedId) || null,
    [expenses, selectedId],
  )

  const handleConfirm = useCallback(
    async (expenseId: string, transactionId: number) => {
      try {
        await fetchAPI(`/expenseone-match/expenses/${expenseId}/confirm`, {
          method: "POST",
          body: JSON.stringify({ transaction_id: transactionId }),
        })
        toast.success("매칭 확정")
        await fetchExpenses(true)
        // auto advance to next unmatched
        const idx = expenses.findIndex((e) => e.expense_id === expenseId)
        const next = expenses.slice(idx + 1).find((e) => !e.match)
        setSelectedId(next?.expense_id ?? null)
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "매칭 실패")
      }
    },
    [expenses, fetchExpenses],
  )

  const handleUnlink = useCallback(
    async (expenseId: string) => {
      try {
        await fetchAPI(`/expenseone-match/expenses/${expenseId}/match`, { method: "DELETE" })
        toast.success("매칭 해제")
        await fetchExpenses(true)
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "해제 실패")
      }
    },
    [fetchExpenses],
  )

  const handleConfirmAuto = useCallback(
    async (expenseId: string) => {
      try {
        await fetchAPI(`/expenseone-match/expenses/${expenseId}/confirm-auto`, { method: "POST" })
        toast.success("자동 매칭 확정")
        await fetchExpenses(true)
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "확정 실패")
      }
    },
    [fetchExpenses],
  )

  const handleIgnore = useCallback(
    async (expenseId: string) => {
      try {
        await fetchAPI(`/expenseone-match/expenses/${expenseId}/ignore`, {
          method: "POST",
          body: JSON.stringify({ reason: null }),
        })
        toast.success("무시 처리")
        if (selectedId === expenseId) setSelectedId(null)
        await fetchExpenses(true)
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "무시 실패")
      }
    },
    [fetchExpenses, selectedId],
  )

  const handleUnignore = useCallback(
    async (expenseId: string) => {
      try {
        await fetchAPI(`/expenseone-match/expenses/${expenseId}/ignore`, { method: "DELETE" })
        toast.success("복원")
        await fetchExpenses(true)
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "복원 실패")
      }
    },
    [fetchExpenses],
  )

  const unmatchedCount = expenses.filter((e) => !e.match).length
  const autoCount = expenses.filter((e) => e.match && !e.match.is_confirmed).length
  const confirmedCount = expenses.filter((e) => e.match?.is_confirmed).length

  return (
    <div className="space-y-5">
      <Suspense fallback={<Skeleton className="h-10 w-full" />}>
        <EntityTabs />
      </Suspense>

      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Receipt className="h-6 w-6 text-muted-foreground" />
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            ExpenseOne 매칭
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <MonthPicker
            months={availableMonths}
            selected={selectedMonth}
            onSelect={setSelectedMonth}
            allowFuture
          />
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchExpenses(true)}
            disabled={loading}
          >
            <RefreshCw className={cn("h-3.5 w-3.5 mr-1.5", loading && "animate-spin")} />
            새로고침
          </Button>
        </div>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-3 gap-3">
        <Card>
          <CardContent className="p-4">
            <div className="text-xs text-muted-foreground">미매칭</div>
            <div className="text-2xl font-semibold text-amber-300 mt-1">{unmatchedCount}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="text-xs text-muted-foreground">자동 매칭 (미확정)</div>
            <div className="text-2xl font-semibold text-blue-300 mt-1">{autoCount}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="text-xs text-muted-foreground">확정</div>
            <div className="text-2xl font-semibold text-emerald-300 mt-1">{confirmedCount}</div>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as StatusFilter)}>
          <SelectTrigger className="w-40 h-9 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="unmatched">미매칭</SelectItem>
            <SelectItem value="matched">매칭 완료</SelectItem>
            <SelectItem value="ignored">무시됨</SelectItem>
            <SelectItem value="all">전체</SelectItem>
          </SelectContent>
        </Select>
        <Select value={typeFilter} onValueChange={(v) => setTypeFilter(v as TypeFilter)}>
          <SelectTrigger className="w-40 h-9 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">모든 타입</SelectItem>
            <SelectItem value="CORPORATE_CARD">법인카드</SelectItem>
            <SelectItem value="DEPOSIT_REQUEST">입금요청</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground ml-auto">{expenses.length}건</span>
      </div>

      {/* Main layout: list + detail */}
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] gap-4">
        {/* Left: expense list */}
        <div className="space-y-2">
          {error && (
            <Card>
              <CardContent className="p-4 flex items-center gap-2 text-rose-300 text-sm">
                <AlertCircle className="h-4 w-4" />
                <span>{error}</span>
              </CardContent>
            </Card>
          )}
          {loading && expenses.length === 0 ? (
            [...Array(6)].map((_, i) => <Skeleton key={i} className="h-20 w-full" />)
          ) : expenses.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16 gap-2 text-muted-foreground">
                <Check className="h-8 w-8 opacity-40" />
                <p className="text-sm">
                  {statusFilter === "unmatched" ? "미매칭 경비가 없습니다." : "표시할 경비가 없습니다."}
                </p>
                {statusFilter === "unmatched" && (
                  <p className="text-xs text-muted-foreground/60">모든 ExpenseOne 경비가 매칭되었습니다.</p>
                )}
              </CardContent>
            </Card>
          ) : (
            expenses.map((exp) => (
              <ExpenseCard
                key={exp.expense_id}
                exp={exp}
                selected={selectedId === exp.expense_id}
                onClick={() => setSelectedId(exp.expense_id)}
                onIgnore={handleIgnore}
                onUnignore={handleUnignore}
              />
            ))
          )}
        </div>

        {/* Right: candidates */}
        <div className="lg:sticky lg:top-4 lg:self-start">
          {selected ? (
            <CandidatePanel
              key={selected.expense_id}
              expense={selected}
              crossEntity={crossEntity}
              setCrossEntity={setCrossEntity}
              onConfirm={handleConfirm}
              onUnlink={handleUnlink}
              onConfirmAuto={handleConfirmAuto}
              onClose={() => setSelectedId(null)}
            />
          ) : (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16 gap-2 text-muted-foreground">
                <ExternalLink className="h-8 w-8 opacity-40" />
                <p className="text-sm">왼쪽에서 경비를 선택하세요.</p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

export default function ExpenseOneMatchPage() {
  return (
    <Suspense fallback={<Skeleton className="h-screen w-full" />}>
      <ExpenseOneMatchContent />
    </Suspense>
  )
}
