"use client"

import { useState, useCallback, useEffect, useRef, Suspense } from "react"
import { useSearchParams } from "next/navigation"
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { EntityTabs } from "@/components/entity-tabs"
import { MonthPicker } from "@/components/month-picker"
import { fetchAPI } from "@/lib/api"
import { formatKRW } from "@/lib/format"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import {
  MessageSquare,
  Check,
  EyeOff,
  Search,
  RefreshCw,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
} from "lucide-react"

// ── Name color helper ─────────────────────────────────
const NAME_COLORS = [
  "bg-blue-500/20 text-blue-300 ring-blue-500/30",
  "bg-emerald-500/20 text-emerald-300 ring-emerald-500/30",
  "bg-amber-500/20 text-amber-300 ring-amber-500/30",
  "bg-purple-500/20 text-purple-300 ring-purple-500/30",
  "bg-rose-500/20 text-rose-300 ring-rose-500/30",
  "bg-cyan-500/20 text-cyan-300 ring-cyan-500/30",
  "bg-orange-500/20 text-orange-300 ring-orange-500/30",
  "bg-indigo-500/20 text-indigo-300 ring-indigo-500/30",
  "bg-teal-500/20 text-teal-300 ring-teal-500/30",
  "bg-pink-500/20 text-pink-300 ring-pink-500/30",
  "bg-lime-500/20 text-lime-300 ring-lime-500/30",
  "bg-sky-500/20 text-sky-300 ring-sky-500/30",
]
function nameColor(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash)
  return NAME_COLORS[Math.abs(hash) % NAME_COLORS.length]
}

// ── Types ──────────────────────────────────────────────

interface ParsedStructured {
  summary: string | null
  vendor: string | null
  project: string | null
  category: string | null
  items: Array<{ description: string; amount: number; currency: string }> | null
  total_amount: number | null
  currency: string | null
  vat: { type: string; vat_amount: number | null; supply_amount: number | null } | null
  withholding_tax: { applies: boolean; rate: number | null; amount: number | null; net_amount: number | null } | null
  payment_terms: { type: string; ratio: string | null; related_context: string | null } | null
  tax_invoice: boolean
  date_mentioned: string | null
  urgency: string | null
  confidence: number | null
}

interface ItemMatch {
  item_index: number
  item_description: string
  amount: number | null
  currency: string
  transaction_id: number | null
  transaction_ids?: number[] | null
  is_confirmed: boolean
}

interface MatchProgress {
  total_items: number
  matched_items: number
}

interface SlackMessage {
  id: number
  entity_id: number
  channel_name: string
  sender_name: string | null
  message_text: string
  parsed_amount: number | null
  parsed_currency: string | null
  message_date: string
  is_completed: boolean
  is_cancelled: boolean
  slack_status: string | null
  message_type: string | null
  member_id: number | null
  member_name_ko: string | null
  match_id: number | null
  matched_transaction_id: number | null
  match_confidence: number | null
  parsed_structured: ParsedStructured | null
  item_matches?: ItemMatch[]
  match_progress?: MatchProgress
  parsed_amount_krw?: number
  exchange_rate?: number
}

interface MonthlySummary {
  yr: number
  mo: number
  total: number
  done_count: number
  pending_count: number
  cancelled_count: number
  total_expense: number
}

interface SlackMessagesResponse {
  items: SlackMessage[]
  total: number
  page: number
  pages: number
  monthly_summary: MonthlySummary[]
}

interface MatchCandidate {
  id: number
  date: string
  description: string
  amount: number
  counterparty: string
  confidence: number
  match_type: string
  member_name?: string | null
}

interface CandidatesResponse {
  candidates: MatchCandidate[]
}

type StatusFilter = "all" | "pending" | "confirmed" | "ignored"
type ConfidenceFilter = "all" | "high" | "medium" | "low"

// ── Helpers ────────────────────────────────────────────

function getConfidenceBadge(confidence: number | null) {
  if (confidence === null) return null
  const pct = Math.round(confidence * 100)
  let className = ""
  if (pct >= 90) {
    className = "bg-[hsl(var(--profit))]/20 text-[hsl(var(--profit))] border-[hsl(var(--profit))]/30"
  } else if (pct >= 70) {
    className = "bg-[hsl(var(--warning))]/20 text-[hsl(var(--warning))] border-[hsl(var(--warning))]/30"
  } else {
    className = "bg-[hsl(var(--loss))]/20 text-[hsl(var(--loss))] border-[hsl(var(--loss))]/30"
  }
  return (
    <Badge variant="outline" className={`text-[11px] px-1.5 py-0 ${className}`}>
      {pct}%
    </Badge>
  )
}

function stripSlackText(text: string): string {
  return text
    .replace(/<@[A-Z0-9]+>/g, "")           // 멘션 제거
    .replace(/<#[A-Z0-9]+\|([^>]+)>/g, "$1") // 채널 링크 → 채널명
    .replace(/<(https?:\/\/[^|>]+)\|([^>]+)>/g, "$2") // URL 링크 → 표시 텍스트
    .replace(/<(https?:\/\/[^>]+)>/g, "$1")  // URL 링크 (표시 텍스트 없음)
    .replace(/\*([^*]+)\*/g, "$1")           // 볼드 제거
    .replace(/_([^_]+)_/g, "$1")             // 이탤릭 제거
    .replace(/~([^~]+)~/g, "$1")             // 취소선 제거
    .replace(/\n+/g, " ")                    // 줄바꿈 → 공백
    .replace(/\s+/g, " ")                    // 다중 공백 정리
    .trim()
}

function getMessageStatus(msg: SlackMessage): "confirmed" | "ignored" | "pending" | "partial" {
  if (msg.is_completed && msg.matched_transaction_id) return "confirmed"
  if (msg.is_completed && msg.match_progress?.matched_items === msg.match_progress?.total_items) return "confirmed"
  if (msg.is_cancelled) return "ignored"
  if (msg.match_progress && msg.match_progress.matched_items > 0) return "partial"
  return "pending"
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${m}.${day}.`
}

function getTypeBadge(type: string | null) {
  if (!type) return null
  const typeMap: Record<string, { label: string; className: string }> = {
    card_payment: { label: "법카결제", className: "bg-purple-500/20 text-purple-400 border-purple-500/30" },
    deposit_request: { label: "입금요청", className: "bg-blue-500/20 text-blue-400 border-blue-500/30" },
    tax_invoice: { label: "세금계산서", className: "bg-teal-500/20 text-teal-400 border-teal-500/30" },
    expense_share: { label: "비용공유", className: "bg-orange-500/20 text-orange-400 border-orange-500/30" },
  }
  const info = typeMap[type] || { label: type, className: "bg-secondary text-muted-foreground border-border" }
  return (
    <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${info.className}`}>
      {info.label}
    </Badge>
  )
}

