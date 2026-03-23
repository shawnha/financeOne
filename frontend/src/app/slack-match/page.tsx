"use client"

import { useState, useCallback, useEffect, Suspense } from "react"
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
import { EntityTabs } from "@/components/entity-tabs"
import { fetchAPI } from "@/lib/api"
import { formatKRW } from "@/lib/format"
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
} from "lucide-react"

// ── Types ──────────────────────────────────────────────

interface SlackMessage {
  id: number
  entity_id: number
  channel_name: string
  sender_name: string
  message_text: string
  parsed_amount: number | null
  parsed_currency: string | null
  message_date: string
  is_completed: boolean
  is_cancelled: boolean
  match_id: number | null
  match_transaction_id: number | null
  match_confidence: number | null
}

interface SlackMessagesResponse {
  items: SlackMessage[]
  total: number
  page: number
  pages: number
}

interface MatchCandidate {
  id: number
  date: string
  description: string
  amount: number
  counterparty: string
  confidence: number
  match_reason: string
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

function getMessageStatus(msg: SlackMessage): "confirmed" | "ignored" | "pending" {
  if (msg.is_completed && msg.match_transaction_id) return "confirmed"
  if (msg.is_cancelled) return "ignored"
  return "pending"
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
  })
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

// ── Message Card ───────────────────────────────────────

