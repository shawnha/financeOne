"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams, useRouter } from "next/navigation"
import { fetchAPI, APIError } from "@/lib/api"
import { AccountCombobox } from "@/components/account-combobox"
import { formatKRW, formatByEntity } from "@/lib/format"
import { cn } from "@/lib/utils"
import { EntityTabs } from "@/components/entity-tabs"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import {
  Search, Download, ChevronLeft, ChevronRight, X, AlertTriangle, Upload, RotateCw,
} from "lucide-react"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Transaction {
  id: number
  entity_id: number
  date: string
  amount: number
  currency: string
  type: "in" | "out"
  description: string | null
  counterparty: string | null
  source_type: string | null
  mapping_confidence: number | null
  mapping_source: string | null
  is_confirmed: boolean
  is_duplicate: boolean
  is_cancel: boolean
  note: string | null
  member_id: number | null
  member_name: string | null
  internal_account_id: number | null
  internal_account_code: string | null
  internal_account_name: string | null
  standard_account_id: number | null
  standard_account_code: string | null
  standard_account_name: string | null
}

interface PaginatedResponse {
  items: Transaction[]
  total: number
  page: number
  per_page: number
  pages: number
}

interface StandardAccount {
  id: number
  code: string
  name: string
  category: string
  subcategory: string
}

interface InternalAccount {
  id: number
  code: string
  name: string
  standard_code: string | null
  standard_name: string | null
  parent_id: number | null
}

interface Member {
  id: number
  name: string
  role: string
}

interface Filters {
  search: string
  dateFrom: string
  dateTo: string
  memberId: string
  standardAccountId: string
  sourceType: string
  unclassified: boolean
}

type EditingCell = {
  txId: number
  field: "internal_account_id" | "standard_account_id"
} | null

type ViewState = "loading" | "empty" | "error" | "success" | "partial"

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SOURCE_LABELS: Record<string, string> = {
  lotte_card: "롯데카드",
  woori_card: "우리카드",
  woori_bank: "우리은행",
  manual: "수동",
}

const SOURCE_BADGE_CLASSES: Record<string, string> = {
  lotte_card: "bg-red-500/15 text-red-400 border-red-500/30",
  woori_card: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  woori_bank: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  manual: "bg-gray-500/15 text-gray-400 border-gray-500/30",
}

const PER_PAGE_OPTIONS = [20, 50, 100, 200]