function getStatusDot(status: "confirmed" | "ignored" | "pending" | "partial") {
  if (status === "confirmed") return <span className="h-2 w-2 rounded-full bg-[hsl(var(--profit))] inline-block" />
  if (status === "partial") return <span className="w-2 h-2 rounded-full bg-yellow-400 inline-block" />
  if (status === "pending") return <span className="h-2 w-2 rounded-full bg-[hsl(var(--warning))] inline-block" />
  return <span className="h-2 w-2 rounded-full bg-[hsl(var(--loss))] inline-block" />
}

// ── Skeletons ──────────────────────────────────────────

function MessageCardSkeleton() {
  return (
    <Card className="bg-card rounded-xl shadow">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Skeleton className="h-5 w-12" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-20" />
        </div>
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-6 w-24" />
        <div className="flex gap-2">
          <Skeleton className="h-8 w-16" />
          <Skeleton className="h-8 w-20" />
          <Skeleton className="h-8 w-12" />
        </div>
      </CardContent>
    </Card>
  )
}

function CandidatePanelSkeleton() {
  return (
    <Card className="bg-card rounded-xl shadow">
      <CardContent className="p-4 space-y-4">
        <Skeleton className="h-5 w-20" />
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="space-y-2 border-b border-border pb-3">
            <div className="flex items-center gap-2">
              <Skeleton className="h-4 w-4 rounded-full" />
              <Skeleton className="h-4 w-40" />
            </div>
            <Skeleton className="h-5 w-24 ml-6" />
            <Skeleton className="h-3 w-32 ml-6" />
          </div>
        ))}
        <div className="flex gap-2">
          <Skeleton className="h-9 w-24" />
          <Skeleton className="h-9 w-24" />
        </div>
      </CardContent>
    </Card>
  )
}

// ── KPI Cards ─────────────────────────────────────────

