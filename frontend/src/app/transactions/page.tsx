"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useGlobalMonth } from "@/hooks/use-global-month"
import { useSearchParams, useRouter } from "next/navigation"
import { fetchAPI, APIError } from "@/lib/api"
import { AccountCombobox } from "@/components/account-combobox"
import { SearchableSelect } from "@/components/searchable-select"
import { formatKRW, formatByEntity } from "@/lib/format"
import { cn } from "@/lib/utils"
import { EntityTabs } from "@/components/entity-tabs"
import { MonthPicker } from "@/components/month-picker"
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
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu"
import {
  Search, Download, ChevronLeft, ChevronRight, X, AlertTriangle, AlertCircle, Upload, RotateCw, RefreshCw, Wand2, MessageSquare, SlidersHorizontal, ChevronDown, CheckCircle2, Receipt,
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
  card_number: string | null
  note: string | null
  member_id: number | null
  member_name: string | null
  internal_account_id: number | null
  internal_account_code: string | null
  internal_account_name: string | null
  internal_account_parent_name: string | null
  standard_account_id: number | null
  standard_account_code: string | null
  standard_account_name: string | null
  has_slack_match: boolean
  expense_id: string | null
  expense_submitted_by: string | null
  expense_title: string | null
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

interface SlackMatchInfo {
  slack_message_id: number
  message_text: string | null
  message_date: string | null
  message_type: string | null
  sender_name: string | null
  matched_at: string | null
  item_index: number | null
  item_description: string | null
  match_type: "auto" | "manual"
  match_confidence: number | null
  ai_reasoning: string | null
  note: string | null
}

interface ExpenseOneMatchInfo {
  match_id: number
  expense_id: string
  expense_type: string
  confidence: number | null
  method: string | null
  is_manual: boolean
  is_confirmed: boolean
  reasoning: string | null
  expense: {
    title: string | null
    description: string | null
    merchant_name: string | null
    amount: number | null
    category: string | null
    account_holder: string | null
    transaction_date: string | null
    approved_at: string | null
    submitter_name: string | null
  }
}

interface Filters {
  search: string
  dateFrom: string
  dateTo: string
  memberId: string
  internalAccountId: string
  standardAccountId: string
  sourceType: string
  txType: "" | "in" | "out"
  mappingSource: string
  recentlyMapped: boolean
  slackMatched: boolean
  unclassified: boolean
  unconfirmed: boolean
  hideCancelled: boolean
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
  ibk_bank: "IBK기업은행",
  shinhan_bank: "신한은행",
  shinhan_card: "신한카드",
  // Codef API pull (출처는 같은 기관이므로 동일 라벨)
  codef_woori_bank: "우리은행",
  codef_ibk_bank: "IBK기업은행",
  codef_shinhan_bank: "신한은행",
  codef_lotte_card: "롯데카드",
  codef_woori_card: "우리카드",
  codef_shinhan_card: "신한카드",
  codef_kb_card: "KB국민카드",
  codef_hyundai_card: "현대카드",
  codef_samsung_card: "삼성카드",
  codef_nh_card: "NH농협카드",
  codef_bc_card: "BC카드",
  codef_hana_card: "하나카드",
  codef_citi_card: "씨티카드",
  codef_jeonbuk_card: "전북카드",
  codef_gwangju_card: "광주카드",
  codef_suhyup_card: "수협카드",
  codef_jeju_card: "제주카드",
  expenseone_card: "ExpenseOne 법카",
  expenseone_deposit: "ExpenseOne 입금",
  manual: "수동",
}

const SOURCE_BADGE_CLASSES: Record<string, string> = {
  // 색상 가이드: 은행/카드는 같은 회사라도 다른 hue 로 구분.
  // 카드사별 브랜드 색을 최대한 반영 (+ 충돌 방지).
  lotte_card: "bg-red-500/15 text-red-400 border-red-500/30",                  // 롯데 = 빨강
  woori_card: "bg-sky-500/15 text-sky-400 border-sky-500/30",                  // 우리카드 = 하늘
  woori_bank: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",               // 우리은행 = 청록
  ibk_bank: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",        // IBK = 초록
  shinhan_bank: "bg-blue-500/15 text-blue-400 border-blue-500/30",             // 신한은행 = 신한 브랜드 파랑
  shinhan_card: "bg-fuchsia-500/15 text-fuchsia-400 border-fuchsia-500/30",    // 신한카드 = 푹시아 (장미보라)
  codef_woori_bank: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  codef_ibk_bank: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  codef_shinhan_bank: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  codef_lotte_card: "bg-red-500/15 text-red-400 border-red-500/30",
  codef_woori_card: "bg-sky-500/15 text-sky-400 border-sky-500/30",
  codef_shinhan_card: "bg-fuchsia-500/15 text-fuchsia-400 border-fuchsia-500/30",
  codef_kb_card: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",      // KB = 노랑
  codef_hyundai_card: "bg-orange-500/15 text-orange-400 border-orange-500/30", // 현대 = 주황
  codef_samsung_card: "bg-violet-500/15 text-violet-400 border-violet-500/30", // 삼성 = 보라 (신한은행 blue 와 충돌 회피)
  codef_nh_card: "bg-lime-500/15 text-lime-400 border-lime-500/30",            // NH = 라임 (IBK 초록과 구분)
  codef_bc_card: "bg-pink-500/15 text-pink-400 border-pink-500/30",            // BC = 핑크
  codef_hana_card: "bg-teal-500/15 text-teal-400 border-teal-500/30",          // 하나 = 청록2
  codef_citi_card: "bg-rose-500/15 text-rose-400 border-rose-500/30",          // 씨티 = 로즈
  codef_jeonbuk_card: "bg-gray-500/15 text-gray-400 border-gray-500/30",
  codef_gwangju_card: "bg-gray-500/15 text-gray-400 border-gray-500/30",
  codef_suhyup_card: "bg-gray-500/15 text-gray-400 border-gray-500/30",
  codef_jeju_card: "bg-gray-500/15 text-gray-400 border-gray-500/30",
  expenseone_card: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  expenseone_deposit: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  manual: "bg-gray-500/15 text-gray-400 border-gray-500/30",
}

const PER_PAGE_OPTIONS = [20, 50, 100, 200]

const INITIAL_FILTERS: Filters = {
  search: "",
  dateFrom: "",
  dateTo: "",
  memberId: "",
  internalAccountId: "",
  standardAccountId: "",
  sourceType: "",
  txType: "",
  mappingSource: "",
  recentlyMapped: false,
  slackMatched: false,
  unclassified: false,
  unconfirmed: false,
  hideCancelled: true,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const MAPPING_SOURCE_CONFIG: Record<string, { label: string; classes: string }> = {
  exact:     { label: "규칙",   classes: "bg-green-500/15 text-green-400 border-green-500/30" },
  similar:   { label: "유사",   classes: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
  keyword:   { label: "키워드", classes: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30" },
  ai:        { label: "AI",    classes: "bg-purple-500/15 text-purple-400 border-purple-500/30" },
  rule:      { label: "규칙",   classes: "bg-green-500/15 text-green-400 border-green-500/30" },
  manual:    { label: "수동",   classes: "bg-gray-500/15 text-gray-400 border-gray-500/30" },
  confirmed: { label: "확정",   classes: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
}

function mappingBadge(mappingSource: string | null, confidence: number | null) {
  if (!mappingSource && confidence == null) return null
  const pct = confidence != null ? Math.round(confidence * 100) : null
  const config = MAPPING_SOURCE_CONFIG[mappingSource || ""] || MAPPING_SOURCE_CONFIG.rule
  return (
    <Badge variant="outline" className={cn("text-[10px] px-1 py-0 font-mono whitespace-nowrap", config.classes)}>
      {config.label}{pct != null ? `${pct}%` : ""}
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

function slackTypeBadge(type: string | null) {
  if (!type) return null
  const typeMap: Record<string, { label: string; className: string }> = {
    card_payment: { label: "법카결제", className: "bg-purple-500/20 text-purple-400 border-purple-500/30" },
    deposit_request: { label: "입금요청", className: "bg-blue-500/20 text-blue-400 border-blue-500/30" },
    tax_invoice: { label: "세금계산서", className: "bg-teal-500/20 text-teal-400 border-teal-500/30" },
  }
  const info = typeMap[type] || { label: type, className: "bg-gray-500/20 text-gray-400 border-gray-500/30" }
  return (
    <Badge variant="outline" className={cn("text-[10px] px-1.5 py-0", info.className)}>
      {info.label}
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
  const [codefSyncing, setCodefSyncing] = useState(false)
  const [codefSyncMsg, setCodefSyncMsg] = useState<string | null>(null)
  const [codefLastSync, setCodefLastSync] = useState<string | null>(null)
  const [codefHasConnections, setCodefHasConnections] = useState(false)
  const [globalMonth, setGlobalMonth] = useGlobalMonth() // ready handled via globalMonth sync effect
  const [filters, setFilters] = useState<Filters>(() => {
    // URL query에서 year/month/filter 읽기
    const urlYear = searchParams.get("year")
    const urlMonth = searchParams.get("month")
    const urlFilter = searchParams.get("filter")
    const urlSourceType = searchParams.get("source_type")
    const urlUnconfirmed = searchParams.get("unconfirmed") === "true"
    // localStorage에서 직접 읽기 (globalMonth는 아직 초기화 전일 수 있음)
    const savedMonth = typeof window !== "undefined" ? localStorage.getItem("financeone-selected-month") : null
    const now = new Date()
    const fallback = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
    const monthStr = urlYear && urlMonth ? `${urlYear}-${String(Number(urlMonth)).padStart(2, "0")}` : (savedMonth || fallback)
    const [y, m] = monthStr.split("-").map(Number)
    const lastDay = new Date(y, m, 0).getDate()
    return {
      ...INITIAL_FILTERS,
      dateFrom: `${y}-${String(m).padStart(2, "0")}-01`,
      dateTo: `${y}-${String(m).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`,
      sourceType: urlSourceType || "",
      unclassified: urlFilter === "unmapped",
      unconfirmed: urlUnconfirmed || urlFilter === "unconfirmed",
    }
  })
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
  const [bulkMapping, setBulkMapping] = useState(false)
  const [bulkMapOpen, setBulkMapOpen] = useState(false)
  const [bulkMapAccountId, setBulkMapAccountId] = useState("")
  const [slackMatch, setSlackMatch] = useState<SlackMatchInfo | null>(null)
  const [slackMatchLoading, setSlackMatchLoading] = useState(false)
  const [eoMatch, setEoMatch] = useState<ExpenseOneMatchInfo | null>(null)
  const [eoMatchLoading, setEoMatchLoading] = useState(false)
  const [tier2Open, setTier2Open] = useState(false)

  // URL query에서 month 왔으면 globalMonth 동기화
  useEffect(() => {
    const urlYear = searchParams.get("year")
    const urlMonth = searchParams.get("month")
    if (urlYear && urlMonth) {
      const m = `${urlYear}-${String(Number(urlMonth)).padStart(2, "0")}`
      if (m !== globalMonth) setGlobalMonth(m)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // globalMonth 변경 시 filters 동기화 (localStorage 복원 포함)
  useEffect(() => {
    const [y, m] = globalMonth.split("-").map(Number)
    const lastDay = new Date(y, m, 0).getDate()
    const newFrom = `${y}-${String(m).padStart(2, "0")}-01`
    const newTo = `${y}-${String(m).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`
    setFilters(f => {
      if (f.dateFrom === newFrom && f.dateTo === newTo) return f
      return { ...f, dateFrom: newFrom, dateTo: newTo }
    })
    setPage(1)
  }, [globalMonth])

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

  // ExpenseOne summary — entity_id=2에서만, 필터 바에 표시
  const [expenseoneSummary, setExpenseoneSummary] = useState<{
    unmapped_count: number
    by_submitter: { name: string; count: number }[]
    drift_count: number
  } | null>(null)
  useEffect(() => {
    if (entityId !== 2) {
      setExpenseoneSummary(null)
      return
    }
    fetchAPI<{
      unmapped_count: number
      by_submitter: { name: string; count: number }[]
      drift_count: number
    }>(`/dashboard/expenseone-summary?entity_id=2`, { cache: "no-store" })
      .then(setExpenseoneSummary)
      .catch(() => setExpenseoneSummary(null))
  }, [entityId])

  // Fetch transactions
  const fetchTransactions = useCallback(async (background = false) => {
    if (!entityId) return
    if (!background) setViewState("loading")
    setErrorMsg("")

    const params = new URLSearchParams()
    params.set("entity_id", String(entityId))
    params.set("page", String(page))
    params.set("per_page", String(perPage))
    if (debouncedSearch) params.set("search", debouncedSearch)
    if (filters.dateFrom) params.set("date_from", filters.dateFrom)
    if (filters.dateTo) params.set("date_to", filters.dateTo)
    if (filters.memberId) params.set("member_id", filters.memberId)
    if (filters.internalAccountId) params.set("internal_account_id", filters.internalAccountId)
    if (filters.standardAccountId) params.set("standard_account_id", filters.standardAccountId)
    if (filters.sourceType) params.set("source_type", filters.sourceType)
    if (filters.txType) params.set("tx_type", filters.txType)
    if (filters.mappingSource) params.set("mapping_source", filters.mappingSource)
    if (filters.recentlyMapped) params.set("recently_mapped", "true")
    if (filters.slackMatched) params.set("slack_matched", "true")
    if (filters.unclassified) params.set("unclassified", "true")
    if (filters.unconfirmed) params.set("unconfirmed", "true")
    if (filters.hideCancelled) params.set("hide_cancelled", "true")

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
  }, [entityId, page, perPage, debouncedSearch, filters.dateFrom, filters.dateTo, filters.memberId, filters.internalAccountId, filters.standardAccountId, filters.sourceType, filters.txType, filters.mappingSource, filters.recentlyMapped, filters.slackMatched, filters.unclassified, filters.unconfirmed, filters.hideCancelled])

  useEffect(() => {
    fetchTransactions()
  }, [fetchTransactions])

  // Reset page when filters change
  const updateFilter = useCallback(<K extends keyof Filters>(key: K, value: Filters[K]) => {
    setFilters(prev => ({ ...prev, [key]: value }))
    if (key !== "search") setPage(1)
    // URL에서 filter 파라미터 제거 (새로고침 시 필터 고착 방지)
    if (key === "unclassified" || key === "unconfirmed") {
      const params = new URLSearchParams(window.location.search)
      if (params.has("filter")) {
        params.delete("filter")
        const newUrl = `${window.location.pathname}${params.toString() ? `?${params}` : ""}`
        window.history.replaceState(null, "", newUrl)
      }
    }
  }, [])

  const clearFilters = useCallback(() => {
    setFilters(INITIAL_FILTERS)
    setPage(1)
  }, [])

  const hasActiveFilters = useMemo(() => {
    return filters.search !== "" || filters.dateFrom !== "" || filters.dateTo !== "" ||
      filters.memberId !== "" || filters.internalAccountId !== "" || filters.standardAccountId !== "" ||
      filters.sourceType !== "" || filters.txType !== "" || filters.mappingSource !== "" || filters.recentlyMapped || filters.slackMatched || filters.unclassified || filters.unconfirmed
  }, [filters])

  // Tier 2 (보조 필터) 활성 개수 — 필터 버튼 배지 표시용
  const activeTier2Count = useMemo(() => {
    let n = 0
    if (filters.internalAccountId) n++
    if (filters.standardAccountId) n++
    if (filters.memberId) n++
    if (filters.sourceType) n++
    if (filters.slackMatched) n++
    if (filters.recentlyMapped) n++
    return n
  }, [filters.internalAccountId, filters.standardAccountId, filters.memberId, filters.sourceType, filters.slackMatched, filters.recentlyMapped])

  // Tier 2에 값이 있으면 자동으로 펼침
  useEffect(() => {
    if (activeTier2Count > 0) setTier2Open(true)
  }, [activeTier2Count])

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
      fetchTransactions(true)
    } catch {
      toast.error("일괄 확정에 실패했습니다.")
    } finally {
      setBulkConfirming(false)
    }
  }, [selectedIds, fetchTransactions])

  // Codef 상태 + 마지막 sync 로드 (entity 바뀔 때마다)
  useEffect(() => {
    if (!entityId || entityId < 0) {
      setCodefHasConnections(false)
      setCodefLastSync(null)
      return
    }
    fetchAPI<{
      configured: boolean
      connections?: Record<string, string>
      last_syncs?: Record<string, string>
    }>(`/integrations/codef/status?entity_id=${entityId}`)
      .then((s) => {
        const conns = Object.keys(s.connections || {})
        setCodefHasConnections(s.configured && conns.length > 0)
        const ts = Object.values(s.last_syncs || {})
        if (ts.length > 0) {
          const newest = ts.reduce((a, b) => (a > b ? a : b))
          setCodefLastSync(newest)
        } else {
          setCodefLastSync(null)
        }
      })
      .catch(() => {
        setCodefHasConnections(false)
        setCodefLastSync(null)
      })
  }, [entityId, codefSyncing])

  // 상대시간 포맷 ('5분 전', '1시간 전')
  const formatRelative = (iso: string | null) => {
    if (!iso) return null
    const d = new Date(iso.replace(" ", "T"))
    if (isNaN(d.getTime())) return null
    const diffSec = Math.floor((Date.now() - d.getTime()) / 1000)
    if (diffSec < 60) return "방금 전"
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}분 전`
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}시간 전`
    return `${Math.floor(diffSec / 86400)}일 전`
  }

  // Codef 동기화 (현재 entity, 선택 월의 1일 ~ 월말 또는 오늘)
  const handleCodefSync = useCallback(async () => {
    if (!entityId || entityId < 0) return
    setCodefSyncing(true)
    setCodefSyncMsg(null)
    try {
      // 1) connections 조회
      const status = await fetchAPI<{
        configured: boolean
        connections: Record<string, string>
      }>(`/integrations/codef/status?entity_id=${entityId}`)
      if (!status.configured) {
        toast.error("Codef 미설정")
        return
      }
      const orgs = Object.keys(status.connections || {})
      if (orgs.length === 0) {
        toast.error("이 법인에 연결된 Codef 계정이 없습니다 (설정 → Codef)")
        return
      }
      // 2) 날짜 범위 결정 — 현재 선택 월
      const sel =
        filters.dateFrom && filters.dateFrom.slice(0, 7) === filters.dateTo.slice(0, 7)
          ? filters.dateFrom.slice(0, 7)
          : globalMonth
      const [y, m] = sel.split("-").map(Number)
      const today = new Date()
      const isCurrentMonth = today.getFullYear() === y && today.getMonth() + 1 === m
      const lastDay = isCurrentMonth ? today.getDate() : new Date(y, m, 0).getDate()
      const startStr = `${y}${String(m).padStart(2, "0")}01`
      const endStr = `${y}${String(m).padStart(2, "0")}${String(lastDay).padStart(2, "0")}`

      // 3) 기관별 sync 병렬 실행
      const results = await Promise.all(
        orgs.map(async (org) => {
          try {
            const isBank = org.endsWith("_bank")
            const path = isBank
              ? "/integrations/codef/sync-bank"
              : "/integrations/codef/sync-card"
            const body: Record<string, unknown> = {
              entity_id: entityId,
              start_date: startStr,
              end_date: endStr,
            }
            if (!isBank) body.card_type = org
            const r = await fetchAPI<{
              synced: number
              duplicates: number
              auto_mapped?: number
              unmapped?: number
              total_fetched: number
            }>(path, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            })
            return { org, ok: true, ...r }
          } catch (err) {
            return {
              org,
              ok: false,
              error: err instanceof Error ? err.message : "실패",
              synced: 0,
              total_fetched: 0,
              duplicates: 0,
            }
          }
        }),
      )

      // 4) 결과 메시지
      const totalSynced = results.reduce((s, r) => s + (r.synced || 0), 0)
      const totalDup = results.reduce((s, r) => s + (r.duplicates || 0), 0)
      const totalAuto = results.reduce(
        (s, r) => s + ((r as { auto_mapped?: number }).auto_mapped ?? 0),
        0,
      )
      const errs = results.filter((r) => !r.ok)
      const summary = `${sel} 동기화: 신규 ${totalSynced}, 자동매핑 ${totalAuto}, 중복 ${totalDup}` +
        (errs.length > 0 ? ` (실패 ${errs.length})` : "")
      setCodefSyncMsg(summary)
      if (errs.length === 0) toast.success(summary)
      else toast.error(`일부 실패: ${errs.map((e) => `${e.org}=${(e as {error?:string}).error}`).join(", ")}`)
      // 5) 거래내역 새로고침
      await fetchTransactions(true)
    } catch (err) {
      const msg = err instanceof Error ? err.message : "동기화 실패"
      setCodefSyncMsg(msg)
      toast.error(msg)
    } finally {
      setCodefSyncing(false)
    }
  }, [entityId, filters.dateFrom, filters.dateTo, globalMonth, fetchTransactions])

  // Bulk cancel
  const [bulkCancelling, setBulkCancelling] = useState(false)
  const handleBulkCancel = useCallback(async () => {
    if (selectedIds.size === 0) return
    setBulkCancelling(true)
    try {
      const result = await fetchAPI<{ cancelled: number; restored: number }>("/transactions/bulk-cancel", {
        method: "POST",
        body: JSON.stringify({ ids: Array.from(selectedIds) }),
      })
      if (result.cancelled > 0) toast.success(`${result.cancelled}건 취소 처리 완료`)
      if (result.restored > 0) toast.success(`${result.restored}건 취소 해제 완료`)
      setSelectedIds(new Set())
      fetchTransactions(true)
    } catch {
      toast.error("취소 처리에 실패했습니다.")
    } finally {
      setBulkCancelling(false)
    }
  }, [selectedIds, fetchTransactions])

  // Create internal account inline
  const handleCreateInternalAccount = useCallback(async (name: string, parentId: number | null) => {
    if (!entityId) return null
    const code = name.toUpperCase().replace(/[^A-Z가-힣0-9]/g, "").slice(0, 20) || `NEW_${Date.now()}`
    const res = await fetchAPI<{ id: number; code: string; name: string; parent_id?: number | null; is_recurring?: boolean }>(
      "/accounts/internal",
      { method: "POST", body: JSON.stringify({ entity_id: entityId, code, name, parent_id: parentId }) },
    )
    const updated = await fetchAPI<InternalAccount[]>(`/accounts/internal?entity_id=${entityId}`, { cache: "no-store" })
    setInternalAccounts(updated)
    return { id: res.id, code: res.code, name: res.name ?? name, parent_id: res.parent_id, is_recurring: res.is_recurring }
  }, [entityId])

  // Bulk map
  const handleBulkMap = useCallback(async () => {
    if (selectedIds.size === 0 || !bulkMapAccountId) return
    setBulkMapping(true)
    try {
      const result = await fetchAPI<{ mapped: number; rules_learned: number }>("/transactions/bulk-map", {
        method: "POST",
        body: JSON.stringify({
          ids: Array.from(selectedIds),
          internal_account_id: Number(bulkMapAccountId),
        }),
      })
      toast.success(`${result.mapped}건 매핑 완료 (${result.rules_learned}개 규칙 학습)`)
      setSelectedIds(new Set())
      setBulkMapOpen(false)
      setBulkMapAccountId("")
      fetchTransactions(true)
    } catch {
      toast.error("일괄 매핑에 실패했습니다")
    } finally {
      setBulkMapping(false)
    }
  }, [selectedIds, bulkMapAccountId, fetchTransactions])

  // Inline cell edit
  const handleInlineEdit = useCallback(async (txId: number, field: "internal_account_id" | "standard_account_id", value: string) => {
    setEditingCell(null)
    if (!value) return // clear selection — do nothing
    const numValue = Number(value)
    if (!numValue || isNaN(numValue)) return
    try {
      await fetchAPI(`/transactions/${txId}`, {
        method: "PATCH",
        body: JSON.stringify({ [field]: numValue }),
      })
      // Update local state
      setData(prev => {
        if (!prev) return prev
        return {
          ...prev,
          items: prev.items.map(tx => {
            if (tx.id !== txId) return tx
            if (field === "internal_account_id") {
              const account = internalAccounts.find(a => a.id === numValue)
              const parent = account?.parent_id ? internalAccounts.find(a => a.id === account.parent_id) : null
              return { ...tx, internal_account_id: numValue, internal_account_name: account?.name ?? null, internal_account_code: account?.code ?? null, internal_account_parent_name: parent?.name ?? null }
            } else {
              const account = standardAccounts.find(a => a.id === numValue)
              return { ...tx, standard_account_id: numValue, standard_account_name: account?.name ?? null, standard_account_code: account?.code ?? null }
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
    // Fetch slack match info
    setSlackMatch(null)
    setSlackMatchLoading(true)
    fetchAPI<SlackMatchInfo | null>(`/transactions/${tx.id}/slack-match`)
      .then(data => setSlackMatch(data))
      .catch(() => setSlackMatch(null))
      .finally(() => setSlackMatchLoading(false))
    // Fetch ExpenseOne match info
    setEoMatch(null)
    setEoMatchLoading(true)
    fetchAPI<ExpenseOneMatchInfo | null>(`/transactions/${tx.id}/expenseone-match`)
      .then(data => setEoMatch(data))
      .catch(() => setEoMatch(null))
      .finally(() => setEoMatchLoading(false))
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
      fetchTransactions(true)
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

  // 자동 매핑
  const [autoMapping, setAutoMapping] = useState(false)
  const handleAutoMap = useCallback(async (onlyUnmapped: boolean = false) => {
    if (!entityId) return
    setAutoMapping(true)
    try {
      const [y, m] = (filters.dateFrom && filters.dateTo && filters.dateFrom.slice(0, 7) === filters.dateTo.slice(0, 7)
        ? filters.dateFrom.slice(0, 7) : globalMonth).split("-").map(Number)
      const result = await fetchAPI<{ new_mapped: number; updated: number; total_targets: number }>(
        `/transactions/auto-map?entity_id=${entityId}&year=${y}&month=${m}&only_unmapped=${onlyUnmapped}`,
        { method: "POST" },
      )
      const total = (result.new_mapped || 0) + (result.updated || 0)
      if (total > 0) {
        const parts = []
        if (result.new_mapped) parts.push(`신규 ${result.new_mapped}건`)
        if (result.updated) parts.push(`변경 ${result.updated}건`)
        toast.success(`자동 매핑: ${parts.join(", ")} (대상 ${result.total_targets}건)`)
        fetchTransactions(true)
      } else {
        toast.info(`변경할 거래가 없습니다.`)
      }
    } catch {
      toast.error("자동 매핑에 실패했습니다")
    } finally {
      setAutoMapping(false)
    }
  }, [entityId, fetchTransactions])

  // 자동 매핑 일괄 확정
  // 브랜드/사업부별 색상 점 — 하위 계정에 항상 표시
  const BRAND_COLORS: Record<string, string> = {
    "ODD": "bg-red-500",
    "한아원리테일": "bg-yellow-500",
    "마트약국": "bg-sky-400",
    "YUNE": "bg-pink-500",
    "3PL": "bg-green-500",
  }

  const autoMappedUnconfirmed = useMemo(() => {
    if (!data) return []
    return data.items.filter(tx =>
      tx.internal_account_id && !tx.is_confirmed &&
      tx.mapping_source && ["exact", "similar", "keyword", "ai", "rule", "manual"].includes(tx.mapping_source)
    )
  }, [data])

  const handleBulkConfirmAutoMapped = useCallback(async () => {
    if (!entityId) return
    setBulkConfirming(true)
    try {
      const selectedYM = filters.dateFrom && filters.dateTo && filters.dateFrom.slice(0, 7) === filters.dateTo.slice(0, 7)
        ? filters.dateFrom.slice(0, 7) : globalMonth
      const [y, m] = selectedYM.split("-").map(Number)
      const result = await fetchAPI<{ confirmed: number }>(`/transactions/bulk-confirm-month?entity_id=${entityId}&year=${y}&month=${m}`, {
        method: "POST",
      })
      toast.success(`${selectedYM.replace("-", "년 ")}월 — ${result.confirmed}건 일괄 확정 완료`)
      fetchTransactions(true)
    } catch {
      toast.error("일괄 확정에 실패했습니다")
    } finally {
      setBulkConfirming(false)
    }
  }, [entityId, filters.dateFrom, filters.dateTo, globalMonth, fetchTransactions])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col h-full">
      {/* Entity Tabs */}
      <EntityTabs />

      <div className="flex-1 flex flex-col p-6 gap-4 min-h-0">
        {/* Header */}
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">거래내역</h1>
          {data && viewState === "success" && (
            <span className="text-sm text-muted-foreground">{data.total.toLocaleString()}건</span>
          )}
        </div>

        {/* Filter Bar — Tier 1 (주 필터) */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Month picker */}
          <MonthPicker
            months={(() => {
              const ms: string[] = []
              for (let i = 18; i >= 0; i--) {
                const d = new Date()
                d.setMonth(d.getMonth() - i)
                ms.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`)
              }
              return ms
            })()}
            selected={
              filters.dateFrom && filters.dateTo && filters.dateFrom.slice(0, 7) === filters.dateTo.slice(0, 7)
                ? filters.dateFrom.slice(0, 7)
                : globalMonth
            }
            onSelect={(m) => {
              const [y, mo] = m.split("-").map(Number)
              const lastDay = new Date(y, mo, 0).getDate()
              setFilters(f => ({
                ...f,
                dateFrom: `${y}-${String(mo).padStart(2, "0")}-01`,
                dateTo: `${y}-${String(mo).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`,
              }))
              setGlobalMonth(m)
              setPage(1)
            }}
            allowFuture
          />

          {/* Codef 동기화 — 현재 entity 연결 기관에 대해 선택월 sync */}
          {codefHasConnections && (
            <div className="inline-flex items-center gap-2">
              <button
                onClick={handleCodefSync}
                disabled={codefSyncing}
                className={cn(
                  "h-9 px-3 rounded-full border text-xs font-medium transition-colors inline-flex items-center gap-1.5",
                  codefSyncing
                    ? "border-cyan-500/30 bg-cyan-500/10 text-cyan-400"
                    : "border-white/10 text-muted-foreground hover:bg-white/[0.04] hover:text-cyan-400",
                )}
                title={codefLastSync ? `마지막: ${new Date(codefLastSync.replace(" ","T")).toLocaleString("ko-KR")}` : "선택한 월의 Codef 거래를 가져옵니다"}
              >
                {codefSyncing ? (
                  <RefreshCw className="h-3 w-3 animate-spin" />
                ) : (
                  <Download className="h-3 w-3" />
                )}
                Codef 동기화
              </button>
              {codefLastSync && !codefSyncing && (
                <span className="text-[11px] text-muted-foreground/70">
                  마지막: {formatRelative(codefLastSync)}
                </span>
              )}
            </div>
          )}

          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="내역, 거래처, 금액 검색..."
              value={filters.search}
              onChange={e => updateFilter("search", e.target.value)}
              className="pl-9 h-9 w-56 text-sm rounded-full bg-white/[0.03] border-white/10"
            />
          </div>

          {/* Type filter (전체/수입/지출) — pill tab group */}
          <div className="flex items-center rounded-full border border-white/10 p-0.5">
            {[
              { value: "" as const, label: "전체" },
              { value: "in" as const, label: "수입" },
              { value: "out" as const, label: "지출" },
            ].map(opt => (
              <button
                key={opt.value}
                onClick={() => updateFilter("txType", opt.value)}
                className={cn(
                  "px-3 py-1 text-xs font-medium rounded-full transition-colors",
                  filters.txType === opt.value
                    ? opt.value === "in" ? "bg-green-500/20 text-green-400"
                      : opt.value === "out" ? "bg-red-500/20 text-red-400"
                      : "bg-white/[0.08] text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {/* Unclassified toggle (pill) */}
          <button
            onClick={() => updateFilter("unclassified", !filters.unclassified)}
            className={cn(
              "h-8 px-3 rounded-full border text-xs font-medium transition-colors",
              filters.unclassified
                ? "bg-amber-500/15 text-amber-400 border-amber-500/30"
                : "border-white/10 text-muted-foreground hover:bg-white/[0.04]",
            )}
          >
            미분류
          </button>

          {/* Unconfirmed toggle (pill) */}
          <button
            onClick={() => updateFilter("unconfirmed", !filters.unconfirmed)}
            className={cn(
              "h-8 px-3 rounded-full border text-xs font-medium transition-colors",
              filters.unconfirmed
                ? "bg-blue-500/15 text-blue-400 border-blue-500/30"
                : "border-white/10 text-muted-foreground hover:bg-white/[0.04]",
            )}
          >
            미확정
          </button>

          {/* Hide cancelled toggle — 기본 ON. 취소된 거래 + 페어된 원거래 숨김 */}
          <button
            onClick={() => updateFilter("hideCancelled", !filters.hideCancelled)}
            className={cn(
              "h-8 px-3 rounded-full border text-xs font-medium transition-colors",
              filters.hideCancelled
                ? "border-white/10 text-muted-foreground hover:bg-white/[0.04]"
                : "bg-rose-500/15 text-rose-300 border-rose-500/30",
            )}
            title={filters.hideCancelled
              ? "취소된 거래 + 같은 날·금액의 원승인 건을 숨기는 중 (클릭 시 모두 표시)"
              : "취소 거래 모두 표시 중 (클릭 시 숨김)"}
          >
            {filters.hideCancelled ? "취소 숨김" : "취소 포함"}
          </button>

          {/* Filter expand button (opens Tier 2) */}
          <button
            onClick={() => setTier2Open(v => !v)}
            className={cn(
              "h-8 px-3 rounded-full border text-xs font-medium transition-colors inline-flex items-center gap-1.5",
              tier2Open
                ? "bg-white/[0.08] border-white/20 text-foreground"
                : "border-white/10 text-muted-foreground hover:bg-white/[0.04]",
            )}
          >
            <SlidersHorizontal className="h-3.5 w-3.5" />
            필터
            {activeTier2Count > 0 && (
              <span className="inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full bg-sky-500 text-[9px] font-bold text-background">
                {activeTier2Count}
              </span>
            )}
          </button>

          {/* Clear (active filters indicator) */}
          {hasActiveFilters && (
            <button
              onClick={clearFilters}
              className="h-8 px-3 rounded-full text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
            >
              <X className="h-3 w-3" />
              초기화
            </button>
          )}

          {/* Actions dropdown — 오른쪽 정렬 */}
          <div className="ml-auto">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="h-8 px-3.5 rounded-full border border-white/10 text-xs font-medium text-foreground hover:bg-white/[0.05] inline-flex items-center gap-1.5">
                  작업
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56 rounded-2xl">
                <DropdownMenuItem onClick={() => handleAutoMap(true)} disabled={autoMapping} className="rounded-xl">
                  <Wand2 className="h-4 w-4 mr-2" />
                  {autoMapping ? "매핑 중..." : "자동 매핑 (비어있는 것만)"}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => handleAutoMap(false)} disabled={autoMapping} className="rounded-xl">
                  <Wand2 className="h-4 w-4 mr-2" />
                  {autoMapping ? "매핑 중..." : "자동 매핑 (전체 재매핑)"}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={handleBulkConfirmAutoMapped}
                  disabled={bulkConfirming || autoMappedUnconfirmed.length === 0}
                  className="rounded-xl text-emerald-400 focus:text-emerald-400"
                >
                  <CheckCircle2 className="h-4 w-4 mr-2" />
                  {bulkConfirming ? "확정 중..." : "이 달 일괄 확정"}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={handleCSVDownload} className="rounded-xl">
                  <Download className="h-4 w-4 mr-2" />
                  CSV 다운로드
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {/* Filter Bar — Tier 2 (보조 필터, 접기/펼치기) */}
        {tier2Open && (
          <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-white/[0.06]">
            {/* Internal Account */}
            <SearchableSelect
              value={filters.internalAccountId}
              onChange={v => updateFilter("internalAccountId", v)}
              options={internalAccounts.filter(a => a.code !== "INC" && a.code !== "EXP").map(a => ({ value: String(a.id), label: a.name }))}
              placeholder="내부계정"
              searchPlaceholder="내부계정 검색..."
              className="w-36 rounded-full"
            />

            {/* Standard Account */}
            <SearchableSelect
              value={filters.standardAccountId}
              onChange={v => updateFilter("standardAccountId", v)}
              options={standardAccounts.map(a => ({ value: String(a.id), label: a.name }))}
              placeholder="표준 계정"
              searchPlaceholder="표준 계정 검색..."
              className="w-36 rounded-full"
            />

            {/* Member */}
            <SearchableSelect
              value={filters.memberId}
              onChange={v => updateFilter("memberId", v)}
              options={members.map(m => ({ value: String(m.id), label: m.name }))}
              placeholder="회원"
              searchPlaceholder="회원 검색..."
              className="w-32 rounded-full"
            />

            {/* Source Type */}
            <SearchableSelect
              value={filters.sourceType}
              onChange={v => updateFilter("sourceType", v)}
              options={[
                { value: "lotte_card", label: "롯데카드" },
                { value: "woori_card", label: "우리카드" },
                { value: "woori_bank", label: "우리은행" },
                { value: "shinhan_bank", label: "신한은행" },
                { value: "shinhan_card", label: "신한카드" },
                { value: "expenseone_card", label: "ExpenseOne 법카" },
                { value: "expenseone_deposit", label: "ExpenseOne 입금" },
              ]}
              placeholder="출처"
              searchPlaceholder="출처 검색..."
              className="w-32 rounded-full"
            />

            {/* Slack matched toggle */}
            <button
              onClick={() => updateFilter("slackMatched", !filters.slackMatched)}
              className={cn(
                "h-8 px-3 rounded-full border text-xs font-medium transition-colors inline-flex items-center gap-1.5",
                filters.slackMatched
                  ? "bg-purple-500/15 text-purple-400 border-purple-500/30"
                  : "border-white/10 text-muted-foreground hover:bg-white/[0.04]",
              )}
            >
              <MessageSquare className="h-3 w-3" />
              슬랙
            </button>

            {/* Recently mapped toggle */}
            <button
              onClick={() => updateFilter("recentlyMapped", !filters.recentlyMapped)}
              className={cn(
                "h-8 px-3 rounded-full border text-xs font-medium transition-colors",
                filters.recentlyMapped
                  ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                  : "border-white/10 text-muted-foreground hover:bg-white/[0.04]",
              )}
            >
              자동 매핑
            </button>
          </div>
        )}

        {/* 브랜드/사업부 범례 */}
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>내부계정 구분:</span>
          {Object.entries(BRAND_COLORS).map(([name, color]) => (
            <span key={name} className="flex items-center gap-1">
              <span className={cn("inline-block w-2 h-2 rounded-full", color)} />
              {name}
            </span>
          ))}
        </div>

        {/* ExpenseOne 요약 바 — source_type이 expenseone_* 일 때만 */}
        {expenseoneSummary
          && filters.sourceType.startsWith("expenseone")
          && expenseoneSummary.unmapped_count > 0 && (
          <div className="flex flex-col sm:flex-row items-start sm:items-center gap-2 sm:gap-4 px-3 py-2 rounded-md border border-[hsl(var(--warning))]/30 bg-[hsl(var(--warning))]/5 text-sm">
            <div className="flex items-center gap-2 text-[hsl(var(--warning))]">
              <AlertCircle className="h-4 w-4" />
              <span>미매칭 <span className="font-mono tabular-nums font-semibold">{expenseoneSummary.unmapped_count}</span>건</span>
            </div>
            {expenseoneSummary.by_submitter.length > 0 && (
              <div className="text-muted-foreground text-xs sm:text-sm">
                <span className="hidden sm:inline">제출자별: </span>
                <span className="font-mono tabular-nums">
                  {expenseoneSummary.by_submitter
                    .map((s) => `${s.name} ${s.count}`)
                    .join(" · ")}
                </span>
              </div>
            )}
            {expenseoneSummary.drift_count > 0 && (
              <Badge
                variant="outline"
                className="ml-auto text-xs font-mono bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-[hsl(var(--warning))]/30"
              >
                전월 승인 {expenseoneSummary.drift_count}건
              </Badge>
            )}
          </div>
        )}

        {/* Main content area */}
        <div className="flex-1 overflow-y-auto rounded-md border">
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
              <table className="w-full table-fixed caption-bottom text-sm">
                <thead className="sticky top-0 z-10 bg-primary [&_tr]:border-b">
                  <TableRow className="hover:bg-primary border-b-0 whitespace-nowrap">
                    <TableHead className="w-[36px] text-center">
                      <Checkbox
                        checked={allSelected}
                        onCheckedChange={toggleSelectAll}
                        aria-label="전체 선택"
                        className="border-white/40 data-[state=checked]:border-primary"
                      />
                    </TableHead>
                    <TableHead className="w-[88px]">날짜</TableHead>
                    <TableHead className="w-[64px]">출처</TableHead>
                    <TableHead className="w-[64px]">회원</TableHead>
                    <TableHead className="w-[72px]">제출자</TableHead>
                    <TableHead className="w-[18%]">내역</TableHead>
                    <TableHead className="w-[14%]">거래처</TableHead>
                    <TableHead className="w-[90px] text-right">수입</TableHead>
                    <TableHead className="w-[90px] text-right">지출</TableHead>
                    <TableHead className="w-[80px]">내부 계정</TableHead>
                    <TableHead className="w-[80px]">표준 계정</TableHead>
                    <TableHead className="w-[80px] text-center">신뢰</TableHead>
                  </TableRow>
                </thead>
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
                        !tx.is_confirmed && tx.internal_account_id && "border-l-2 border-l-amber-400",
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
                          className="border-white/40 data-[state=checked]:border-primary"
                        />
                      </TableCell>

                      {/* Date */}
                      <TableCell className="p-2 text-sm whitespace-nowrap">{tx.date}</TableCell>

                      {/* Source + Slack match indicator */}
                      <TableCell className="p-2 whitespace-nowrap">
                        <span className="inline-flex items-center gap-1.5">
                          {sourceLabel(tx.source_type)}
                          {tx.has_slack_match && (
                            <span className="inline-block w-2 h-2 rounded-full bg-indigo-400" title="Slack 매칭됨" />
                          )}
                        </span>
                      </TableCell>

                      {/* Member */}
                      <TableCell className="p-2 text-sm truncate max-w-[80px]">
                        {tx.member_name || (tx.card_number ? tx.card_number.slice(-4) : "\u2014")}
                      </TableCell>

                      {/* Submitter (ExpenseOne) */}
                      <TableCell
                        className="p-2 text-sm overflow-hidden text-muted-foreground"
                        title={tx.expense_submitted_by || ""}
                      >
                        <span className="block truncate">{tx.expense_submitted_by || "\u2014"}</span>
                      </TableCell>

                      {/* Description */}
                      <TableCell className="p-2 text-sm overflow-hidden" title={tx.description || ""}>
                        <span className={cn("block truncate", tx.is_cancel && "line-through")}>
                          {tx.description || "\u2014"}
                          {tx.is_cancel && <Badge variant="outline" className="ml-1.5 text-[10px] px-1 py-0 bg-amber-500/15 text-amber-400 border-amber-500/30">취소</Badge>}
                        </span>
                      </TableCell>

                      {/* Counterparty */}
                      <TableCell className="p-2 text-sm overflow-hidden" title={tx.counterparty || ""}>
                        <span className="block truncate">{tx.counterparty || "\u2014"}</span>
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
                        data-account-cell
                        className="p-2 overflow-hidden cursor-pointer hover:bg-muted/20 transition-colors"
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
                            onCreateAccount={handleCreateInternalAccount}
                          />
                        ) : (
                          <span className={cn("text-xs truncate flex items-center gap-1", tx.internal_account_name ? "text-foreground" : "text-muted-foreground")}
                            title={tx.internal_account_parent_name && BRAND_COLORS[tx.internal_account_parent_name]
                              ? `${tx.internal_account_parent_name} > ${tx.internal_account_name}` : tx.internal_account_name ?? ""}
                          >
                            {tx.internal_account_name ? (
                              <>
                                {tx.internal_account_parent_name && BRAND_COLORS[tx.internal_account_parent_name] && (
                                  <span className={cn("inline-block w-2 h-2 rounded-full shrink-0", BRAND_COLORS[tx.internal_account_parent_name])} />
                                )}
                                <span className="truncate">{tx.internal_account_name}</span>
                              </>
                            ) : "-"}
                          </span>
                        )}
                      </TableCell>

                      {/* Standard Account */}
                      <TableCell
                        data-account-cell
                        className="p-2 overflow-hidden cursor-pointer hover:bg-muted/20 transition-colors"
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
                        {mappingBadge(tx.mapping_source, tx.mapping_confidence)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </table>
              {/* 페이지가 가득 찼을 때만 bulk bar 공간 확보 (미분류처럼 rows 적으면 생략) */}
              {someSelected && (data?.items?.length ?? 0) >= 20 && (
                <div aria-hidden className="h-20 pointer-events-none" />
              )}
            </>
          )}

        </div>

        {/* Pagination */}
        {data && viewState !== "loading" && viewState !== "error" && data.pages > 1 && (
          <div className="flex-shrink-0 flex items-center justify-between text-sm py-3">
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
              {(() => {
                const totalPages = data?.pages || 1
                const pages: (number | "...")[] = []
                if (totalPages <= 7) {
                  for (let i = 1; i <= totalPages; i++) pages.push(i)
                } else {
                  pages.push(1)
                  if (page > 3) pages.push("...")
                  for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) pages.push(i)
                  if (page < totalPages - 2) pages.push("...")
                  pages.push(totalPages)
                }
                return pages.map((p, i) =>
                  p === "..." ? (
                    <span key={`dot-${i}`} className="text-xs text-muted-foreground px-1">...</span>
                  ) : (
                    <button
                      key={p}
                      onClick={() => setPage(p)}
                      className={cn(
                        "h-8 w-8 rounded-full text-xs font-medium transition-colors",
                        p === page
                          ? "bg-[#F59E0B] text-black font-bold"
                          : "border border-border text-muted-foreground hover:text-foreground hover:border-foreground/30"
                      )}
                    >
                      {p}
                    </button>
                  )
                )
              })()}
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

      </div>

      {/* Bulk Actions Bar — fixed bottom outside overflow container */}
      {someSelected && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-5 py-3 rounded-xl border border-border bg-background/95 backdrop-blur-lg shadow-2xl supports-[backdrop-filter]:bg-background/80 animate-in slide-in-from-bottom-4 fade-in-0 duration-200">
          <div className="flex items-center gap-2 pr-3 border-r border-border">
            <div className="flex items-center justify-center h-6 min-w-[24px] rounded-md bg-primary text-primary-foreground text-xs font-bold px-1.5">
              {selectedIds.size}
            </div>
            <span className="text-sm font-medium whitespace-nowrap">건 선택됨</span>
          </div>
          {bulkMapOpen ? (
            <div className="flex items-center gap-2">
              <div className="w-[220px]">
                <AccountCombobox
                  options={internalAccounts}
                  value={bulkMapAccountId}
                  onChange={setBulkMapAccountId}
                  placeholder="내부계정 선택..."
                  dropUp
                  onCreateAccount={handleCreateInternalAccount}
                />
              </div>
              <Button size="sm" onClick={handleBulkMap} disabled={bulkMapping || !bulkMapAccountId}>
                {bulkMapping ? "매핑 중..." : "적용"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => { setBulkMapOpen(false); setBulkMapAccountId("") }}>
                취소
              </Button>
            </div>
          ) : (
            <>
              <Button size="sm" variant="outline" onClick={() => setBulkMapOpen(true)}>
                일괄 매핑
              </Button>
              <Button
                size="sm"
                onClick={handleBulkConfirm}
                disabled={bulkConfirming}
              >
                {bulkConfirming ? "처리 중..." : "일괄 확정"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="text-amber-400 border-amber-500/30 hover:bg-amber-500/10"
                onClick={handleBulkCancel}
                disabled={bulkCancelling}
              >
                {bulkCancelling ? "처리 중..." : "취소 처리"}
              </Button>
            </>
          )}
          <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={() => setSelectedIds(new Set())}>
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}

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
                {detailTx.member_name && (
                  <div>
                    <span className="text-muted-foreground">회원</span>
                    <p className="font-medium">{detailTx.member_name}</p>
                  </div>
                )}
                {detailTx.card_number && (
                  <div>
                    <span className="text-muted-foreground">카드번호</span>
                    <p className="font-medium font-mono text-xs">{detailTx.card_number}</p>
                  </div>
                )}
                {detailTx.is_cancel && (
                  <div className="col-span-2">
                    <Badge variant="outline" className="bg-amber-500/15 text-amber-400 border-amber-500/30">취소 건</Badge>
                  </div>
                )}
              </div>

              {/* Slack match info */}
              {!slackMatchLoading && slackMatch && (
                <div className="rounded-lg border border-indigo-500/20 bg-indigo-500/5 p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <MessageSquare className="h-3.5 w-3.5 text-indigo-400" />
                    <span className="text-xs font-medium text-indigo-400">Slack 매칭</span>
                    {slackTypeBadge(slackMatch.message_type)}
                    <Badge variant="outline" className={cn(
                      "text-[10px] px-1.5 py-0 ml-auto",
                      slackMatch.match_type === "auto"
                        ? "bg-green-500/15 text-green-400 border-green-500/30"
                        : "bg-orange-500/15 text-orange-400 border-orange-500/30"
                    )}>
                      {slackMatch.match_type === "auto" ? "자동" : "수동"}
                    </Badge>
                  </div>
                  {slackMatch.message_text && (
                    <p className="text-xs text-muted-foreground line-clamp-2">{slackMatch.message_text}</p>
                  )}
                  <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                    {slackMatch.message_date && <span>{slackMatch.message_date}</span>}
                    {slackMatch.sender_name && <span>{slackMatch.sender_name}</span>}
                    {slackMatch.item_description && (
                      <span className="truncate max-w-[150px]" title={slackMatch.item_description}>
                        {slackMatch.item_description}
                      </span>
                    )}
                    {slackMatch.match_confidence != null && (
                      <span className="ml-auto font-mono">{Math.round(slackMatch.match_confidence * 100)}%</span>
                    )}
                  </div>
                </div>
              )}

              {/* ExpenseOne match info */}
              {!eoMatchLoading && eoMatch && (
                <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <Receipt className="h-3.5 w-3.5 text-amber-400" />
                    <span className="text-xs font-medium text-amber-400">ExpenseOne 매칭</span>
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0 bg-amber-500/15 text-amber-400 border-amber-500/30">
                      {eoMatch.expense_type === "CORPORATE_CARD" ? "법카" : "입금요청"}
                    </Badge>
                    <Badge variant="outline" className={cn(
                      "text-[10px] px-1.5 py-0 ml-auto",
                      eoMatch.is_manual
                        ? "bg-orange-500/15 text-orange-400 border-orange-500/30"
                        : "bg-green-500/15 text-green-400 border-green-500/30"
                    )}>
                      {eoMatch.is_manual ? "수동" : "자동"}
                    </Badge>
                  </div>
                  {eoMatch.expense.title && (
                    <p className="text-sm text-foreground">
                      {eoMatch.expense.title}
                    </p>
                  )}
                  {eoMatch.expense.description && eoMatch.expense.description !== eoMatch.expense.title && (
                    <p className="text-xs text-muted-foreground line-clamp-2">
                      {eoMatch.expense.description}
                    </p>
                  )}
                  <div className="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                    {eoMatch.expense.submitter_name && (
                      <div>
                        <span className="text-muted-foreground/70">제출자</span>
                        <p className="text-foreground">{eoMatch.expense.submitter_name}</p>
                      </div>
                    )}
                    {eoMatch.expense.category && (
                      <div>
                        <span className="text-muted-foreground/70">카테고리</span>
                        <p className="text-foreground">{eoMatch.expense.category}</p>
                      </div>
                    )}
                    {eoMatch.expense.merchant_name && (
                      <div>
                        <span className="text-muted-foreground/70">가맹점</span>
                        <p className="text-foreground">{eoMatch.expense.merchant_name}</p>
                      </div>
                    )}
                    {eoMatch.expense.account_holder && (
                      <div>
                        <span className="text-muted-foreground/70">예금주</span>
                        <p className="text-foreground">{eoMatch.expense.account_holder}</p>
                      </div>
                    )}
                  </div>
                  {eoMatch.confidence != null && (
                    <div className="flex items-center justify-between text-[10px] text-muted-foreground/70 pt-1 border-t border-amber-500/10">
                      <span className="font-mono">{eoMatch.method}</span>
                      <span className="font-mono">신뢰도 {Math.round(eoMatch.confidence * 100)}%</span>
                    </div>
                  )}
                </div>
              )}
              {!eoMatchLoading && !eoMatch && detailTx.source_type && (detailTx.source_type.includes("card") || detailTx.source_type.includes("bank")) && (
                <div className="rounded-lg border border-border bg-secondary/20 p-3 text-xs text-muted-foreground">
                  매칭된 ExpenseOne 항목 없음. 매칭 메뉴에서 수동 연결 가능 (예정).
                </div>
              )}

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