const INITIAL_FILTERS: Filters = {
  search: "",
  dateFrom: "",
  dateTo: "",
  memberId: "",
  standardAccountId: "",
  sourceType: "",
  unclassified: false,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function confidenceBadge(confidence: number | null) {
  if (confidence == null) return null
  const pct = Math.round(confidence * 100)
  let colorClass = "bg-red-500/15 text-red-400 border-red-500/30"
  if (pct >= 90) colorClass = "bg-green-500/15 text-green-400 border-green-500/30"
  else if (pct >= 70) colorClass = "bg-yellow-500/15 text-yellow-400 border-yellow-500/30"
  return (
    <Badge variant="outline" className={cn("text-[10px] px-1.5 py-0 font-mono", colorClass)}>
      {pct}%
    </Badge>
  )
}

function sourceLabel(sourceType: string | null) {
  if (!sourceType) return null
  const label = SOURCE_LABELS[sourceType] || sourceType
  const classes = SOURCE_BADGE_CLASSES[sourceType] || SOURCE_BADGE_CLASSES.manual
  return (
    <Badge variant="outline" className={cn("text-[10px] px-1.5 py-0", classes)}>
      {label}
    </Badge>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TransactionsPage() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity") ? Number(searchParams.get("entity")) : null

  // Data
  const [data, setData] = useState<PaginatedResponse | null>(null)
  const [standardAccounts, setStandardAccounts] = useState<StandardAccount[]>([])
  const [internalAccounts, setInternalAccounts] = useState<InternalAccount[]>([])
  const [members, setMembers] = useState<Member[]>([])

  // UI state
  const [viewState, setViewState] = useState<ViewState>("loading")
  const [errorMsg, setErrorMsg] = useState("")
  const [page, setPage] = useState(1)
  const [perPage, setPerPage] = useState(50)
  const [filters, setFilters] = useState<Filters>(INITIAL_FILTERS)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [editingCell, setEditingCell] = useState<EditingCell>(null)
  const [detailTx, setDetailTx] = useState<Transaction | null>(null)
  const [detailForm, setDetailForm] = useState<{
    internal_account_id: string
    standard_account_id: string
    note: string
  }>({ internal_account_id: "", standard_account_id: "", note: "" })
  const [saving, setSaving] = useState(false)
  const [bulkConfirming, setBulkConfirming] = useState(false)

  // Debounce search
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [debouncedSearch, setDebouncedSearch] = useState("")

  useEffect(() => {
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current)
    searchTimeoutRef.current = setTimeout(() => {
      setDebouncedSearch(filters.search)
      setPage(1)
    }, 300)
    return () => {
      if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current)
    }
  }, [filters.search])

  // Fetch reference data when entityId changes
  useEffect(() => {
    fetchAPI<StandardAccount[]>("/accounts/standard")
      .then(setStandardAccounts)
      .catch(() => {})

    if (entityId) {
      fetchAPI<InternalAccount[]>(`/accounts/internal?entity_id=${entityId}`)
        .then(setInternalAccounts)
        .catch(() => {})
      fetchAPI<Member[]>(`/accounts/members?entity_id=${entityId}`)
        .then(setMembers)
        .catch(() => {})
    }
  }, [entityId])

  // Fetch transactions
  const fetchTransactions = useCallback(async () => {
    if (!entityId) return
    setViewState("loading")
    setErrorMsg("")

    const params = new URLSearchParams()
    params.set("entity_id", String(entityId))
    params.set("page", String(page))
    params.set("per_page", String(perPage))
    if (debouncedSearch) params.set("search", debouncedSearch)
    if (filters.dateFrom) params.set("date_from", filters.dateFrom)
    if (filters.dateTo) params.set("date_to", filters.dateTo)
    if (filters.memberId) params.set("member_id", filters.memberId)
    if (filters.standardAccountId) params.set("standard_account_id", filters.standardAccountId)
    if (filters.sourceType) params.set("source_type", filters.sourceType)
    if (filters.unclassified) params.set("unclassified", "true")

    try {
      const result = await fetchAPI<PaginatedResponse>(`/transactions?${params.toString()}`)
      setData(result)
      setSelectedIds(new Set())
      setViewState(result.items.length === 0 ? "empty" : "success")
    } catch (err) {
      const msg = err instanceof APIError ? err.message : "데이터를 불러올 수 없습니다."
      setErrorMsg(msg)
      setViewState("error")
    }
  }, [entityId, page, perPage, debouncedSearch, filters.dateFrom, filters.dateTo, filters.memberId, filters.standardAccountId, filters.sourceType, filters.unclassified])

  useEffect(() => {
    fetchTransactions()
  }, [fetchTransactions])

  // Reset page when filters change
  const updateFilter = useCallback(<K extends keyof Filters>(key: K, value: Filters[K]) => {
    setFilters(prev => ({ ...prev, [key]: value }))
    if (key !== "search") setPage(1)
  }, [])

  const clearFilters = useCallback(() => {
    setFilters(INITIAL_FILTERS)
    setPage(1)
  }, [])

  const hasActiveFilters = useMemo(() => {
    return filters.search !== "" || filters.dateFrom !== "" || filters.dateTo !== "" ||
      filters.memberId !== "" || filters.standardAccountId !== "" ||
      filters.sourceType !== "" || filters.unclassified
  }, [filters])

  // Selection
  const allSelected = data ? data.items.length > 0 && data.items.every(tx => selectedIds.has(tx.id)) : false
  const someSelected = selectedIds.size > 0

  const toggleSelectAll = useCallback(() => {
    if (!data) return
    if (allSelected) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(data.items.map(tx => tx.id)))
    }
  }, [data, allSelected])

  const toggleSelect = useCallback((id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  // Bulk confirm
  const handleBulkConfirm = useCallback(async () => {
    if (selectedIds.size === 0) return
    setBulkConfirming(true)
    try {
      const result = await fetchAPI<{ confirmed: number; ids: number[] }>("/transactions/bulk-confirm", {
        method: "POST",
        body: JSON.stringify({ ids: Array.from(selectedIds) }),
      })
      toast.success(`${result.confirmed}건 확정 완료`)
      setSelectedIds(new Set())
      fetchTransactions()
    } catch {
      toast.error("일괄 확정에 실패했습니다.")
    } finally {
      setBulkConfirming(false)
    }
  }, [selectedIds, fetchTransactions])

  // Inline cell edit
  const handleInlineEdit = useCallback(async (txId: number, field: "internal_account_id" | "standard_account_id", value: string) => {
    setEditingCell(null)
    try {
      await fetchAPI(`/transactions/${txId}`, {
        method: "PATCH",
        body: JSON.stringify({ [field]: Number(value) }),
      })
      // Update local state
      setData(prev => {
        if (!prev) return prev
        return {
          ...prev,
          items: prev.items.map(tx => {
            if (tx.id !== txId) return tx
            if (field === "internal_account_id") {
              const account = internalAccounts.find(a => a.id === Number(value))
              return { ...tx, internal_account_id: Number(value), internal_account_name: account?.name ?? null, internal_account_code: account?.code ?? null }
            } else {
              const account = standardAccounts.find(a => a.id === Number(value))
              return { ...tx, standard_account_id: Number(value), standard_account_name: account?.name ?? null, standard_account_code: account?.code ?? null }
            }
          }),
        }
      })
      toast.success("계정이 변경되었습니다.")
    } catch {
      toast.error("계정 변경에 실패했습니다.")
    }
  }, [internalAccounts, standardAccounts])

  // Detail dialog
  const openDetail = useCallback((tx: Transaction) => {
    setDetailTx(tx)
    setDetailForm({
      internal_account_id: tx.internal_account_id ? String(tx.internal_account_id) : "",
      standard_account_id: tx.standard_account_id ? String(tx.standard_account_id) : "",
      note: tx.note || "",
    })
  }, [])

  const saveDetail = useCallback(async () => {
    if (!detailTx) return
    setSaving(true)
    try {
      const body: Record<string, unknown> = {}
      if (detailForm.internal_account_id) body.internal_account_id = Number(detailForm.internal_account_id)
      if (detailForm.standard_account_id) body.standard_account_id = Number(detailForm.standard_account_id)
      if (detailForm.note !== (detailTx.note || "")) body.note = detailForm.note || null

      if (Object.keys(body).length === 0) {
        setDetailTx(null)
        return
      }

      await fetchAPI(`/transactions/${detailTx.id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      })
      toast.success("거래 정보가 저장되었습니다.")
      setDetailTx(null)
      fetchTransactions()
    } catch {
      toast.error("저장에 실패했습니다.")
    } finally {
      setSaving(false)
    }
  }, [detailTx, detailForm, fetchTransactions])

  // CSV download placeholder
  const handleCSVDownload = useCallback(() => {
    // eslint-disable-next-line no-console
    console.log("CSV download - to be implemented in Phase 2")
    toast.info("CSV 다운로드는 Phase 2에서 제공됩니다.")
  }, [])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col h-full">
      {/* Entity Tabs */}
      <EntityTabs />

      <div className="flex-1 flex flex-col p-6 gap-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold">거래내역</h1>
            {data && viewState === "success" && (
              <span className="text-sm text-muted-foreground">{data.total.toLocaleString()}건</span>
            )}
          </div>
          <Button variant="outline" size="sm" onClick={handleCSVDownload}>
            <Download className="h-4 w-4 mr-1.5" />
            CSV 다운로드
          </Button>
        </div>

        {/* Filter Bar */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="내역, 거래처 검색..."
              value={filters.search}
              onChange={e => updateFilter("search", e.target.value)}
              className="pl-8 h-9 w-56 text-sm"
            />
          </div>

          {/* Date from */}
          <Input
            type="date"
            value={filters.dateFrom}
            onChange={e => updateFilter("dateFrom", e.target.value)}
            className="h-9 w-36 text-sm"
            aria-label="시작일"
          />
          <span className="text-muted-foreground text-sm">~</span>
          <Input
            type="date"
            value={filters.dateTo}
            onChange={e => updateFilter("dateTo", e.target.value)}
            className="h-9 w-36 text-sm"
            aria-label="종료일"
          />

          {/* Member */}
          <Select value={filters.memberId} onValueChange={v => updateFilter("memberId", v === "__all__" ? "" : v)}>
            <SelectTrigger className="h-9 w-32 text-sm">
              <SelectValue placeholder="회원" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">전체</SelectItem>
              {members.map(m => (
                <SelectItem key={m.id} value={String(m.id)}>{m.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Standard Account */}
          <Select value={filters.standardAccountId} onValueChange={v => updateFilter("standardAccountId", v === "__all__" ? "" : v)}>
            <SelectTrigger className="h-9 w-36 text-sm">
              <SelectValue placeholder="표준 계정" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">전체</SelectItem>
              {standardAccounts.map(a => (
                <SelectItem key={a.id} value={String(a.id)}>{a.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Source Type */}
          <Select value={filters.sourceType} onValueChange={v => updateFilter("sourceType", v === "__all__" ? "" : v)}>
            <SelectTrigger className="h-9 w-32 text-sm">
              <SelectValue placeholder="출처" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">전체</SelectItem>
              <SelectItem value="lotte_card">롯데카드</SelectItem>
              <SelectItem value="woori_card">우리카드</SelectItem>
              <SelectItem value="woori_bank">우리은행</SelectItem>
            </SelectContent>
          </Select>

          {/* Unclassified */}
          <label className="flex items-center gap-1.5 text-sm cursor-pointer select-none">
            <Checkbox
              checked={filters.unclassified}
              onCheckedChange={v => updateFilter("unclassified", v === true)}
            />
            미분류만
          </label>

          {/* Clear */}
          {hasActiveFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters} className="h-9 text-sm text-muted-foreground">
              <X className="h-3.5 w-3.5 mr-1" />
              초기화
            </Button>
          )}
        </div>

        {/* Main content area */}
        <div className="flex-1 overflow-auto rounded-md border">
          {viewState === "loading" && <TableSkeleton />}
          {viewState === "error" && <ErrorState message={errorMsg} onRetry={fetchTransactions} />}
          {viewState === "empty" && <EmptyState />}
          {(viewState === "success" || viewState === "partial") && data && (
            <>
              {viewState === "partial" && (
                <div className="flex items-center gap-2 px-4 py-2 bg-yellow-500/10 border-b border-yellow-500/30 text-yellow-400 text-sm">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  일부 데이터만 표시됩니다.
                </div>
              )}
              <Table>
                <TableHeader className="sticky top-0 z-10 bg-primary">
                  <TableRow className="hover:bg-primary border-b-0">
                    <TableHead className="w-[40px] text-center">
                      <Checkbox
                        checked={allSelected}
                        onCheckedChange={toggleSelectAll}
                        aria-label="전체 선택"
                      />
                    </TableHead>
                    <TableHead className="w-[100px]">날짜</TableHead>
                    <TableHead className="w-[90px]">출처</TableHead>
                    <TableHead className="w-[80px]">회원</TableHead>
                    <TableHead className="min-w-[160px]">내역</TableHead>
                    <TableHead className="w-[140px]">거래처</TableHead>
                    <TableHead className="w-[120px] text-right">수입</TableHead>
                    <TableHead className="w-[120px] text-right">지출</TableHead>
                    <TableHead className="w-[120px]">내부 계정</TableHead>
                    <TableHead className="w-[120px]">표준 계정</TableHead>
                    <TableHead className="w-[60px] text-center">신뢰</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((tx, idx) => (
                    <TableRow
                      key={tx.id}
                      data-state={selectedIds.has(tx.id) ? "selected" : undefined}
                      className={cn(
                        "h-9 cursor-pointer",
                        idx % 2 === 1 && "bg-secondary/50",
                        tx.is_duplicate && "bg-gray-900/50",
                        tx.is_cancel && "opacity-50",
                      )}
                      onClick={(e) => {
                        const target = e.target as HTMLElement
                        // Don't open detail if clicking on checkbox or account cell with editing
                        if (target.closest("[role=checkbox]") || target.closest("[data-account-cell]")) return
                        openDetail(tx)
                      }}
                    >
                      {/* Checkbox */}
                      <TableCell className="p-2 text-center">
                        <Checkbox
                          checked={selectedIds.has(tx.id)}
                          onCheckedChange={() => toggleSelect(tx.id)}
                          aria-label={`거래 ${tx.id} 선택`}
                        />
                      </TableCell>

                      {/* Date */}
                      <TableCell className="p-2 text-sm whitespace-nowrap">{tx.date}</TableCell>

                      {/* Source */}
                      <TableCell className="p-2">{sourceLabel(tx.source_type)}</TableCell>

                      {/* Member */}
                      <TableCell className="p-2 text-sm truncate max-w-[80px]">
                        {tx.member_name || "\u2014"}
                      </TableCell>

                      {/* Description */}
                      <TableCell className="p-2 text-sm truncate max-w-[300px]" title={tx.description || ""}>
                        <span className={cn(tx.is_cancel && "line-through")}>
                          {tx.description || "\u2014"}
                        </span>
                        {tx.is_cancel && <Badge variant="outline" className="ml-1.5 text-[10px] px-1 py-0 bg-amber-500/15 text-amber-400 border-amber-500/30">취소</Badge>}
                      </TableCell>

                      {/* Counterparty */}
                      <TableCell className="p-2 text-sm truncate max-w-[140px]" title={tx.counterparty || ""}>
                        {tx.counterparty || "\u2014"}
                      </TableCell>

                      {/* Income */}
                      <TableCell className={cn(
                        "p-2 text-right font-mono tabular-nums text-sm",
                        (tx.is_duplicate || tx.is_cancel) && "line-through",
                      )}>
                        {tx.type === "in" ? (
                          <span className={tx.is_cancel ? "text-amber-400" : "text-green-400"}>{formatByEntity(tx.amount, String(entityId ?? 1))}</span>
                        ) : null}
                      </TableCell>

                      {/* Expense */}
                      <TableCell className={cn(
                        "p-2 text-right font-mono tabular-nums text-sm",
                        (tx.is_duplicate || tx.is_cancel) && "line-through",
                      )}>
                        {tx.type === "out" ? (
                          <span className="text-red-400">{formatByEntity(tx.amount, String(entityId ?? 1))}</span>
                        ) : null}
                      </TableCell>

                      {/* Internal Account */}
                      <TableCell
                        className="p-2 cursor-pointer hover:bg-muted/20 transition-colors"
                        onClick={e => { e.stopPropagation(); if (!(editingCell?.txId === tx.id && editingCell?.field === "internal_account_id")) setEditingCell({ txId: tx.id, field: "internal_account_id" }) }}
                      >
                        {editingCell?.txId === tx.id && editingCell?.field === "internal_account_id" ? (
                          <AccountCombobox
                            options={internalAccounts}
                            value={tx.internal_account_id ? String(tx.internal_account_id) : ""}
                            onChange={v => { handleInlineEdit(tx.id, "internal_account_id", v); setEditingCell(null) }}
                            placeholder="선택..."
                            compact
                            autoOpen
                          />
                        ) : (
                          <span className={cn("text-xs truncate block", tx.internal_account_name ? "text-foreground" : "text-muted-foreground")}>
                            {tx.internal_account_name || "-"}
                          </span>
                        )}
                      </TableCell>

                      {/* Standard Account */}
                      <TableCell
                        className="p-2 cursor-pointer hover:bg-muted/20 transition-colors"
                        onClick={e => { e.stopPropagation(); if (!(editingCell?.txId === tx.id && editingCell?.field === "standard_account_id")) setEditingCell({ txId: tx.id, field: "standard_account_id" }) }}
                      >
                        {editingCell?.txId === tx.id && editingCell?.field === "standard_account_id" ? (
                          <AccountCombobox
                            options={standardAccounts}
                            value={tx.standard_account_id ? String(tx.standard_account_id) : ""}
                            onChange={v => { handleInlineEdit(tx.id, "standard_account_id", v); setEditingCell(null) }}
                            placeholder="선택..."
                            compact
                            autoOpen
                          />
                        ) : (
                          <span className={cn("text-xs truncate block", tx.standard_account_name ? "text-foreground" : "text-muted-foreground")}>
                            {tx.standard_account_name || "-"}
                          </span>
                        )}
                      </TableCell>

                      {/* Confidence */}
                      <TableCell className="p-2 text-center">
                        {confidenceBadge(tx.mapping_confidence)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </>
          )}
        </div>

        {/* Pagination */}
        {data && viewState !== "loading" && viewState !== "error" && data.pages > 0 && (
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              {data.page}/{data.pages} 페이지 ({data.total.toLocaleString()}건)
            </span>
            <div className="flex items-center gap-2">
              <Select value={String(perPage)} onValueChange={v => { setPerPage(Number(v)); setPage(1) }}>
                <SelectTrigger className="h-8 w-20 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PER_PAGE_OPTIONS.map(n => (
                    <SelectItem key={n} value={String(n)}>{n}건</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage(p => p - 1)}
                className="h-8"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= (data?.pages || 1)}
                onClick={() => setPage(p => p + 1)}
                className="h-8"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}

        {/* Bulk Actions Bar */}
        {someSelected && (
          <div className="sticky bottom-0 flex items-center gap-3 px-4 py-3 rounded-md border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
            <span className="text-sm font-medium">{selectedIds.size}건 선택됨</span>
            <Button
              size="sm"
              onClick={handleBulkConfirm}
              disabled={bulkConfirming}
            >
              {bulkConfirming ? "처리 중..." : "일괄 확정"}
            </Button>
          </div>
        )}
      </div>

      {/* Detail Dialog */}
      <Dialog open={!!detailTx} onOpenChange={open => { if (!open) setDetailTx(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>거래 상세</DialogTitle>
            <DialogDescription>거래 정보를 확인하고 계정 매핑을 수정할 수 있습니다.</DialogDescription>
          </DialogHeader>
          {detailTx && (
            <div className="space-y-4">
              {/* Read-only info */}
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <span className="text-muted-foreground">날짜</span>
                  <p className="font-medium">{detailTx.date}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">출처</span>
                  <p className="font-medium">{sourceLabel(detailTx.source_type)}</p>
                </div>
                <div className="col-span-2">
                  <span className="text-muted-foreground">내역</span>
                  <p className="font-medium">{detailTx.description || "\u2014"}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">거래처</span>
                  <p className="font-medium">{detailTx.counterparty || "\u2014"}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">금액</span>
                  <p className={cn("font-medium font-mono", detailTx.type === "in" ? "text-green-400" : "text-red-400")}>
                    {detailTx.type === "in" ? "+" : "-"}{formatByEntity(detailTx.amount, String(entityId ?? 1))}
                  </p>
                </div>
              </div>

              {/* Editable fields */}
              <div className="space-y-3 pt-2 border-t">
                <div>
                  <label className="text-sm text-muted-foreground mb-1 block">내부 계정</label>
                  <AccountCombobox
                    options={internalAccounts}
                    value={detailForm.internal_account_id}
                    onChange={v => setDetailForm(p => ({ ...p, internal_account_id: v }))}
                    placeholder="내부 계정 검색..."
                    showCode
                  />
                </div>
                <div>
                  <label className="text-sm text-muted-foreground mb-1 block">표준 계정</label>
                  <AccountCombobox
                    options={standardAccounts}
                    value={detailForm.standard_account_id}
                    onChange={v => setDetailForm(p => ({ ...p, standard_account_id: v }))}
                    placeholder="표준 계정 검색..."
                    showCode
                  />
                </div>
                <div>
                  <label className="text-sm text-muted-foreground mb-1 block">메모</label>
                  <Input
                    value={detailForm.note}
                    onChange={e => setDetailForm(p => ({ ...p, note: e.target.value }))}
                    placeholder="메모를 입력하세요"
                    className="h-9"
                  />
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDetailTx(null)}>취소</Button>
            <Button onClick={saveDetail} disabled={saving}>
              {saving ? "저장 중..." : "저장"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-components for states
// ---------------------------------------------------------------------------

function TableSkeleton() {
  return (
    <div className="w-full">
      {/* Header skeleton */}
      <div className="flex items-center h-12 px-4 border-b bg-primary/50">
        {[40, 100, 90, 80, 200, 140, 120, 120, 120, 120, 60].map((w, i) => (
          <Skeleton key={i} className="h-4 mr-4 shrink-0" style={{ width: w }} />
        ))}
      </div>
      {/* Row skeletons */}
      {Array.from({ length: 10 }).map((_, rowIdx) => (
        <div key={rowIdx} className={cn("flex items-center h-9 px-4 border-b", rowIdx % 2 === 1 && "bg-secondary/50")}>
          {[40, 100, 90, 80, 200, 140, 120, 120, 120, 120, 60].map((w, i) => (
            <Skeleton key={i} className="h-3.5 mr-4 shrink-0 animate-pulse" style={{ width: w * 0.7 }} />
          ))}
        </div>
      ))}
    </div>
  )
}

function EmptyState() {
  const router = useRouter()
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="rounded-full bg-muted p-4 mb-4">
        <Upload className="h-8 w-8 text-muted-foreground" />
      </div>
      <h3 className="text-lg font-medium mb-1">거래 데이터가 없습니다</h3>
      <p className="text-sm text-muted-foreground mb-4">Excel 파일을 업로드해보세요.</p>
      <Button onClick={() => router.push("/upload")}>
        <Upload className="h-4 w-4 mr-1.5" />
        업로드하기
      </Button>
    </div>
  )
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="rounded-full bg-red-500/10 p-4 mb-4">
        <AlertTriangle className="h-8 w-8 text-red-400" />
      </div>
      <h3 className="text-lg font-medium mb-1">데이터를 불러올 수 없습니다</h3>
      <p className="text-sm text-muted-foreground mb-4">{message}</p>
      <Button variant="outline" onClick={onRetry}>
        <RotateCw className="h-4 w-4 mr-1.5" />
        다시 시도
      </Button>
    </div>
  )
}