function KPICards({
  total,
  doneCount,
  pendingCount,
  cancelledCount,
}: {
  total: number
  doneCount: number
  pendingCount: number
  cancelledCount: number
}) {
  const cards = [
    { label: "전체", value: total, className: "text-foreground" },
    { label: "완료", value: doneCount, className: "text-[hsl(var(--profit))]" },
    { label: "미처리", value: pendingCount, className: "text-[hsl(var(--warning))]" },
    { label: "취소", value: cancelledCount, className: "text-[hsl(var(--loss))]" },
  ]
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {cards.map((c) => (
        <Card key={c.label} className="bg-card border-white/[0.04] backdrop-blur">
          <CardContent className="p-4 flex flex-col items-center gap-1">
            <span className="text-xs text-muted-foreground">{c.label}</span>
            <span className={cn("text-2xl font-mono font-bold tabular-nums", c.className)}>
              {c.value}
            </span>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

// ── Structured Detail ─────────────────────────────────

function StructuredDetail({ data }: { data: ParsedStructured }) {
  const vatLabel =
    data.vat?.type === "included" ? "포함" :
    data.vat?.type === "excluded" ? "별도" : "해당없음"

  const paymentLabel =
    data.payment_terms?.type === "full" ? "일시불" :
    data.payment_terms?.type === "advance" ? "선금" :
    data.payment_terms?.type === "balance" ? "잔금" :
    data.payment_terms?.type === "installment" ? "분할" : "일시불"

  return (
    <div className="space-y-3">
      {/* 메타 정보 */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        {data.project && (
          <>
            <span className="text-muted-foreground">프로젝트</span>
            <span className="font-medium">{data.project}</span>
          </>
        )}
        {data.vendor && (
          <>
            <span className="text-muted-foreground">거래처</span>
            <span className="font-medium">{data.vendor}</span>
          </>
        )}
        {data.category && (
          <>
            <span className="text-muted-foreground">카테고리</span>
            <span className="font-medium">{data.category}</span>
          </>
        )}
      </div>

      {/* 항목 테이블 */}
      {data.items && data.items.length > 0 && (
        <div className="rounded-md border border-white/[0.06] overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-white/[0.06] bg-secondary/30">
                <th className="text-left px-2 py-1.5 font-medium text-muted-foreground">항목</th>
                <th className="text-right px-2 py-1.5 font-medium text-muted-foreground">금액</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item, i) => (
                <tr key={i} className="border-b border-white/[0.04] last:border-0">
                  <td className="px-2 py-1.5">{item.description}</td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums">
                    {item.currency === "USD" ? (
                      <span>
                        ${item.amount.toLocaleString()}
                        {(item as Record<string, unknown>).amount_krw != null && (
                          <span className="text-[10px] text-muted-foreground ml-1">
                            ({formatKRW((item as Record<string, unknown>).amount_krw as number)})
                          </span>
                        )}
                      </span>
                    ) : formatKRW(item.amount)}
                  </td>
                </tr>
              ))}
              {data.items.length > 1 && data.total_amount && (
                <tr className="bg-secondary/20 font-medium">
                  <td className="px-2 py-1.5">합계</td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums">
                    {data.currency === "USD" ? (
                      <span>
                        ${data.total_amount.toLocaleString()}
                        {(data as Record<string, unknown>).total_amount_krw != null && (
                          <span className="text-[10px] text-muted-foreground ml-1">
                            ({formatKRW((data as Record<string, unknown>).total_amount_krw as number)})
                          </span>
                        )}
                      </span>
                    ) : formatKRW(data.total_amount)}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* 세금/결제 정보 */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <span className="text-muted-foreground">VAT</span>
        <span>
          {vatLabel}
          {data.vat?.vat_amount != null && ` (${formatKRW(data.vat.vat_amount)})`}
        </span>

        {data.withholding_tax?.applies && (
          <>
            <span className="text-muted-foreground">원천징수</span>
            <span>
              {data.withholding_tax.rate}%
              {data.withholding_tax.amount != null && ` (${formatKRW(data.withholding_tax.amount)})`}
              {data.withholding_tax.net_amount != null && ` → 실수령 ${formatKRW(data.withholding_tax.net_amount)}`}
            </span>
          </>
        )}

        <span className="text-muted-foreground">결제조건</span>
        <span>
          {paymentLabel}
          {data.payment_terms?.ratio && ` (${data.payment_terms.ratio})`}
        </span>

        {data.tax_invoice && (
          <>
            <span className="text-muted-foreground">세금계산서</span>
            <span>발행 예정</span>
          </>
        )}

        {data.urgency && (
          <>
            <span className="text-muted-foreground">긴급도</span>
            <span className="text-[hsl(var(--loss))]">{data.urgency}</span>
          </>
        )}
      </div>
    </div>
  )
}

// ── Compact Message Row ───────────────────────────────

function CompactMessageRow({
  message,
  isSelected,
  isExpanded,
  onSelect,
  onToggleExpand,
  onConfirmDirect,
  onIgnore,
  onManualMatch,
}: {
  message: SlackMessage
  isSelected: boolean
  isExpanded: boolean
  onSelect: () => void
  onToggleExpand: () => void
  onConfirmDirect: () => void
  onIgnore: () => void
  onManualMatch: () => void
}) {
  const status = getMessageStatus(message)

  return (
    <div
      className={cn(
        "rounded-lg border transition-all",
        isSelected
          ? "ring-2 ring-[hsl(var(--accent))] border-[hsl(var(--accent))]/30 bg-[hsl(var(--accent))]/5"
          : "border-white/[0.04] hover:bg-secondary/30",
      )}
      role="option"
      aria-selected={isSelected}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter") onSelect()
      }}
    >
      {/* Compact summary line */}
      <button
        className="w-full text-left px-3 py-2.5 flex items-center gap-2 min-w-0"
        onClick={() => { onToggleExpand(); onSelect(); }}
      >
        {/* Status dot */}
        {getStatusDot(status)}

        {/* Type badge */}
        {getTypeBadge(message.message_type)}

        {/* Date — 날짜순 정렬이므로 이름 앞에 배치 */}
        <span className="text-xs text-muted-foreground">
          {formatDate(message.message_date)}
        </span>

        {/* Sender */}
        {(message.member_name_ko || message.sender_name) && (
          <span className={cn("inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset truncate max-w-[72px]", nameColor(message.member_name_ko || message.sender_name || ""))}>
            {message.member_name_ko || message.sender_name}
          </span>
        )}

        {/* Amount - push right (구조화 파싱 총액 우선) */}
        <span className="ml-auto font-mono font-bold text-sm tabular-nums whitespace-nowrap text-right">
          {(() => {
            const structTotal = message.parsed_structured?.total_amount
            const amount = structTotal ?? message.parsed_amount
            if (amount === null && structTotal == null) return ""
            const currency = message.parsed_structured?.currency || message.parsed_currency
            if (currency === "USD") {
              const krwAmount = message.parsed_amount_krw ?? (message.parsed_structured as Record<string, unknown>)?.total_amount_krw as number | undefined
              return (
                <span className="flex flex-col items-end">
                  <span>${(amount ?? 0).toLocaleString()}</span>
                  {krwAmount != null && (
                    <span className="text-[10px] text-muted-foreground font-normal">
                      {formatKRW(krwAmount)}
                    </span>
                  )}
                </span>
              )
            }
            return formatKRW(amount ?? 0)
          })()}
        </span>

        {/* Confidence badge */}
        {status === "pending" && message.match_confidence !== null && (
          <span className="shrink-0">{getConfidenceBadge(message.match_confidence)}</span>
        )}

        {/* Match progress badge */}
        {message.match_progress && !message.is_completed && (
          <Badge
            variant="outline"
            className="text-[10px] px-1.5 py-0 bg-yellow-500/10 text-yellow-400 border-yellow-500/30"
          >
            {message.match_progress.matched_items}/{message.match_progress.total_items}
          </Badge>
        )}

        {/* Chevron */}
        <ChevronDown
          className={cn(
            "h-4 w-4 text-muted-foreground shrink-0 transition-transform",
            isExpanded && "rotate-180",
          )}
        />
      </button>

      {/* Summary preview (collapsed) */}
      {!isExpanded && message.message_text && (
        <p className="px-3 pb-2 text-xs text-muted-foreground truncate">
          {stripSlackText(message.message_text).slice(0, 80)}
        </p>
      )}

      {/* Expanded detail */}
      {isExpanded && (
        <div className="px-3 pb-3 space-y-2 border-t border-white/[0.04]">
          {/* Channel */}
          <div className="flex items-center gap-2 pt-2 text-xs">
            <Badge
              variant="outline"
              className="bg-[#6366F1]/20 text-[#6366F1] border-[#6366F1]/30 text-[11px] px-1.5 py-0"
            >
              #{message.channel_name}
            </Badge>
            <span className={cn("inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset", nameColor(message.member_name_ko || message.sender_name || ""))}>
              {message.member_name_ko || message.sender_name}
            </span>
            <span className="text-muted-foreground">&middot;</span>
            <span className="text-muted-foreground">
              {new Date(message.message_date).toLocaleDateString("ko-KR")}
            </span>
          </div>

          {/* 구조화 정보 또는 원문 */}
          {message.parsed_structured ? (
            <div className="space-y-2">
              <StructuredDetail data={message.parsed_structured} />
              {/* 원문 토글 */}
              <button
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                onClick={(e) => {
                  e.stopPropagation()
                  const el = e.currentTarget.nextElementSibling
                  if (el) el.classList.toggle("hidden")
                }}
              >
                <ChevronDown className="h-3 w-3" />
                원문 보기
              </button>
              <p className="hidden text-xs leading-relaxed text-muted-foreground whitespace-pre-wrap bg-secondary/20 rounded p-2">
                {message.message_text}
              </p>
            </div>
          ) : (
            <p className="text-sm leading-relaxed">{message.message_text}</p>
          )}

          {/* Match status */}
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">매칭 상태:</span>
            {status === "confirmed" && (
              <Badge
                variant="outline"
                className="bg-[hsl(var(--profit))]/20 text-[hsl(var(--profit))] border-0 text-[11px] px-1.5 py-0"
              >
                확정됨
              </Badge>
            )}
            {status === "ignored" && (
              <Badge
                variant="outline"
                className="bg-secondary text-muted-foreground border-0 text-[11px] px-1.5 py-0"
              >
                무시됨
              </Badge>
            )}
            {status === "pending" && message.match_confidence !== null && (
              <>
                <span className="text-muted-foreground">AI 매칭</span>
                {getConfidenceBadge(message.match_confidence)}
              </>
            )}
            {status === "pending" && message.match_confidence === null && (
              <span className="text-muted-foreground">미매칭</span>
            )}
          </div>

          {/* Actions for pending */}
          {status === "pending" && (
            <div className="flex gap-2 pt-1" onClick={(e) => e.stopPropagation()}>
              {message.matched_transaction_id && (
                <Button
                  size="sm"
                  className="bg-[hsl(var(--accent))] text-accent-foreground hover:bg-[hsl(var(--accent))]/90 h-8 text-xs"
                  onClick={onConfirmDirect}
                >
                  <Check className="h-3 w-3 mr-1" />
                  확정
                </Button>
              )}
              <Button
                size="sm"
                variant="secondary"
                className="h-8 text-xs"
                onClick={onManualMatch}
              >
                <Search className="h-3 w-3 mr-1" />
                수동 매칭
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-8 text-xs text-[hsl(var(--loss))] hover:text-[hsl(var(--loss))]"
                onClick={onIgnore}
              >
                <EyeOff className="h-3 w-3 mr-1" />
                무시
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Candidate Panel ────────────────────────────────────

function CandidatesList({
  candidates,
  selectedId,
  onSelect,
  onConfirm,
}: {
  candidates: MatchCandidate[]
  selectedId: number | null
  onSelect: (id: number | null) => void
  onConfirm: (id: number) => void
}) {
  if (candidates.length === 0) {
    return <p className="text-sm text-muted-foreground py-4 text-center">매칭 후보가 없습니다</p>
  }

  return (
    <div className="space-y-1.5 max-h-[320px] overflow-y-auto scrollbar-thin" role="listbox" aria-label="매칭 후보 목록">
      {candidates.map((candidate) => {
        const isSelected = selectedId === candidate.id
        return (
          <div
            key={candidate.id}
            role="option"
            aria-selected={isSelected}
            tabIndex={0}
            onClick={() => onSelect(isSelected ? null : candidate.id)}
            onKeyDown={(e) => { if (e.key === "Enter" && isSelected) onConfirm(candidate.id) }}
            className={cn(
              "rounded-lg p-3 transition-all border cursor-pointer",
              isSelected
                ? "border-[hsl(var(--accent))] bg-[hsl(var(--accent))]/5"
                : "border-white/[0.04] hover:bg-secondary/30"
            )}
          >
            <div className="flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-muted-foreground whitespace-nowrap shrink-0">
                    {formatDate(candidate.date)}
                  </span>
                  {candidate.member_name && (
                    <span className={cn("inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset shrink-0", nameColor(candidate.member_name))}>
                      {candidate.member_name}
                    </span>
                  )}
                  <span className="font-medium truncate">
                    {candidate.counterparty}{" "}
                    {candidate.description}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="font-mono font-semibold text-sm tabular-nums">
                    {formatKRW(candidate.amount)}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    신뢰도:
                  </span>
                  {getConfidenceBadge(candidate.confidence)}
                </div>
              </div>

              {isSelected && (
                <Button
                  size="sm"
                  className="shrink-0 bg-[hsl(var(--accent))] text-accent-foreground hover:bg-[hsl(var(--accent))]/90 h-8 px-3"
                  onClick={(e) => { e.stopPropagation(); onConfirm(candidate.id) }}
                >
                  <Check className="h-3.5 w-3.5 mr-1" />
                  확정
                </Button>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function CandidatePanel({
  messageId,
  message,
  entityId,
  onConfirm,
  onMultiConfirm,
  onRefresh,
}: {
  messageId: number
  message: SlackMessage
  entityId: string
  onConfirm: (transactionId: number) => void
  onMultiConfirm: (transactionIds: number[]) => void
  onRefresh: () => void
}) {
  const [candidates, setCandidates] = useState<MatchCandidate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedCandidateId, setSelectedCandidateId] = useState<number | null>(null)

  // 개별 매칭 상태
  const [activeItemIndex, setActiveItemIndex] = useState<number | null>(null)
  const [itemCandidates, setItemCandidates] = useState<MatchCandidate[]>([])
  const [itemCandidatesLoading, setItemCandidatesLoading] = useState(false)
  const [selectedItemCandidateId, setSelectedItemCandidateId] = useState<number | null>(null)

  // 직접 검색 상태
  const [searchMode, setSearchMode] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const [searchResults, setSearchResults] = useState<MatchCandidate[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [selectedSearchIds, setSelectedSearchIds] = useState<Set<number>>(new Set())

  const toggleSearchSelection = useCallback((id: number) => {
    setSelectedSearchIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const selectedSearchTotal = searchResults
    .filter(r => selectedSearchIds.has(r.id))
    .reduce((sum, r) => sum + r.amount, 0)

  const doSearch = useCallback(async (query: string) => {
    if (!query.trim()) return
    setSearchLoading(true)
    setSelectedSearchIds(new Set())
    try {
      const isAmount = /^[\d,]+$/.test(query.replace(/\s/g, ""))
      const params = new URLSearchParams({ entity_id: entityId })
      if (isAmount) {
        params.set("amount", query.replace(/,/g, ""))
      } else {
        params.set("q", query.trim())
      }
      const data = await fetchAPI<{ results: MatchCandidate[] }>(
        `/slack/transactions/search?${params.toString()}`,
      )
      setSearchResults(data.results.map(r => ({ ...r, confidence: 0, match_type: "manual" })))
    } catch {
      toast.error("검색에 실패했습니다")
      setSearchResults([])
    } finally {
      setSearchLoading(false)
    }
  }, [entityId])

  const items = message.parsed_structured?.items || []
  const isMultiItem = items.length >= 2

  const fetchCandidates = useCallback(async () => {
    setLoading(true)
    setError(null)
    setSelectedCandidateId(null)
    try {
      const data = await fetchAPI<CandidatesResponse>(
        `/slack/messages/${messageId}/candidates`,
      )
      setCandidates(data.candidates)
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "후보를 불러올 수 없습니다.",
      )
    } finally {
      setLoading(false)
    }
  }, [messageId])

  const fetchItemCandidates = useCallback(async (itemIdx: number) => {
    setItemCandidatesLoading(true)
    setSelectedItemCandidateId(null)
    try {
      const data = await fetchAPI<CandidatesResponse>(
        `/slack/messages/${messageId}/candidates?item_index=${itemIdx}`,
      )
      setItemCandidates(data.candidates || [])
    } catch {
      toast.error("후보 검색 중 오류가 발생했습니다")
      setItemCandidates([])
    } finally {
      setItemCandidatesLoading(false)
    }
  }, [messageId])

  const confirmItemMatch = useCallback(async (
    transactionIdOrIds: number | number[],
    itemIndex: number,
    itemDescription: string,
  ) => {
    try {
      const body = Array.isArray(transactionIdOrIds)
        ? { transaction_ids: transactionIdOrIds, item_index: itemIndex, item_description: itemDescription }
        : { transaction_id: transactionIdOrIds, item_index: itemIndex, item_description: itemDescription }
      const res = await fetchAPI<{ is_completed: boolean }>(`/slack/messages/${messageId}/confirm`, {
        method: "POST",
        body: JSON.stringify(body),
      })
      toast.success(`${itemDescription} 매칭 완료`)
      setSearchResults([])
      setSearchQuery("")
      setSelectedSearchIds(new Set())
      onRefresh()

      if (!res.is_completed) {
        const confirmedIndices = new Set([
          ...(message.item_matches || []).filter(m => m.is_confirmed).map(m => m.item_index),
          itemIndex,
        ])
        const nextUnmatched = items.findIndex((_, i) => !confirmedIndices.has(i))
        if (nextUnmatched >= 0) {
          setTimeout(() => {
            setActiveItemIndex(nextUnmatched)
            fetchItemCandidates(nextUnmatched)
          }, 300)
        }
      } else {
        toast.success("전체 매칭 완료!")
        setActiveItemIndex(null)
      }
    } catch {
      toast.error("매칭 확정에 실패했습니다")
    }
  }, [messageId, message, items, onRefresh, fetchItemCandidates])

  const undoItemMatch = useCallback(async (itemIndex: number) => {
    try {
      await fetchAPI(`/slack/messages/${messageId}/match/${itemIndex}`, {
        method: "DELETE",
      })
      toast.success("매칭이 취소되었습니다")
      onRefresh()
      setActiveItemIndex(null)
    } catch {
      toast.error("매칭 취소에 실패했습니다")
    }
  }, [messageId, onRefresh])

  useEffect(() => {
    fetchCandidates()
    setActiveItemIndex(null)
    setItemCandidates([])
    setSearchMode(false)
    setSearchQuery("")
    setSearchResults([])
    setSelectedSearchIds(new Set())
  }, [fetchCandidates])

  if (loading) return <CandidatePanelSkeleton />

  if (error) {
    return (
      <Card className="bg-card rounded-xl shadow">
        <CardContent className="p-6 flex flex-col items-center gap-3">
          <AlertCircle className="h-8 w-8 text-[hsl(var(--loss))]" />
          <p className="text-sm text-muted-foreground">{error}</p>
          <Button
            variant="secondary"
            size="sm"
            onClick={fetchCandidates}
            className="gap-1"
          >
            <RefreshCw className="h-3 w-3" />
            다시 시도
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="bg-card rounded-xl shadow">
      <CardContent className="p-4 space-y-3">
        <h3 className="text-sm font-semibold">매칭 후보</h3>

        {isMultiItem ? (
          <Tabs defaultValue="total">
            <TabsList className="w-full">
              <TabsTrigger value="total" className="flex-1">전체 매칭</TabsTrigger>
              <TabsTrigger value="items" className="flex-1">
                개별 매칭
                <Badge variant="secondary" className="ml-1.5 text-[10px] px-1.5">
                  {items.length}
                </Badge>
              </TabsTrigger>
            </TabsList>

            <TabsContent value="total" className="mt-3">
              {candidates.length === 0 ? (
                <p className="text-sm text-muted-foreground py-4 text-center">매칭 후보가 없습니다</p>
              ) : (
                <CandidatesList
                  candidates={candidates}
                  selectedId={selectedCandidateId}
                  onSelect={setSelectedCandidateId}
                  onConfirm={onConfirm}
                />
              )}
            </TabsContent>

            <TabsContent value="items" className="mt-3 space-y-3">
              {/* 항목 테이블 */}
              <div className="rounded-md border border-border overflow-hidden">
                {items.map((item, idx) => {
                  const match = message.item_matches?.find(m => m.item_index === idx)
                  const isActive = activeItemIndex === idx
                  const isConfirmed = match?.is_confirmed

                  return (
                    <div
                      key={idx}
                      role="option"
                      aria-selected={isActive}
                      aria-label={`${item.description} 항목, ${formatKRW(item.amount)}원, ${isConfirmed ? "확정" : "미매칭"}`}
                      className={cn(
                        "flex items-center justify-between px-3 py-2 cursor-pointer border-b border-border last:border-b-0 transition-colors",
                        isActive && "bg-yellow-500/10",
                        isConfirmed && "bg-emerald-500/10",
                        !isActive && !isConfirmed && "hover:bg-muted/50",
                      )}
                      onClick={() => {
                        if (!isConfirmed) {
                          setActiveItemIndex(idx)
                          fetchItemCandidates(idx)
                        }
                      }}
                    >
                      <div className="flex items-center gap-2">
                        {isActive && <span className="text-yellow-400 text-xs">&#9654;</span>}
                        {isConfirmed && <Check className="w-3.5 h-3.5 text-emerald-400" />}
                        <span className={cn("text-sm", isConfirmed && "text-emerald-400")}>
                          {item.description}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-mono">
                          {item.currency === "USD" ? (
                            <span className="flex flex-col items-end">
                              <span>${item.amount.toLocaleString()}</span>
                              {(item as Record<string, unknown>).amount_krw != null && (
                                <span className="text-[10px] text-muted-foreground">
                                  {formatKRW((item as Record<string, unknown>).amount_krw as number)}
                                </span>
                              )}
                            </span>
                          ) : formatKRW(item.amount)}
                        </span>
                        {isConfirmed ? (
                          <button
                            className="text-xs text-muted-foreground hover:text-red-400 transition-colors"
                            onClick={(e) => {
                              e.stopPropagation()
                              undoItemMatch(idx)
                            }}
                          >
                            취소
                          </button>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            {isActive ? "선택중" : "미매칭"}
                          </span>
                        )}
                      </div>
                    </div>
                  )
                })}
                {/* 합계 행 */}
                <div className="flex items-center justify-between px-3 py-2 bg-muted/30 text-sm">
                  <span className="font-medium">합계</span>
                  <div className="flex items-center gap-2">
                    <span className="font-mono">
                      {message.parsed_structured?.currency === "USD" ? (
                        <span className="flex flex-col items-end">
                          <span>${items.reduce((s, i) => s + (i.amount || 0), 0).toLocaleString()}</span>
                          {(message.parsed_structured as Record<string, unknown>)?.total_amount_krw != null && (
                            <span className="text-[10px] text-muted-foreground">
                              {formatKRW((message.parsed_structured as Record<string, unknown>).total_amount_krw as number)}
                            </span>
                          )}
                        </span>
                      ) : formatKRW(items.reduce((s, i) => s + (i.amount || 0), 0))}
                    </span>
                    {message.match_progress && (
                      <Badge variant="outline" className="text-[10px]">
                        {message.match_progress.matched_items}/{message.match_progress.total_items}
                      </Badge>
                    )}
                  </div>
                </div>
              </div>

              {/* 항목별 후보 리스트 */}
              {activeItemIndex !== null && (
                <div className="space-y-2">
                  <p className="text-xs text-muted-foreground">
                    &ldquo;{items[activeItemIndex]?.description}&rdquo; 후보
                  </p>
                  {itemCandidatesLoading ? (
                    <div className="space-y-2">
                      <Skeleton className="h-12 w-full" />
                      <Skeleton className="h-12 w-full" />
                      <Skeleton className="h-12 w-full" />
                    </div>
                  ) : itemCandidates.length === 0 ? (
                    <p className="text-sm text-muted-foreground py-4 text-center">
                      이 금액에 맞는 거래를 찾지 못했습니다
                    </p>
                  ) : (
                    <CandidatesList
                      candidates={itemCandidates}
                      selectedId={selectedItemCandidateId}
                      onSelect={setSelectedItemCandidateId}
                      onConfirm={(txId) => {
                        const item = items[activeItemIndex]
                        confirmItemMatch(txId, activeItemIndex, item.description)
                      }}
                    />
                  )}
                </div>
              )}
            </TabsContent>
          </Tabs>
        ) : (
          /* 단일 항목: 기존 후보 리스트 (탭 없음) */
          candidates.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-4">
              <Search className="h-8 w-8 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">매칭 후보가 없습니다.</p>
              <p className="text-xs text-muted-foreground">
                다른 메시지를 선택하거나 거래 데이터를 업로드해주세요.
              </p>
            </div>
          ) : (
            <CandidatesList
              candidates={candidates}
              selectedId={selectedCandidateId}
              onSelect={setSelectedCandidateId}
              onConfirm={onConfirm}
            />
          )
        )}

        {/* 직접 검색 */}
        <div className="pt-2 space-y-2">
          <Button
            size="sm"
            variant={searchMode ? "default" : "secondary"}
            onClick={() => { setSearchMode(!searchMode); setSearchResults([]); setSearchQuery("") }}
          >
            <Search className="h-3.5 w-3.5 mr-1" />
            직접 검색
          </Button>

          {searchMode && (
            <div className="space-y-2">
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="거래처명 또는 금액 (예: 쿠팡, 815960)"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") doSearch(searchQuery) }}
                  className="flex-1 h-8 rounded-md border border-white/[0.06] bg-secondary/30 px-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                />
                <Button size="sm" variant="secondary" onClick={() => doSearch(searchQuery)} disabled={searchLoading}>
                  {searchLoading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : "검색"}
                </Button>
              </div>
              <p className="text-[10px] text-muted-foreground">숫자만 입력하면 금액(±3%) 검색, 텍스트면 거래처/설명 검색</p>

              {searchResults.length > 0 && (
                <div className="space-y-1">
                  <div className="space-y-1 max-h-[400px] overflow-y-auto">
                    {searchResults.map((r) => {
                      const isChecked = selectedSearchIds.has(r.id)
                      return (
                        <div
                          key={r.id}
                          className={cn(
                            "rounded-lg border p-2 cursor-pointer transition-all text-sm",
                            isChecked
                              ? "border-[hsl(var(--accent))] bg-[hsl(var(--accent))]/5"
                              : "border-white/[0.04] hover:bg-secondary/30"
                          )}
                          onClick={() => toggleSearchSelection(r.id)}
                        >
                          <div className="flex items-center gap-2">
                            <div className={cn(
                              "h-4 w-4 rounded border shrink-0 flex items-center justify-center transition-colors",
                              isChecked
                                ? "bg-[hsl(var(--accent))] border-[hsl(var(--accent))]"
                                : "border-white/20"
                            )}>
                              {isChecked && <Check className="h-3 w-3 text-white" />}
                            </div>
                            <span className="text-xs text-muted-foreground">{formatDate(r.date)}</span>
                            {r.member_name && (
                              <span className={cn("inline-flex items-center rounded-md px-1 py-0 text-[10px] font-medium ring-1 ring-inset shrink-0", nameColor(r.member_name))}>
                                {r.member_name}
                              </span>
                            )}
                            <span className="truncate">{r.counterparty} {r.description}</span>
                            <span className="ml-auto font-mono font-semibold tabular-nums whitespace-nowrap">
                              {formatKRW(r.amount)}
                            </span>
                          </div>
                        </div>
                      )
                    })}
                  </div>

                  {/* 선택 합계 + 확정 버튼 */}
                  {selectedSearchIds.size > 0 && (
                    <div className="flex items-center justify-between rounded-lg border border-white/[0.06] bg-secondary/20 p-2">
                      <div className="text-xs">
                        <span className="text-muted-foreground">선택 {selectedSearchIds.size}건 합계: </span>
                        <span className="font-mono font-bold tabular-nums">{formatKRW(selectedSearchTotal)}</span>
                      </div>
                      <Button
                        size="sm"
                        className="h-7 px-3 bg-[hsl(var(--accent))] text-accent-foreground hover:bg-[hsl(var(--accent))]/90"
                        onClick={() => {
                          const ids = Array.from(selectedSearchIds)
                          if (activeItemIndex !== null) {
                            const item = items[activeItemIndex]
                            confirmItemMatch(ids.length === 1 ? ids[0] : ids, activeItemIndex, item.description)
                          } else if (ids.length === 1) {
                            onConfirm(ids[0])
                          } else {
                            onMultiConfirm(ids)
                          }
                        }}
                      >
                        <Check className="h-3.5 w-3.5 mr-1" />
                        {selectedSearchIds.size === 1 ? "확정" : `${selectedSearchIds.size}건 합산 확정`}
                      </Button>
                    </div>
                  )}
                </div>
              )}
              {!searchLoading && searchResults.length === 0 && searchQuery && (
                <p className="text-xs text-muted-foreground text-center py-2">검색 결과가 없습니다</p>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ── Main Content ───────────────────────────────────────

function SlackMatchContent() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity") || "1"

  const [messages, setMessages] = useState<SlackMessage[]>([])
  const [, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [selectedMessageId, setSelectedMessageId] = useState<number | null>(null)
  const [popupStyle, setPopupStyle] = useState<React.CSSProperties>({})
  const selectedRowRef = useRef<HTMLDivElement>(null)

  // 선택된 메시지의 위치에 맞춰 팝업 위치 업데이트
  useEffect(() => {
    if (selectedRowRef.current) {
      const rect = selectedRowRef.current.getBoundingClientRect()
      const vh = window.innerHeight
      const isLowerHalf = rect.top > vh * 0.45

      if (isLowerHalf) {
        // 화면 하반부: 팝업을 아래 기준으로 위로 자라게
        setPopupStyle({ bottom: `${Math.max(8, vh - rect.bottom)}px`, top: "auto", maxHeight: `${rect.bottom - 8}px` })
      } else {
        // 화면 상반부: 팝업을 위 기준으로 아래로 자라게
        setPopupStyle({ top: `${Math.max(8, rect.top)}px`, bottom: "auto", maxHeight: `${vh - rect.top - 8}px` })
      }
    }
  }, [selectedMessageId])
  const [monthlySummary, setMonthlySummary] = useState<MonthlySummary[]>([])
  const [expandedId, setExpandedId] = useState<number | null>(null)

  // Month navigation
  const [selectedMonth, setSelectedMonth] = useState<string>(() => {
    const now = new Date()
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
  })

  // Filters
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending")
  const [confidenceFilter, setConfidenceFilter] = useState<ConfidenceFilter>("all")

  const fetchMessages = useCallback(async (background = false) => {
    if (!background) setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        entity_id: entityId,
        page: String(page),
        per_page: "50",
        month: selectedMonth,
      })
      if (statusFilter === "pending") params.set("status", "pending")
      else if (statusFilter === "confirmed") params.set("status", "done")
      else if (statusFilter === "ignored") params.set("status", "cancelled")
      const data = await fetchAPI<SlackMessagesResponse>(
        `/slack/messages?${params.toString()}`,
      )
      setMessages(data.items)
      setTotal(data.total)
      setPages(data.pages)
      setMonthlySummary(data.monthly_summary || [])
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Slack 데이터를 불러올 수 없습니다.",
      )
    } finally {
      setLoading(false)
    }
  }, [entityId, page, selectedMonth, statusFilter])

  const [syncing, setSyncing] = useState(false)

  const handleSync = useCallback(async () => {
    setSyncing(true)
    try {
      const result = await fetchAPI<{ total_fetched: number; new: number; updated: number; skipped: number }>(
        `/slack/sync?channel=99-expenses&entity_id=${entityId}&year=2026`,
        { method: "POST" },
      )
      toast.success(`동기화 완료: 신규 ${result.new}건, 업데이트 ${result.updated}건`)
      fetchMessages(true)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "동기화에 실패했습니다")
    } finally {
      setSyncing(false)
    }
  }, [entityId, fetchMessages])

  useEffect(() => {
    fetchMessages()
  }, [fetchMessages])

  // Reset selection and page when entity changes
  useEffect(() => {
    setSelectedMessageId(null)
    setExpandedId(null)
    setPage(1)
    setMonthAutoSelected(false)
  }, [entityId])

  // Auto-select latest month with data if current month is empty
  const [monthAutoSelected, setMonthAutoSelected] = useState(false)
  useEffect(() => {
    if (monthAutoSelected) return
    if (monthlySummary.length > 0 && messages.length === 0 && !loading) {
      const sorted = [...monthlySummary].sort((a, b) =>
        a.yr !== b.yr ? b.yr - a.yr : b.mo - a.mo,
      )
      const latest = sorted[0]
      if (latest) {
        const key = `${latest.yr}-${String(latest.mo).padStart(2, "0")}`
        if (key !== selectedMonth) {
          setSelectedMonth(key)
          setMonthAutoSelected(true)
        }
      }
    }
  }, [monthlySummary, messages, loading, selectedMonth, monthAutoSelected])

  useEffect(() => {
    setPage(1)
    setSelectedMessageId(null)
    setExpandedId(null)
  }, [selectedMonth])

  // Filter messages client-side
  const filteredMessages = messages.filter((msg) => {
    // Status filter
    if (statusFilter !== "all") {
      const status = getMessageStatus(msg)
      if (statusFilter === "pending" && status !== "pending" && status !== "partial") return false
      if (statusFilter === "confirmed" && status !== "confirmed") return false
      if (statusFilter === "ignored" && status !== "ignored") return false
    }

    // Confidence filter
    if (confidenceFilter !== "all" && msg.match_confidence !== null) {
      const pct = msg.match_confidence * 100
      if (confidenceFilter === "high" && pct < 90) return false
      if (confidenceFilter === "medium" && (pct < 70 || pct >= 90)) return false
      if (confidenceFilter === "low" && pct >= 70) return false
    }

    return true
  })

  // KPI: 선택된 월의 summary
  const selectedSummary = monthlySummary.find((s) => {
    const key = `${s.yr}-${String(s.mo).padStart(2, "0")}`
    return key === selectedMonth
  })
  const kpiTotal = selectedSummary?.total ?? 0
  const kpiDone = selectedSummary?.done_count ?? 0
  const kpiPending = selectedSummary?.pending_count ?? 0
  const kpiCancelled = selectedSummary?.cancelled_count ?? 0

  // 매칭 확정 후 다음 미매칭 메시지 자동 선택
  const selectNextPending = useCallback((currentId: number) => {
    const currentIndex = filteredMessages.findIndex(m => m.id === currentId)
    // 현재 위치 이후의 pending 메시지 찾기
    for (let i = currentIndex + 1; i < filteredMessages.length; i++) {
      const status = getMessageStatus(filteredMessages[i])
      if (status === "pending" || status === "partial") {
        setSelectedMessageId(filteredMessages[i].id)
        setExpandedId(filteredMessages[i].id)
        return
      }
    }
    // 못 찾으면 이전 메시지에서 찾기
    for (let i = 0; i < currentIndex; i++) {
      const status = getMessageStatus(filteredMessages[i])
      if (status === "pending" || status === "partial") {
        setSelectedMessageId(filteredMessages[i].id)
        setExpandedId(filteredMessages[i].id)
        return
      }
    }
    setSelectedMessageId(null)
    setExpandedId(null)
  }, [filteredMessages])

  // Actions
  const handleConfirm = useCallback(
    async (messageId: number, transactionId: number) => {
      try {
        await fetchAPI(`/slack/messages/${messageId}/confirm`, {
          method: "POST",
          body: JSON.stringify({ transaction_id: transactionId }),
        })
        toast.success("매칭이 확정되었습니다.")
        selectNextPending(messageId)
        fetchMessages(true)
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : "매칭 확정에 실패했습니다.",
        )
      }
    },
    [fetchMessages, selectNextPending],
  )

  const handleMultiConfirm = useCallback(
    async (messageId: number, transactionIds: number[]) => {
      try {
        await fetchAPI(`/slack/messages/${messageId}/confirm`, {
          method: "POST",
          body: JSON.stringify({ transaction_ids: transactionIds }),
        })
        toast.success(`${transactionIds.length}건 합산 매칭이 확정되었습니다.`)
        selectNextPending(messageId)
        fetchMessages(true)
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : "매칭 확정에 실패했습니다.",
        )
      }
    },
    [fetchMessages, selectNextPending],
  )

  const handleIgnore = useCallback(
    async (messageId: number) => {
      const msg = messages.find(m => m.id === messageId)
      if (msg?.match_progress && msg.match_progress.matched_items > 0) {
        const confirmed = window.confirm(
          `${msg.match_progress.matched_items}개 항목이 매칭됨. 무시하면 매칭도 해제됩니다. 계속?`
        )
        if (!confirmed) return
      }

      try {
        await fetchAPI(`/slack/messages/${messageId}/ignore`, {
          method: "POST",
          body: JSON.stringify({}),
        })
        toast.success("메시지가 무시 처리되었습니다.")
        fetchMessages(true)
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : "무시 처리에 실패했습니다.",
        )
      }
    },
    [messages, fetchMessages],
  )

  const handleConfirmDirect = useCallback(
    (msg: SlackMessage) => {
      if (msg.matched_transaction_id) {
        handleConfirm(msg.id, msg.matched_transaction_id)
      }
    },
    [handleConfirm],
  )

  const handleToggleExpand = useCallback((id: number) => {
    setExpandedId((prev) => (prev === id ? null : id))
  }, [])

  const handleManualMatch = useCallback((id: number) => {
    setSelectedMessageId(id)
    setExpandedId(id)
  }, [])

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't intercept if user is in an input/select
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLSelectElement
      ) {
        return
      }

      if (e.key === "j" || e.key === "k") {
        e.preventDefault()
        const currentIndex = filteredMessages.findIndex(
          (m) => m.id === selectedMessageId,
        )

        if (e.key === "j") {
          const nextIndex = currentIndex < filteredMessages.length - 1
            ? currentIndex + 1
            : 0
          const nextId = filteredMessages[nextIndex]?.id ?? null
          setSelectedMessageId(nextId)
          setExpandedId(nextId)
        } else {
          const prevIndex = currentIndex > 0
            ? currentIndex - 1
            : filteredMessages.length - 1
          const prevId = filteredMessages[prevIndex]?.id ?? null
          setSelectedMessageId(prevId)
          setExpandedId(prevId)
        }
      }

      if (e.key === "i" && selectedMessageId !== null) {
        e.preventDefault()
        handleIgnore(selectedMessageId)
      }
    }

    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [filteredMessages, selectedMessageId, handleIgnore])

  const selectedMessage = messages.find((m) => m.id === selectedMessageId)

  // ── LOADING
  if (loading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-5 w-60" />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <MessageCardSkeleton key={i} />
            ))}
          </div>
          <CandidatePanelSkeleton />
        </div>
      </div>
    )
  }

  // ── ERROR
  if (error) {
    return (
      <div className="p-6 space-y-6">
        <h1 className="text-2xl font-semibold tracking-tight">Slack 매칭</h1>
        <Card className="bg-card rounded-xl p-8 shadow flex flex-col items-center justify-center text-center gap-4">
          <AlertCircle className="h-12 w-12 text-[hsl(var(--loss))]" />
          <p className="text-lg font-medium">
            Slack 데이터를 불러올 수 없습니다.
          </p>
          <p className="text-sm text-muted-foreground">{error}</p>
          <Button
            onClick={fetchMessages}
            variant="secondary"
            className="gap-2"
          >
            <RefreshCw className="h-4 w-4" />
            다시 시도
          </Button>
        </Card>
      </div>
    )
  }

  // ── EMPTY
  if (messages.length === 0) {
    return (
      <div className="p-6 space-y-6">
        <h1 className="text-2xl font-semibold tracking-tight">Slack 매칭</h1>
        <Card className="bg-card rounded-xl p-12 shadow flex flex-col items-center justify-center text-center gap-4">
          <MessageSquare className="h-12 w-12 text-muted-foreground" />
          <p className="text-lg font-medium">Slack 메시지가 없습니다</p>
          <p className="text-sm text-muted-foreground">
            Slack 동기화를 설정하면 경비 메시지가 자동으로 수집됩니다.
          </p>
          <Button onClick={handleSync} disabled={syncing} variant="outline" className="mt-4 gap-2">
            <RefreshCw className={cn("h-4 w-4", syncing && "animate-spin")} />
            {syncing ? "동기화 중..." : "Slack 동기화"}
          </Button>
        </Card>
      </div>
    )
  }

  // ── SUCCESS / PARTIAL
  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div className="flex items-center gap-4">
          <h1 className="text-2xl font-semibold tracking-tight">Slack 매칭</h1>
          <MonthPicker
            months={monthlySummary.map((s) =>
              `${s.yr}-${String(s.mo).padStart(2, "0")}`
            )}
            selected={selectedMonth}
            onSelect={setSelectedMonth}
          />
        </div>
        <Button onClick={handleSync} disabled={syncing} variant="outline" className="gap-2">
          <RefreshCw className={cn("h-4 w-4", syncing && "animate-spin")} />
          {syncing ? "동기화 중..." : "Slack 동기화"}
        </Button>
      </div>

      {/* KPI Cards */}
      <KPICards
        total={kpiTotal}
        doneCount={kpiDone}
        pendingCount={kpiPending}
        cancelledCount={kpiCancelled}
      />

      {/* Partial warning */}
      {kpiPending > 0 && (
        <div className="rounded-lg border border-[hsl(var(--warning))]/30 bg-[hsl(var(--warning))]/5 px-4 py-3">
          <p className="text-sm text-[hsl(var(--warning))]">
            {kpiPending}건의 매칭을 확인해주세요
          </p>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="w-[140px]">
          <Select
            value={statusFilter}
            onValueChange={(v) => { setStatusFilter(v as StatusFilter); setPage(1) }}
          >
            <SelectTrigger className="h-9 text-xs">
              <SelectValue placeholder="상태" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">전체</SelectItem>
              <SelectItem value="pending">미확정</SelectItem>
              <SelectItem value="confirmed">확정</SelectItem>
              <SelectItem value="ignored">무시</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="w-[160px]">
          <Select
            value={confidenceFilter}
            onValueChange={(v) => setConfidenceFilter(v as ConfidenceFilter)}
          >
            <SelectTrigger className="h-9 text-xs">
              <SelectValue placeholder="신뢰도" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">전체 신뢰도</SelectItem>
              <SelectItem value="high">높음 (90%+)</SelectItem>
              <SelectItem value="medium">중간 (70-89%)</SelectItem>
              <SelectItem value="low">낮음 (&lt;70%)</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Single column layout — popup on right */}
      <div className="relative lg:pr-[416px]">
        {/* Left: Message list — normal flow */}
        <div className="space-y-1 p-0.5" role="listbox" aria-label="Slack 메시지 목록">
          {filteredMessages.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 gap-2">
              <Search className="h-8 w-8 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                이 달에 메시지가 없습니다.
              </p>
            </div>
          ) : (
            filteredMessages.map((msg) => (
              <div key={msg.id} ref={selectedMessageId === msg.id ? selectedRowRef : undefined}>
              <CompactMessageRow
                message={msg}
                isSelected={selectedMessageId === msg.id}
                isExpanded={expandedId === msg.id}
                onSelect={() => setSelectedMessageId(msg.id)}
                onToggleExpand={() => handleToggleExpand(msg.id)}
                onConfirmDirect={() => handleConfirmDirect(msg)}
                onIgnore={() => handleIgnore(msg.id)}
                onManualMatch={() => handleManualMatch(msg.id)}
              />
              </div>
            ))
          )}

          {/* Pagination */}
          {pages > 1 && (
            <div className="flex items-center justify-center gap-2 pt-4">
              <Button
                variant="ghost"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="text-sm text-muted-foreground">
                {page} / {pages}
              </span>
              <Button
                variant="ghost"
                size="sm"
                disabled={page >= pages}
                onClick={() => setPage((p) => Math.min(pages, p + 1))}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          )}
        </div>

        {/* Right: Candidate popup — appears at selected message position */}
        {selectedMessageId !== null && selectedMessage && (
        <div
          className="hidden lg:block fixed right-4 w-[400px] overflow-y-auto z-10 scrollbar-thin rounded-xl border border-white/[0.06] shadow-lg bg-card/95 backdrop-blur-xl transition-all duration-150 ease-out"
          style={popupStyle}
        >
          {(getMessageStatus(selectedMessage) === "pending" || getMessageStatus(selectedMessage) === "partial") ? (
            <CandidatePanel
              messageId={selectedMessageId}
              message={selectedMessage}
              entityId={entityId}
              onConfirm={(txId) => handleConfirm(selectedMessageId, txId)}
              onMultiConfirm={(txIds) => handleMultiConfirm(selectedMessageId, txIds)}
              onRefresh={() => fetchMessages(true)}
            />
          ) : (
            <div className="p-4 text-center text-sm text-muted-foreground">
              이미 처리된 메시지입니다.
            </div>
          )}
        </div>
        )}
      </div>
    </div>
  )
}

// ── Page Export ─────────────────────────────────────────

export default function SlackMatchPage() {
  return (
    <div>
      <Suspense
        fallback={
          <div className="flex gap-1 border-b border-border">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-10 w-32 animate-pulse rounded-t bg-muted"
              />
            ))}
          </div>
        }
      >
        <EntityTabs />
      </Suspense>
      <Suspense
        fallback={
          <div className="p-6 space-y-6">
            <Skeleton className="h-8 w-40" />
            <Skeleton className="h-5 w-60" />
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-20 rounded-xl" />
              ))}
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <MessageCardSkeleton key={i} />
                ))}
              </div>
              <CandidatePanelSkeleton />
            </div>
          </div>
        }
      >
        <SlackMatchContent />
      </Suspense>
    </div>
  )
}
