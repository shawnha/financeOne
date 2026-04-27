"use client"

import { Suspense, useCallback, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { EntityTabs } from "@/components/entity-tabs"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { fetchAPI } from "@/lib/api"
import { cn } from "@/lib/utils"
import {
  FileSpreadsheet,
  Plus,
  RefreshCw,
  Search,
  X,
  Wand2,
  Trash2,
  XCircle,
  Upload,
  AlertTriangle,
  Cloud,
  Building2,
} from "lucide-react"
import { toast } from "sonner"

interface Invoice {
  id: number
  entity_id: number
  direction: "sales" | "purchase"
  counterparty: string
  counterparty_biz_no: string | null
  issue_date: string
  due_date: string | null
  document_no: string | null
  description: string | null
  amount: number
  vat: number
  total: number
  currency: string
  status: "open" | "partial" | "paid" | "cancelled"
  paid_amount: number
  outstanding: number
  internal_account_id: number | null
  standard_account_id: number | null
  note: string | null
}

interface AutoMatchCandidate {
  invoice_id: number
  transaction_id: number
  amount: number
  score: number
  reason: string
  invoice_counterparty: string
  transaction_counterparty: string
  invoice_outstanding: number
  transaction_amount: number
  tx_date: string
  due_date: string
}

interface TxLite {
  id: number
  date: string
  type: string
  amount: number
  counterparty: string | null
  description: string | null
}

const STATUS_LABELS: Record<string, string> = {
  open: "미결제",
  partial: "부분결제",
  paid: "완납",
  cancelled: "취소",
}

const STATUS_BADGE: Record<string, string> = {
  open: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  partial: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  paid: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  cancelled: "bg-gray-500/15 text-gray-400 border-gray-500/30",
}

function fmtKRW(n: number): string {
  return new Intl.NumberFormat("ko-KR").format(Math.round(n))
}

function todayISO(): string {
  const d = new Date()
  return d.toISOString().slice(0, 10)
}


// ── Page ───────────────────────────────────────────────────────────


export default function InvoicesPage() {
  return (
    <div className="space-y-6">
      <Suspense fallback={<Skeleton className="h-10 w-full border-b" />}>
        <EntityTabs />
      </Suspense>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <InvoicesInner />
      </Suspense>
    </div>
  )
}


function InvoicesInner() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity") ? Number(searchParams.get("entity")) : null

  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [loading, setLoading] = useState(false)
  const [direction, setDirection] = useState<"" | "sales" | "purchase">("")
  const [status, setStatus] = useState<"" | "open" | "partial" | "paid" | "cancelled">("")
  const [search, setSearch] = useState("")
  const [createOpen, setCreateOpen] = useState(false)
  const [matchInvoice, setMatchInvoice] = useState<Invoice | null>(null)
  const [autoMatchOpen, setAutoMatchOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [codefSyncOpen, setCodefSyncOpen] = useState(false)
  const [bizNoOpen, setBizNoOpen] = useState(false)
  const [entityBizNo, setEntityBizNo] = useState<string | null>(null)

  // entity.business_number 조회 (codef sync direction 자동 판별용)
  useEffect(() => {
    if (!entityId) return
    void (async () => {
      try {
        const res = await fetchAPI<Array<{ id: number; business_number: string | null }>>("/entities")
        const found = res.find(e => e.id === entityId)
        setEntityBizNo(found?.business_number || null)
      } catch {/* silent */}
    })()
  }, [entityId])

  const reload = useCallback(async () => {
    if (!entityId) return
    setLoading(true)
    try {
      const params = new URLSearchParams({ entity_id: String(entityId), limit: "200" })
      if (direction) params.set("direction", direction)
      if (status) params.set("status", status)
      if (search) params.set("counterparty", search)
      const res = await fetchAPI<{ items: Invoice[]; count: number }>(
        `/invoices?${params.toString()}`,
      )
      setInvoices(res.items)
    } catch (e) {
      toast.error(`불러오기 실패: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }, [entityId, direction, status, search])

  useEffect(() => {
    void reload()
  }, [reload])

  const summary = useMemo(() => {
    const open = invoices.filter(i => i.status === "open")
    const partial = invoices.filter(i => i.status === "partial")
    const paid = invoices.filter(i => i.status === "paid")
    const outstandingTotal = invoices
      .filter(i => i.status !== "cancelled")
      .reduce((s, i) => s + (i.outstanding || 0), 0)
    return { open: open.length, partial: partial.length, paid: paid.length, outstandingTotal }
  }, [invoices])

  if (!entityId) {
    return (
      <Card>
        <CardContent className="py-16 text-center text-muted-foreground text-sm">
          법인을 선택해주세요.
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <FileSpreadsheet className="h-6 w-6 text-muted-foreground" />
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">세금계산서</h1>
          <span className="text-xs text-muted-foreground ml-2">발생주의 / 매출·매입 인식</span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setBizNoOpen(true)}
            title={entityBizNo ? `사업자번호 ${entityBizNo}` : "사업자번호 미등록"}>
            <Building2 className="h-4 w-4 mr-1" />
            {entityBizNo ? formatBizNo(entityBizNo) : "사업자번호 등록"}
          </Button>
          <Button variant="outline" size="sm" onClick={() => setCodefSyncOpen(true)}>
            <Cloud className="h-4 w-4 mr-1" /> Codef 동기화
          </Button>
          <Button variant="outline" size="sm" onClick={() => setImportOpen(true)}>
            <Upload className="h-4 w-4 mr-1" /> Excel 가져오기
          </Button>
          <Button variant="outline" size="sm" onClick={() => setAutoMatchOpen(true)}>
            <Wand2 className="h-4 w-4 mr-1" /> 자동 매칭 후보
          </Button>
          <Button variant="outline" size="sm" onClick={() => void reload()}>
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          </Button>
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4 mr-1" /> 신규
          </Button>
        </div>
      </div>

      {/* KPI */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KPI label="미결제" value={summary.open} color="text-amber-400" />
        <KPI label="부분결제" value={summary.partial} color="text-blue-400" />
        <KPI label="완납" value={summary.paid} color="text-emerald-400" />
        <KPI label="미수/미지급 합계" value={`₩${fmtKRW(summary.outstandingTotal)}`} color="text-foreground" />
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <SegmentedSelect
          value={direction}
          onChange={(v) => setDirection(v as typeof direction)}
          options={[
            { value: "", label: "전체" },
            { value: "sales", label: "매출" },
            { value: "purchase", label: "매입" },
          ]}
        />
        <SegmentedSelect
          value={status}
          onChange={(v) => setStatus(v as typeof status)}
          options={[
            { value: "", label: "모든 상태" },
            { value: "open", label: "미결제" },
            { value: "partial", label: "부분" },
            { value: "paid", label: "완납" },
            { value: "cancelled", label: "취소" },
          ]}
        />
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="거래처 검색"
            className="pl-7 h-8 w-48"
          />
        </div>
      </div>

      {/* List */}
      <Card>
        <CardContent className="p-0">
          {loading && invoices.length === 0 ? (
            <div className="p-6 space-y-2">
              {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-10" />)}
            </div>
          ) : invoices.length === 0 ? (
            <div className="py-16 text-center text-sm text-muted-foreground">
              <FileSpreadsheet className="h-10 w-10 mx-auto mb-3 opacity-40" />
              세금계산서가 없습니다. <span className="text-foreground">[신규]</span>로 추가해주세요.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs text-muted-foreground border-b">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium">발행일</th>
                    <th className="text-left px-3 py-2 font-medium">유형</th>
                    <th className="text-left px-3 py-2 font-medium">거래처</th>
                    <th className="text-left px-3 py-2 font-medium">문서번호</th>
                    <th className="text-right px-3 py-2 font-medium">총액</th>
                    <th className="text-right px-3 py-2 font-medium">결제</th>
                    <th className="text-right px-3 py-2 font-medium">잔액</th>
                    <th className="text-left px-3 py-2 font-medium">상태</th>
                    <th className="text-right px-3 py-2 font-medium">액션</th>
                  </tr>
                </thead>
                <tbody>
                  {invoices.map(inv => (
                    <tr key={inv.id} className="border-b hover:bg-secondary/30">
                      <td className="px-3 py-2 font-mono text-xs">{inv.issue_date}</td>
                      <td className="px-3 py-2">
                        <span className={cn(
                          "text-[10px] px-2 py-0.5 rounded border font-medium",
                          inv.direction === "sales"
                            ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                            : "bg-rose-500/15 text-rose-400 border-rose-500/30",
                        )}>
                          {inv.direction === "sales" ? "매출" : "매입"}
                        </span>
                      </td>
                      <td className="px-3 py-2 max-w-[240px] truncate" title={inv.counterparty}>
                        {inv.counterparty}
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{inv.document_no || "-"}</td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums">{fmtKRW(inv.total)}</td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-muted-foreground">
                        {fmtKRW(inv.paid_amount)}
                      </td>
                      <td className={cn(
                        "px-3 py-2 text-right font-mono tabular-nums font-medium",
                        inv.outstanding > 0 ? "text-foreground" : "text-muted-foreground",
                      )}>
                        {fmtKRW(inv.outstanding)}
                      </td>
                      <td className="px-3 py-2">
                        <span className={cn(
                          "text-[10px] px-2 py-0.5 rounded border font-medium",
                          STATUS_BADGE[inv.status],
                        )}>
                          {STATUS_LABELS[inv.status]}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <div className="flex justify-end gap-1">
                          {inv.status !== "cancelled" && inv.status !== "paid" && (
                            <Button variant="outline" size="sm" className="h-7 px-2"
                              onClick={() => setMatchInvoice(inv)}>
                              매칭
                            </Button>
                          )}
                          {inv.status !== "cancelled" && (
                            <Button variant="ghost" size="sm" className="h-7 w-7 p-0"
                              title="취소"
                              onClick={() => void cancelInvoice(inv.id, reload)}>
                              <XCircle className="h-3.5 w-3.5 text-rose-400" />
                            </Button>
                          )}
                          <Button variant="ghost" size="sm" className="h-7 w-7 p-0"
                            title="삭제"
                            onClick={() => void deleteInvoice(inv.id, reload)}>
                            <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {createOpen && (
        <CreateInvoiceModal
          entityId={entityId}
          onClose={() => setCreateOpen(false)}
          onCreated={() => { setCreateOpen(false); void reload() }}
        />
      )}

      {matchInvoice && (
        <MatchModal
          invoice={matchInvoice}
          onClose={() => setMatchInvoice(null)}
          onMatched={() => { setMatchInvoice(null); void reload() }}
        />
      )}

      {autoMatchOpen && entityId && (
        <AutoMatchModal
          entityId={entityId}
          onClose={() => setAutoMatchOpen(false)}
          onApplied={() => { setAutoMatchOpen(false); void reload() }}
        />
      )}

      {importOpen && entityId && (
        <ImportModal
          entityId={entityId}
          onClose={() => setImportOpen(false)}
          onImported={() => { setImportOpen(false); void reload() }}
        />
      )}

      {codefSyncOpen && entityId && (
        <CodefSyncModal
          entityId={entityId}
          ourBizNo={entityBizNo}
          onClose={() => setCodefSyncOpen(false)}
          onSynced={() => { setCodefSyncOpen(false); void reload() }}
        />
      )}

      {bizNoOpen && entityId && (
        <BizNoModal
          entityId={entityId}
          current={entityBizNo}
          onClose={() => setBizNoOpen(false)}
          onSaved={(v) => { setEntityBizNo(v); setBizNoOpen(false) }}
        />
      )}
    </div>
  )
}


function formatBizNo(s: string | null): string {
  if (!s) return ""
  const d = s.replace(/\D/g, "")
  if (d.length === 10) return `${d.slice(0, 3)}-${d.slice(3, 5)}-${d.slice(5)}`
  return d
}


// ── BizNo Modal ────────────────────────────────────────────────────


function BizNoModal({
  entityId, current, onClose, onSaved,
}: {
  entityId: number
  current: string | null
  onClose: () => void
  onSaved: (bizNo: string | null) => void
}) {
  const [val, setVal] = useState(current ? formatBizNo(current) : "")
  const [submitting, setSubmitting] = useState(false)

  async function handleSave() {
    setSubmitting(true)
    try {
      const res = await fetchAPI<{ business_number: string | null }>(`/entities/${entityId}`, {
        method: "PATCH",
        body: JSON.stringify({ business_number: val || null }),
      })
      toast.success("저장 완료")
      onSaved(res.business_number)
    } catch (e) {
      toast.error(`저장 실패: ${(e as Error).message}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ModalShell title="법인 사업자번호" onClose={onClose}>
      <div className="space-y-3 text-sm">
        <p className="text-xs text-muted-foreground">
          Codef 홈택스 동기화 시 매출/매입 자동 판별에 사용됩니다. 10자리 숫자 (하이픈 자동 제거).
        </p>
        <Field label="사업자번호">
          <Input value={val} onChange={(e) => setVal(e.target.value)}
            placeholder="123-45-67890" />
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={submitting}>취소</Button>
          <Button onClick={handleSave} disabled={submitting}>
            {submitting ? "저장 중..." : "저장"}
          </Button>
        </div>
      </div>
    </ModalShell>
  )
}


// ── Codef Sync Modal ──────────────────────────────────────────────


function CodefSyncModal({
  entityId, ourBizNo, onClose, onSynced,
}: {
  entityId: number
  ourBizNo: string | null
  onClose: () => void
  onSynced: () => void
}) {
  const today = new Date()
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1)
  const fmtYYYYMMDD = (d: Date) =>
    `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`

  const [startDate, setStartDate] = useState(fmtYYYYMMDD(monthStart))
  const [endDate, setEndDate] = useState(fmtYYYYMMDD(today))
  const [queryType, setQueryType] = useState<"1" | "2" | "3">("3")
  const [overrideBizNo, setOverrideBizNo] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<null | {
    fetched: number; inserted: number; duplicates: number;
    skipped: number; unknown_direction: number;
    our_biz_no_used?: string | null
  }>(null)

  async function handleSync() {
    if (!/^\d{8}$/.test(startDate) || !/^\d{8}$/.test(endDate)) {
      toast.error("날짜는 YYYYMMDD 형식이어야 합니다.")
      return
    }
    setSubmitting(true)
    setResult(null)
    try {
      const body: Record<string, unknown> = {
        entity_id: entityId,
        start_date: startDate,
        end_date: endDate,
        query_type: queryType,
      }
      if (overrideBizNo) body.our_biz_no = overrideBizNo
      const res = await fetchAPI<typeof result>("/integrations/codef/sync-tax-invoice", {
        method: "POST",
        body: JSON.stringify(body),
      })
      setResult(res)
      if (res && res.inserted > 0) {
        toast.success(`${res.inserted}건 등록`)
        onSynced()
      } else {
        toast.info("새로 등록된 세금계산서 없음")
      }
    } catch (e) {
      toast.error(`동기화 실패: ${(e as Error).message}`)
    } finally {
      setSubmitting(false)
    }
  }

  const effectiveBizNo = overrideBizNo || ourBizNo

  return (
    <ModalShell title="홈택스 세금계산서 동기화 (Codef)" onClose={onClose}>
      <div className="space-y-3 text-sm">
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-md p-3 text-xs">
          <div className="flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-400 mt-0.5 shrink-0" />
            <div>
              사전에 Codef 콘솔에서 사업자 인증서 + 홈택스 ID/PW 로 connected_id 등록 필요.
              사업자번호로 매출/매입 자동 판별. 매칭 안 되는 행은 'unknown' 으로 등록되니 수동 결정 필요.
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <Field label="시작일 (YYYYMMDD) *">
            <Input value={startDate} onChange={(e) => setStartDate(e.target.value)}
              placeholder="20260401" maxLength={8} />
          </Field>
          <Field label="종료일 (YYYYMMDD) *">
            <Input value={endDate} onChange={(e) => setEndDate(e.target.value)}
              placeholder="20260428" maxLength={8} />
          </Field>
        </div>

        <Field label="조회 유형">
          <SegmentedSelect
            value={queryType}
            onChange={setQueryType}
            options={[
              { value: "3", label: "전체" },
              { value: "1", label: "매출" },
              { value: "2", label: "매입" },
            ]}
          />
        </Field>

        <Field label={ourBizNo ? `사업자번호 (등록됨: ${formatBizNo(ourBizNo)})` : "사업자번호 (이번만 사용)"}>
          <Input value={overrideBizNo} onChange={(e) => setOverrideBizNo(e.target.value)}
            placeholder={ourBizNo ? "비워두면 등록값 사용" : "123-45-67890"} />
        </Field>
        {!effectiveBizNo && (
          <p className="text-xs text-amber-400">
            사업자번호 없이 동기화하면 모든 invoice 가 direction='unknown' 으로 들어갑니다.
          </p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="outline" onClick={onClose} disabled={submitting}>닫기</Button>
          <Button onClick={handleSync} disabled={submitting}>
            {submitting ? "동기화 중..." : "동기화 실행"}
          </Button>
        </div>

        {result && (
          <div className="border rounded-md mt-3 px-3 py-2 text-xs space-y-1">
            <div>가져옴: <span className="font-mono">{result.fetched}</span></div>
            <div className="text-emerald-400">신규 등록: <span className="font-mono">{result.inserted}</span></div>
            <div className="text-muted-foreground">중복: <span className="font-mono">{result.duplicates}</span></div>
            <div className="text-muted-foreground">건너뜀: <span className="font-mono">{result.skipped}</span></div>
            <div className="text-amber-400">unknown direction: <span className="font-mono">{result.unknown_direction}</span></div>
            {result.our_biz_no_used && (
              <div className="text-muted-foreground">기준 사업자번호: <span className="font-mono">{formatBizNo(result.our_biz_no_used)}</span></div>
            )}
          </div>
        )}
      </div>
    </ModalShell>
  )
}


// ── Import Modal ────────────────────────────────────────────────────


interface ImportPreview {
  parsed: Array<{
    direction: string
    counterparty: string
    issue_date: string
    document_no: string | null
    amount: number
    vat: number
    total: number
    row_number: number
  }>
  inserted: number
  duplicates: number
  skipped: number
  errors: Array<{ row: number; message: string }>
  stats: { total: number; valid: number; errors: number; unknown_direction: number }
  column_map: Record<string, string>
  header_row: number
}

function ImportModal({
  entityId, onClose, onImported,
}: {
  entityId: number
  onClose: () => void
  onImported: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [ourBizNo, setOurBizNo] = useState("")
  const [skipUnknown, setSkipUnknown] = useState(true)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function runImport(dryRun: boolean) {
    if (!file) {
      toast.error("Excel 파일을 선택해주세요.")
      return
    }
    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append("entity_id", String(entityId))
      fd.append("file", file)
      fd.append("dry_run", String(dryRun))
      fd.append("skip_unknown_direction", String(skipUnknown))
      if (ourBizNo) fd.append("our_biz_no", ourBizNo)

      const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"
      const res = await fetch(`${apiBase}/api/invoices/import`, {
        method: "POST",
        body: fd,
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || `HTTP ${res.status}`)
      }
      const data = await res.json() as ImportPreview
      setPreview(data)
      if (dryRun) {
        toast.success(`미리보기: ${data.stats.valid}건 정상, ${data.stats.errors}건 오류`)
      } else {
        toast.success(`등록 완료: ${data.inserted}건 신규, ${data.duplicates}건 중복, ${data.skipped}건 건너뜀`)
        if (data.inserted > 0) onImported()
      }
    } catch (e) {
      toast.error(`업로드 실패: ${(e as Error).message}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ModalShell title="세금계산서 Excel 가져오기" onClose={onClose} wide>
      <div className="space-y-3 text-sm">
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-md p-3 text-xs">
          <div className="flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-400 mt-0.5 shrink-0" />
            <div>
              홈택스 / 회계법인 발행 표준 Excel 양식 자동 매핑 (작성일자, 공급가액, 세액, 합계금액, 사업자번호 등).
              사업자번호 입력 시 매출/매입 자동 판별. 미입력 시 모두 'unknown' 으로 들어가니 직접 결정 필요.
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Excel 파일 *">
            <Input type="file" accept=".xls,.xlsx"
              onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </Field>
          <Field label="우리 사업자번호 (direction 자동 판별)">
            <Input value={ourBizNo} onChange={(e) => setOurBizNo(e.target.value)}
              placeholder="123-45-67890" />
          </Field>
        </div>

        <label className="flex items-center gap-2 text-xs cursor-pointer">
          <input type="checkbox" checked={skipUnknown}
            onChange={(e) => setSkipUnknown(e.target.checked)} />
          direction 판별 안 되는 행 건너뛰기 (사업자번호 매칭 실패 시)
        </label>

        <div className="flex gap-2">
          <Button variant="outline" onClick={() => void runImport(true)}
            disabled={submitting || !file}>
            미리보기 (dry-run)
          </Button>
          <Button onClick={() => void runImport(false)}
            disabled={submitting || !file}>
            {submitting ? "처리 중..." : "등록 실행"}
          </Button>
        </div>

        {preview && (
          <div className="border rounded-md mt-3">
            <div className="px-3 py-2 border-b bg-secondary/30 text-xs flex gap-4">
              <span>전체 {preview.stats.total}</span>
              <span className="text-emerald-400">정상 {preview.stats.valid}</span>
              <span className="text-rose-400">오류 {preview.stats.errors}</span>
              <span className="text-amber-400">unknown {preview.stats.unknown_direction}</span>
              {preview.inserted > 0 && (
                <span className="text-emerald-400 ml-auto">신규 등록 {preview.inserted}건</span>
              )}
              {preview.duplicates > 0 && (
                <span className="text-muted-foreground">중복 {preview.duplicates}건</span>
              )}
              {preview.skipped > 0 && (
                <span className="text-muted-foreground">건너뜀 {preview.skipped}건</span>
              )}
            </div>
            {preview.parsed.length > 0 && (
              <div className="max-h-64 overflow-y-auto text-xs">
                <table className="w-full">
                  <thead className="text-muted-foreground border-b sticky top-0 bg-card">
                    <tr>
                      <th className="text-left px-2 py-1">행</th>
                      <th className="text-left px-2 py-1">유형</th>
                      <th className="text-left px-2 py-1">날짜</th>
                      <th className="text-left px-2 py-1">거래처</th>
                      <th className="text-left px-2 py-1">문서번호</th>
                      <th className="text-right px-2 py-1">합계</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.parsed.slice(0, 50).map((p, i) => (
                      <tr key={i} className="border-b">
                        <td className="px-2 py-1 font-mono">{p.row_number}</td>
                        <td className="px-2 py-1">
                          <span className={cn(
                            "px-1.5 rounded text-[10px]",
                            p.direction === "sales" ? "bg-emerald-500/15 text-emerald-400"
                              : p.direction === "purchase" ? "bg-rose-500/15 text-rose-400"
                              : "bg-amber-500/15 text-amber-400",
                          )}>
                            {p.direction === "sales" ? "매출" : p.direction === "purchase" ? "매입" : "?"}
                          </span>
                        </td>
                        <td className="px-2 py-1 font-mono">{p.issue_date}</td>
                        <td className="px-2 py-1 max-w-[160px] truncate">{p.counterparty}</td>
                        <td className="px-2 py-1">{p.document_no || "-"}</td>
                        <td className="px-2 py-1 text-right font-mono tabular-nums">{fmtKRW(p.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {preview.errors.length > 0 && (
              <div className="border-t px-3 py-2 text-xs">
                <div className="text-rose-400 mb-1">오류 ({preview.errors.length}건)</div>
                <ul className="space-y-0.5 max-h-32 overflow-y-auto">
                  {preview.errors.slice(0, 20).map((er, i) => (
                    <li key={i} className="text-muted-foreground">행 {er.row}: {er.message}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </ModalShell>
  )
}


// ── KPI ────────────────────────────────────────────────────────────


function KPI({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <Card>
      <CardContent className="py-4 px-5">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={cn("text-xl font-semibold tabular-nums mt-1", color)}>{value}</p>
      </CardContent>
    </Card>
  )
}


function SegmentedSelect<T extends string>({
  value, onChange, options,
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string }[]
}) {
  return (
    <div className="flex border rounded-md overflow-hidden">
      {options.map(opt => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={cn(
            "px-3 py-1.5 text-xs font-medium",
            value === opt.value
              ? "bg-foreground text-background"
              : "text-muted-foreground hover:bg-secondary/50",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}


// ── Actions ────────────────────────────────────────────────────────


async function cancelInvoice(id: number, reload: () => Promise<void>) {
  if (!confirm("이 세금계산서를 취소합니다. 매칭된 결제는 모두 해제됩니다. 계속할까요?")) return
  try {
    await fetchAPI(`/invoices/${id}/cancel`, {
      method: "POST",
      body: JSON.stringify({}),
    })
    toast.success("취소 완료")
    await reload()
  } catch (e) {
    toast.error(`취소 실패: ${(e as Error).message}`)
  }
}

async function deleteInvoice(id: number, reload: () => Promise<void>) {
  if (!confirm("세금계산서를 영구 삭제합니다. 매칭 행도 함께 삭제됩니다.")) return
  try {
    await fetchAPI(`/invoices/${id}`, { method: "DELETE" })
    toast.success("삭제 완료")
    await reload()
  } catch (e) {
    toast.error(`삭제 실패: ${(e as Error).message}`)
  }
}


// ── Create Modal ──────────────────────────────────────────────────


function CreateInvoiceModal({
  entityId, onClose, onCreated,
}: {
  entityId: number
  onClose: () => void
  onCreated: () => void
}) {
  const [direction, setDirection] = useState<"sales" | "purchase">("sales")
  const [counterparty, setCounterparty] = useState("")
  const [bizNo, setBizNo] = useState("")
  const [issueDate, setIssueDate] = useState(todayISO())
  const [dueDate, setDueDate] = useState("")
  const [docNo, setDocNo] = useState("")
  const [amountStr, setAmountStr] = useState("")
  const [vatStr, setVatStr] = useState("")
  const [description, setDescription] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const amount = Number(amountStr.replace(/,/g, "")) || 0
  const vatAuto = Math.round(amount * 0.1)
  const vat = vatStr === "" ? vatAuto : (Number(vatStr.replace(/,/g, "")) || 0)
  const total = amount + vat

  async function handleSubmit() {
    if (!counterparty || !amount) {
      toast.error("거래처와 금액(공급가액)은 필수입니다.")
      return
    }
    setSubmitting(true)
    try {
      await fetchAPI("/invoices", {
        method: "POST",
        body: JSON.stringify({
          entity_id: entityId,
          direction,
          counterparty,
          counterparty_biz_no: bizNo || null,
          issue_date: issueDate,
          due_date: dueDate || null,
          document_no: docNo || null,
          amount,
          vat,
          description: description || null,
        }),
      })
      toast.success("세금계산서 등록 완료")
      onCreated()
    } catch (e) {
      toast.error(`등록 실패: ${(e as Error).message}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ModalShell title="세금계산서 신규" onClose={onClose}>
      <div className="space-y-3">
        <div>
          <label className="text-xs text-muted-foreground block mb-1">유형</label>
          <SegmentedSelect
            value={direction}
            onChange={setDirection}
            options={[
              { value: "sales", label: "매출 (받을 돈)" },
              { value: "purchase", label: "매입 (줄 돈)" },
            ]}
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Field label="거래처 *">
            <Input value={counterparty} onChange={(e) => setCounterparty(e.target.value)} />
          </Field>
          <Field label="사업자번호">
            <Input value={bizNo} onChange={(e) => setBizNo(e.target.value)} placeholder="123-45-67890" />
          </Field>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <Field label="발행일 *">
            <Input type="date" value={issueDate} onChange={(e) => setIssueDate(e.target.value)} />
          </Field>
          <Field label="결제 예정일">
            <Input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
          </Field>
          <Field label="문서번호">
            <Input value={docNo} onChange={(e) => setDocNo(e.target.value)} />
          </Field>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <Field label="공급가액 *">
            <Input value={amountStr} onChange={(e) => setAmountStr(e.target.value)}
              placeholder="0" className="font-mono text-right" />
          </Field>
          <Field label={`부가세 (자동 ${fmtKRW(vatAuto)})`}>
            <Input value={vatStr} onChange={(e) => setVatStr(e.target.value)}
              placeholder={String(vatAuto)} className="font-mono text-right" />
          </Field>
          <Field label="합계">
            <Input value={fmtKRW(total)} readOnly disabled
              className="font-mono text-right bg-secondary/30" />
          </Field>
        </div>
        <Field label="설명">
          <Input value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
      </div>
      <div className="flex justify-end gap-2 mt-4">
        <Button variant="outline" onClick={onClose} disabled={submitting}>취소</Button>
        <Button onClick={handleSubmit} disabled={submitting}>
          {submitting ? "등록 중..." : "등록"}
        </Button>
      </div>
    </ModalShell>
  )
}


// ── Match Modal ────────────────────────────────────────────────────


function MatchModal({
  invoice, onClose, onMatched,
}: {
  invoice: Invoice
  onClose: () => void
  onMatched: () => void
}) {
  const [txs, setTxs] = useState<TxLite[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const expectedType = invoice.direction === "sales" ? "in" : "out"

  useEffect(() => {
    void (async () => {
      try {
        const params = new URLSearchParams({
          entity_id: String(invoice.entity_id),
          tx_type: expectedType,
          per_page: "100",
        })
        if (search) params.set("search", search)
        const res = await fetchAPI<{ items: TxLite[] }>(`/transactions?${params.toString()}`)
        setTxs(res.items)
      } catch (e) {
        toast.error(`거래 조회 실패: ${(e as Error).message}`)
      } finally {
        setLoading(false)
      }
    })()
  }, [invoice.entity_id, expectedType, search])

  async function handleMatch(txId: number) {
    setSubmitting(true)
    try {
      await fetchAPI(`/invoices/${invoice.id}/payments`, {
        method: "POST",
        body: JSON.stringify({ transaction_id: txId, matched_by: "manual" }),
      })
      toast.success("매칭 완료")
      onMatched()
    } catch (e) {
      toast.error(`매칭 실패: ${(e as Error).message}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ModalShell title={`매칭: ${invoice.counterparty}`} onClose={onClose} wide>
      <div className="text-xs text-muted-foreground mb-3 space-y-1">
        <div>
          {invoice.direction === "sales" ? "매출 (입금)" : "매입 (출금)"} ·
          발행 {invoice.issue_date} · 잔액 ₩{fmtKRW(invoice.outstanding)}
        </div>
        <div>거래는 type={expectedType} 만 표시됩니다.</div>
      </div>
      <div className="relative mb-2">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="거래처/설명 검색"
          className="pl-7 h-8"
        />
      </div>
      <div className="border rounded max-h-[400px] overflow-y-auto">
        {loading ? (
          <div className="p-6 space-y-2">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-8" />)}</div>
        ) : txs.length === 0 ? (
          <div className="py-12 text-center text-sm text-muted-foreground">매칭 가능한 거래가 없습니다.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground border-b sticky top-0 bg-card">
              <tr>
                <th className="text-left px-3 py-2 font-medium">날짜</th>
                <th className="text-left px-3 py-2 font-medium">거래처</th>
                <th className="text-right px-3 py-2 font-medium">금액</th>
                <th className="text-right px-3 py-2 font-medium">액션</th>
              </tr>
            </thead>
            <tbody>
              {txs.map(tx => {
                const exact = Math.abs(tx.amount - invoice.outstanding) < 1
                return (
                  <tr key={tx.id} className={cn("border-b hover:bg-secondary/30", exact && "bg-emerald-500/5")}>
                    <td className="px-3 py-2 font-mono text-xs">{tx.date}</td>
                    <td className="px-3 py-2 max-w-[280px] truncate">
                      {tx.counterparty || tx.description || "-"}
                    </td>
                    <td className={cn(
                      "px-3 py-2 text-right font-mono tabular-nums",
                      exact && "text-emerald-400 font-semibold",
                    )}>
                      {fmtKRW(tx.amount)}
                      {exact && <span className="ml-1 text-[10px]">정확일치</span>}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Button size="sm" variant="outline" className="h-7 px-2"
                        disabled={submitting}
                        onClick={() => void handleMatch(tx.id)}>
                        매칭
                      </Button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </ModalShell>
  )
}


// ── Auto Match Modal ──────────────────────────────────────────────


function AutoMatchModal({
  entityId, onClose, onApplied,
}: {
  entityId: number
  onClose: () => void
  onApplied: () => void
}) {
  const [cands, setCands] = useState<AutoMatchCandidate[]>([])
  const [loading, setLoading] = useState(true)
  const [applying, setApplying] = useState<number | null>(null)
  const [appliedIds, setAppliedIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetchAPI<{ candidates: AutoMatchCandidate[] }>(
          `/invoices/auto-match?entity_id=${entityId}&days_window=14`,
        )
        setCands(res.candidates)
      } catch (e) {
        toast.error(`후보 조회 실패: ${(e as Error).message}`)
      } finally {
        setLoading(false)
      }
    })()
  }, [entityId])

  async function applyOne(c: AutoMatchCandidate) {
    setApplying(c.invoice_id)
    try {
      await fetchAPI(`/invoices/${c.invoice_id}/payments`, {
        method: "POST",
        body: JSON.stringify({ transaction_id: c.transaction_id, matched_by: "auto" }),
      })
      setAppliedIds((s) => new Set(s).add(`${c.invoice_id}-${c.transaction_id}`))
      toast.success(`매칭 적용: invoice ${c.invoice_id}`)
    } catch (e) {
      toast.error(`적용 실패: ${(e as Error).message}`)
    } finally {
      setApplying(null)
    }
  }

  return (
    <ModalShell title="자동 매칭 후보" onClose={() => { onApplied(); onClose() }} wide>
      <p className="text-xs text-muted-foreground mb-3">
        거래처+금액 일치 + 일자 ±14일 안에 들어오는 미결제 invoice ↔ 미매칭 거래 후보. score 가 높을수록 정확.
      </p>
      <div className="border rounded max-h-[500px] overflow-y-auto">
        {loading ? (
          <div className="p-6 space-y-2">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : cands.length === 0 ? (
          <div className="py-12 text-center text-sm text-muted-foreground">매칭 후보 없음.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground border-b sticky top-0 bg-card">
              <tr>
                <th className="text-left px-2 py-2 font-medium">Score</th>
                <th className="text-left px-2 py-2 font-medium">Invoice</th>
                <th className="text-left px-2 py-2 font-medium">Transaction</th>
                <th className="text-right px-2 py-2 font-medium">금액</th>
                <th className="text-left px-2 py-2 font-medium">사유</th>
                <th className="text-right px-2 py-2 font-medium">액션</th>
              </tr>
            </thead>
            <tbody>
              {cands.map(c => {
                const key = `${c.invoice_id}-${c.transaction_id}`
                const applied = appliedIds.has(key)
                return (
                  <tr key={key} className={cn("border-b", applied && "opacity-50")}>
                    <td className="px-2 py-2 font-mono text-xs">
                      <span className={cn(
                        "px-1.5 py-0.5 rounded text-[10px] font-semibold",
                        c.score >= 80 ? "bg-emerald-500/20 text-emerald-400"
                        : c.score >= 60 ? "bg-amber-500/20 text-amber-400"
                        : "bg-gray-500/20 text-gray-400",
                      )}>{c.score}</span>
                    </td>
                    <td className="px-2 py-2 text-xs">
                      <div className="font-medium">#{c.invoice_id} {c.invoice_counterparty}</div>
                      <div className="text-muted-foreground">due {c.due_date}</div>
                    </td>
                    <td className="px-2 py-2 text-xs">
                      <div className="font-medium">#{c.transaction_id} {c.transaction_counterparty}</div>
                      <div className="text-muted-foreground">{c.tx_date}</div>
                    </td>
                    <td className="px-2 py-2 text-right font-mono tabular-nums text-xs">
                      ₩{fmtKRW(c.amount)}
                      {c.invoice_outstanding !== c.transaction_amount && (
                        <div className="text-[10px] text-muted-foreground">
                          inv {fmtKRW(c.invoice_outstanding)} / tx {fmtKRW(c.transaction_amount)}
                        </div>
                      )}
                    </td>
                    <td className="px-2 py-2 text-[10px] text-muted-foreground">{c.reason}</td>
                    <td className="px-2 py-2 text-right">
                      {applied ? (
                        <span className="text-[10px] text-emerald-400">적용됨</span>
                      ) : (
                        <Button size="sm" variant="outline" className="h-7 px-2"
                          disabled={applying === c.invoice_id}
                          onClick={() => void applyOne(c)}>
                          적용
                        </Button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </ModalShell>
  )
}


// ── Modal Shell ────────────────────────────────────────────────────


function ModalShell({
  title, onClose, wide, children,
}: {
  title: string
  onClose: () => void
  wide?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className={cn(
        "bg-card border rounded-lg shadow-xl w-full max-h-[90vh] overflow-y-auto",
        wide ? "max-w-4xl" : "max-w-xl",
      )}>
        <div className="flex items-center justify-between border-b px-5 py-3">
          <h2 className="font-semibold">{title}</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}


function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-xs text-muted-foreground block mb-1">{label}</label>
      {children}
    </div>
  )
}