function MessageCard({
  message,
  isSelected,
  onSelect,
  onConfirmDirect,
  onIgnore,
}: {
  message: SlackMessage
  isSelected: boolean
  onSelect: () => void
  onConfirmDirect: () => void
  onIgnore: () => void
}) {
  const status = getMessageStatus(message)

  return (
    <Card
      className={`bg-card rounded-xl shadow cursor-pointer transition-all ${
        isSelected ? "ring-2 ring-[hsl(var(--accent))]" : "hover:bg-secondary/30"
      }`}
      onClick={onSelect}
      role="option"
      aria-selected={isSelected}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter") onSelect()
      }}
    >
      <CardContent className="p-4 space-y-2">
        {/* Header: channel, sender, date */}
        <div className="flex items-center gap-2 text-xs flex-wrap">
          <Badge
            variant="outline"
            className="bg-[#6366F1]/20 text-[#6366F1] border-[#6366F1]/30 text-[11px] px-1.5 py-0"
          >
            #{message.channel_name}
          </Badge>
          <span className="text-muted-foreground">{message.sender_name}</span>
          <span className="text-muted-foreground">&middot;</span>
          <span className="text-muted-foreground">
            {new Date(message.message_date).toLocaleDateString("ko-KR")}
          </span>
        </div>

        {/* Message text */}
        <p className="text-sm leading-relaxed">{message.message_text}</p>

        {/* Amount */}
        {message.parsed_amount !== null && (
          <p className="text-xl font-mono font-bold tabular-nums">
            {message.parsed_currency === "USD"
              ? `$${message.parsed_amount.toLocaleString()}`
              : formatKRW(message.parsed_amount)}
          </p>
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

        {/* Actions */}
        {status === "pending" && (
          <div className="flex gap-2 pt-1" onClick={(e) => e.stopPropagation()}>
            {message.match_transaction_id && (
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
              onClick={onSelect}
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
      </CardContent>
    </Card>
  )
}

// ── Candidate Panel ────────────────────────────────────

function CandidatePanel({
  messageId,
  onConfirm,
}: {
  messageId: number
  onConfirm: (transactionId: number) => void
}) {
  const [candidates, setCandidates] = useState<MatchCandidate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedCandidateId, setSelectedCandidateId] = useState<number | null>(null)

  const fetchCandidates = useCallback(async () => {
    setLoading(true)
    setError(null)
    setSelectedCandidateId(null)
    try {
      const data = await fetchAPI<CandidatesResponse>(
        `/slack/messages/${messageId}/candidates`,
      )
      setCandidates(data.candidates)
      // Auto-select first candidate
      if (data.candidates.length > 0) {
        setSelectedCandidateId(data.candidates[0].id)
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "후보를 불러올 수 없습니다.",
      )
    } finally {
      setLoading(false)
    }
  }, [messageId])

  useEffect(() => {
    fetchCandidates()
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

  if (candidates.length === 0) {
    return (
      <Card className="bg-card rounded-xl shadow">
        <CardContent className="p-6 flex flex-col items-center gap-2">
          <Search className="h-8 w-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            매칭 후보가 없습니다.
          </p>
          <p className="text-xs text-muted-foreground">
            다른 메시지를 선택하거나 거래 데이터를 업로드해주세요.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="bg-card rounded-xl shadow">
      <CardContent className="p-4 space-y-3">
        <h3 className="text-sm font-semibold">매칭 후보</h3>

        <div className="space-y-1" role="radiogroup" aria-label="매칭 후보 목록">
          {candidates.map((candidate) => {
            const isSelected = selectedCandidateId === candidate.id

            return (
              <button
                key={candidate.id}
                role="radio"
                aria-checked={isSelected}
                onClick={() => setSelectedCandidateId(candidate.id)}
                className={`w-full text-left rounded-lg p-3 transition-colors border ${
                  isSelected
                    ? "border-[hsl(var(--accent))] bg-[hsl(var(--accent))]/5"
                    : "border-transparent hover:bg-secondary/30"
                }`}
              >
                <div className="flex items-start gap-3">
                  {/* Radio indicator */}
                  <div
                    className={`mt-0.5 h-4 w-4 rounded-full border-2 flex items-center justify-center shrink-0 ${
                      isSelected
                        ? "border-[hsl(var(--accent))]"
                        : "border-muted-foreground/40"
                    }`}
                  >
                    {isSelected && (
                      <div className="h-2 w-2 rounded-full bg-[hsl(var(--accent))]" />
                    )}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 text-sm">
                      <span className="text-muted-foreground">
                        {formatDate(candidate.date)}
                      </span>
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
                    <p className="text-xs text-muted-foreground mt-1">
                      매칭 근거: {candidate.match_reason}
                    </p>
                  </div>
                </div>
              </button>
            )
          })}
        </div>

        {/* Actions */}
        <div className="flex gap-2 pt-2">
          <Button
            size="sm"
            className="bg-[hsl(var(--accent))] text-accent-foreground hover:bg-[hsl(var(--accent))]/90"
            disabled={selectedCandidateId === null}
            onClick={() => {
              if (selectedCandidateId !== null) {
                onConfirm(selectedCandidateId)
              }
            }}
          >
            <Check className="h-3.5 w-3.5 mr-1" />
            선택 확정
          </Button>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button size="sm" variant="secondary" disabled>
                  <Search className="h-3.5 w-3.5 mr-1" />
                  직접 검색
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>Phase 2에서 구현</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
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

  // Filters
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all")
  const [confidenceFilter, setConfidenceFilter] = useState<ConfidenceFilter>("all")

  const fetchMessages = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchAPI<SlackMessagesResponse>(
        `/slack/messages?entity_id=${entityId}&page=${page}&per_page=20`,
      )
      setMessages(data.items)
      setTotal(data.total)
      setPages(data.pages)
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Slack 데이터를 불러올 수 없습니다.",
      )
    } finally {
      setLoading(false)
    }
  }, [entityId, page])

  useEffect(() => {
    fetchMessages()
  }, [fetchMessages])

  // Reset selection and page when entity changes
  useEffect(() => {
    setSelectedMessageId(null)
    setPage(1)
  }, [entityId])

  // Filter messages client-side
  const filteredMessages = messages.filter((msg) => {
    // Status filter
    if (statusFilter !== "all") {
      const status = getMessageStatus(msg)
      if (statusFilter === "pending" && status !== "pending") return false
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

  // Counts
  const pendingCount = messages.filter((m) => getMessageStatus(m) === "pending").length
  const confirmedCount = messages.filter((m) => getMessageStatus(m) === "confirmed").length

  // Actions
  const handleConfirm = useCallback(
    async (messageId: number, transactionId: number) => {
      try {
        await fetchAPI(`/slack/messages/${messageId}/confirm`, {
          method: "POST",
          body: JSON.stringify({ transaction_id: transactionId }),
        })
        toast.success("매칭이 확정되었습니다.")
        fetchMessages()
        setSelectedMessageId(null)
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : "매칭 확정에 실패했습니다.",
        )
      }
    },
    [fetchMessages],
  )

  const handleIgnore = useCallback(
    async (messageId: number) => {
      try {
        await fetchAPI(`/slack/messages/${messageId}/ignore`, {
          method: "POST",
        })
        toast.success("메시지가 무시 처리되었습니다.")
        fetchMessages()
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : "무시 처리에 실패했습니다.",
        )
      }
    },
    [fetchMessages],
  )

  const handleConfirmDirect = useCallback(
    (msg: SlackMessage) => {
      if (msg.match_transaction_id) {
        handleConfirm(msg.id, msg.match_transaction_id)
      }
    },
    [handleConfirm],
  )

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
          setSelectedMessageId(filteredMessages[nextIndex]?.id ?? null)
        } else {
          const prevIndex = currentIndex > 0
            ? currentIndex - 1
            : filteredMessages.length - 1
          setSelectedMessageId(filteredMessages[prevIndex]?.id ?? null)
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
        </Card>
      </div>
    )
  }

  // ── SUCCESS / PARTIAL
  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Slack 매칭</h1>
          <div className="flex items-center gap-3 mt-1 text-sm">
            <span>
              미확정{" "}
              <span className="text-[hsl(var(--warning))] font-medium">
                {pendingCount}건
              </span>
            </span>
            <span className="text-muted-foreground">&middot;</span>
            <span>
              확정{" "}
              <span className="text-[hsl(var(--profit))] font-medium">
                {confirmedCount}건
              </span>
            </span>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          마지막 동기화: 방금 전
        </p>
      </div>

      {/* Partial warning */}
      {pendingCount > 0 && (
        <div className="rounded-lg border border-[hsl(var(--warning))]/30 bg-[hsl(var(--warning))]/5 px-4 py-3">
          <p className="text-sm text-[hsl(var(--warning))]">
            {pendingCount}건의 매칭을 확인해주세요
          </p>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="w-[140px]">
          <Select
            value={statusFilter}
            onValueChange={(v) => setStatusFilter(v as StatusFilter)}
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

      {/* Two-panel layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: Message list */}
        <div className="space-y-3" role="listbox" aria-label="Slack 메시지 목록">
          {filteredMessages.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 gap-2">
              <Search className="h-8 w-8 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                필터 조건에 맞는 메시지가 없습니다.
              </p>
            </div>
          ) : (
            filteredMessages.map((msg) => (
              <MessageCard
                key={msg.id}
                message={msg}
                isSelected={selectedMessageId === msg.id}
                onSelect={() => setSelectedMessageId(msg.id)}
                onConfirmDirect={() => handleConfirmDirect(msg)}
                onIgnore={() => handleIgnore(msg.id)}
              />
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

        {/* Right: Candidate panel */}
        <div className="lg:sticky lg:top-6 lg:self-start">
          {selectedMessageId !== null &&
          selectedMessage &&
          getMessageStatus(selectedMessage) === "pending" ? (
            <CandidatePanel
              messageId={selectedMessageId}
              onConfirm={(txId) => handleConfirm(selectedMessageId, txId)}
            />
          ) : (
            <Card className="bg-card rounded-xl shadow">
              <CardContent className="p-8 flex flex-col items-center justify-center text-center gap-2">
                <Search className="h-8 w-8 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">
                  {selectedMessage && getMessageStatus(selectedMessage) !== "pending"
                    ? "이미 처리된 메시지입니다."
                    : "왼쪽에서 메시지를 선택하면 매칭 후보가 표시됩니다."}
                </p>
                <p className="text-xs text-muted-foreground">
                  j/k 키로 이동, Enter로 확정, i로 무시
                </p>
              </CardContent>
            </Card>
          )}
        </div>
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
