"use client"

import { useEffect, useState, useCallback } from "react"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { fetchAPI } from "@/lib/api"
import { formatByEntity } from "@/lib/format"
import { AlertCircle, RefreshCw, Upload, ChevronDown, ChevronUp, Download, Settings } from "lucide-react"
import Link from "next/link"
import { cn } from "@/lib/utils"

// ── Types ──────────────────────────────────────────────

interface CardTransaction {
  id: number
  date: string
  type: string
  amount: number
  description: string
  counterparty: string | null
  account_name: string | null
  account_code: string | null
}

interface CardMember {
  member_id: number | null
  member_name: string | null
  subtotal: number
  refund: number
  net: number
  tx_count: number
  transactions: CardTransaction[]
}

interface AccountBreakdown {
  account_name: string
  amount: number
  tx_count: number
}

interface CardGroup {
  source_type: string
  total_expense: number
  total_refund: number
  net: number
  tx_count: number
  members: CardMember[]
  account_breakdown: AccountBreakdown[]
}

interface ExpenseData {
  year: number
  month: number
  entity_id: number
  groups: CardGroup[]
  total_expense: number
  total_refund: number
  total_net: number
  prev_month_net: number
  change_pct: number | null
}

interface SummaryData {
  available_months: string[]
}

type LoadState = "loading" | "empty" | "error" | "success"

const SOURCE_LABELS: Record<string, string> = {
  lotte_card: "롯데카드",
  woori_card: "우리카드",
}

const ACCOUNT_BADGE_COLORS: Record<string, string> = {
  SaaS: "bg-cyan-500/12 text-cyan-400",
  교통비: "bg-blue-500/12 text-blue-400",
  수수료: "bg-purple-500/12 text-purple-400",
  접대비: "bg-amber-500/12 text-amber-400",
  복리후생: "bg-green-500/12 text-green-400",
}

function getAccountBadgeClass(name: string): string {
  return ACCOUNT_BADGE_COLORS[name] || "bg-gray-500/15 text-gray-400"
}

// ── Month Nav ──────────────────────────────────────────

function MonthNav({
  months,
  selected,
  onSelect,
}: {
  months: string[]
  selected: string
  onSelect: (m: string) => void
}) {
  const idx = months.indexOf(selected)
  return (
    <div className="flex items-center gap-2">
      <Button variant="ghost" size="sm" disabled={idx <= 0} onClick={() => onSelect(months[idx - 1])} className="h-8 w-8 p-0">◀</Button>
      <div className="flex items-center gap-1.5 overflow-x-auto">
        {months.map((m) => (
          <button
            key={m}
            onClick={() => onSelect(m)}
            className={cn(
              "px-3 py-1 rounded-full text-xs font-medium transition-colors whitespace-nowrap",
              m === selected
                ? "bg-[#8B5CF6] text-white"
                : "bg-muted/30 text-muted-foreground hover:bg-muted/50",
            )}
          >
            {`${parseInt(m.slice(5))}월`}
          </button>
        ))}
      </div>
      <Button variant="ghost" size="sm" disabled={idx >= months.length - 1} onClick={() => onSelect(months[idx + 1])} className="h-8 w-8 p-0">▶</Button>
    </div>
  )
}

// ── KPI Card ───────────────────────────────────────────

function KPICard({ label, value, subtext, colorClass }: {
  label: string; value: string; subtext?: string; colorClass?: string
}) {
  return (
    <Card className="bg-secondary rounded-xl p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("text-2xl font-bold font-mono tabular-nums mt-1", colorClass)}>{value}</p>
      {subtext && <p className="text-xs text-muted-foreground mt-0.5">{subtext}</p>}
    </Card>
  )
}

// ── Member Accordion ───────────────────────────────────

function MemberAccordion({ member, entityId }: { member: CardMember; entityId: string | null }) {
  const [expanded, setExpanded] = useState(false)
  const displayName = member.member_name || "(미지정)"
  const preview = member.transactions.slice(0, 3)
  const remaining = member.transactions.length - 3

  return (
    <div className="border-t border-border">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-muted/10 transition-colors"
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm">{displayName}</span>
          <span className="text-xs text-muted-foreground">{member.tx_count}건</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="font-mono tabular-nums text-sm text-[hsl(var(--loss))]">
            {formatByEntity(member.net, entityId)}
          </span>
          {expanded ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
        </div>
      </button>
      {expanded && (
        <div className="bg-muted/5 px-4 pb-3">
          <table className="w-full text-xs">
            <tbody>
              {member.transactions.map((tx) => (
                <tr key={tx.id} className="border-t border-border/50">
                  <td className="py-1.5 pl-4 w-16 font-mono text-muted-foreground">{tx.date.slice(5)}</td>
                  <td className="py-1.5">
                    <div className="flex items-center gap-2">
                      {tx.account_name && (
                        <Badge variant="outline" className={cn("text-[10px] px-1.5 py-0", getAccountBadgeClass(tx.account_name))}>
                          {tx.account_name}
                        </Badge>
                      )}
                      <span className="truncate">{tx.description || tx.counterparty}</span>
                    </div>
                  </td>
                  <td className={cn(
                    "py-1.5 text-right font-mono tabular-nums pr-4",
                    tx.type === "in" ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]",
                  )}>
                    {tx.type === "in" ? "+" : "-"}{formatByEntity(tx.amount, entityId)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2 pt-2 border-t border-border/50 flex justify-between text-xs px-4">
            <span className="text-muted-foreground">
              소계: {formatByEntity(member.subtotal, entityId)} / 환불 {formatByEntity(member.refund, entityId)}
            </span>
            <span className="font-medium">순 {formatByEntity(member.net, entityId)}</span>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Component ──────────────────────────────────────────

export function ExpenseTab({ entityId }: { entityId: string | null }) {
  const [data, setData] = useState<ExpenseData | null>(null)
  const [summary, setSummary] = useState<SummaryData | null>(null)
  const [state, setState] = useState<LoadState>("loading")
  const [error, setError] = useState("")
  const [selectedMonth, setSelectedMonth] = useState("")

  const fetchSummary = useCallback(async () => {
    if (!entityId) return
    try {
      const s = await fetchAPI<SummaryData>(
        `/cashflow/summary?entity_id=${entityId}&months=12`,
        { cache: "no-store" },
      )
      setSummary(s)
      if (s.available_months.length && !selectedMonth) {
        setSelectedMonth(s.available_months[s.available_months.length - 1])
      }
    } catch { /* optional */ }
  }, [entityId]) // eslint-disable-line react-hooks/exhaustive-deps

  const fetchExpense = useCallback(async () => {
    if (!entityId || !selectedMonth) return
    setState("loading")
    const [y, m] = selectedMonth.split("-").map(Number)
    try {
      const d = await fetchAPI<ExpenseData>(
        `/cashflow/card-expense?entity_id=${entityId}&year=${y}&month=${m}`,
        { cache: "no-store" },
      )
      setData(d)
      setState(d.groups.length === 0 ? "empty" : "success")
    } catch (err) {
      setError(err instanceof Error ? err.message : "데이터를 불러올 수 없습니다.")
      setState("error")
    }
  }, [entityId, selectedMonth])

  useEffect(() => { fetchSummary() }, [fetchSummary])
  useEffect(() => { fetchExpense() }, [fetchExpense])

  const months = summary?.available_months ?? []

  // ── LOADING ──
  if (state === "loading" || !selectedMonth) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-3 gap-3">
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}
        </div>
        <Skeleton className="h-[300px] rounded-xl" />
      </div>
    )
  }

  // ── ERROR ──
  if (state === "error") {
    return (
      <Card className="p-8 flex flex-col items-center text-center gap-4">
        <AlertCircle className="h-12 w-12 text-[hsl(var(--loss))]" />
        <p className="font-medium">데이터를 불러올 수 없습니다.</p>
        <p className="text-sm text-muted-foreground">{error}</p>
        <Button onClick={fetchExpense} variant="secondary" className="gap-2">
          <RefreshCw className="h-4 w-4" /> 다시 시도
        </Button>
      </Card>
    )
  }

  // ── EMPTY ──
  if (state === "empty") {
    return (
      <div className="space-y-6">
        <MonthNav months={months} selected={selectedMonth} onSelect={setSelectedMonth} />
        <Card className="p-12 flex flex-col items-center text-center gap-4">
          <Upload className="h-12 w-12 text-muted-foreground" />
          <p className="text-lg font-medium">카드 거래 데이터가 없습니다</p>
          <p className="text-sm text-muted-foreground">카드 사용 내역 Excel을 업로드해주세요.</p>
          <Button asChild className="bg-[hsl(var(--accent))] text-accent-foreground hover:bg-[hsl(var(--accent))]/90 gap-2">
            <Link href="/upload"><Upload className="h-4 w-4" /> Excel 업로드</Link>
          </Button>
        </Card>
      </div>
    )
  }

  if (!data) return null
  const m = parseInt(selectedMonth.slice(5))

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <MonthNav months={months} selected={selectedMonth} onSelect={setSelectedMonth} />
          <p className="text-xs text-muted-foreground mt-1">
            {m}월 카드 사용 → <span className="text-[hsl(var(--warning))]">{m + 1 > 12 ? 1 : m + 1}월</span> 결제 예정
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="gap-2">
            <Settings className="h-4 w-4" /> 카드 설정
          </Button>
          <Button variant="outline" size="sm" className="gap-2">
            <Download className="h-4 w-4" /> 내보내기
          </Button>
        </div>
      </div>

      {/* KPI */}
      <div className="grid grid-cols-3 gap-3 max-md:grid-cols-2 max-sm:grid-cols-1">
        <KPICard
          label="총 지출"
          value={formatByEntity(data.total_expense, entityId)}
          subtext={`${data.groups.reduce((s, g) => s + g.tx_count, 0)}건`}
          colorClass="text-[hsl(var(--loss))]"
        />
        <KPICard
          label="환불"
          value={formatByEntity(data.total_refund, entityId)}
          colorClass="text-[hsl(var(--profit))]"
        />
        <KPICard
          label="순 사용"
          value={formatByEntity(data.total_net, entityId)}
          colorClass="text-[#8B5CF6]"
        />
      </div>

      {/* Card groups (accordion) */}
      {data.groups.map((group) => (
        <Card key={group.source_type} className="overflow-hidden">
          <div className="px-4 py-3 flex items-center justify-between bg-muted/20">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="bg-purple-500/12 text-purple-400 text-xs">
                {SOURCE_LABELS[group.source_type] || group.source_type}
              </Badge>
              <span className="text-xs text-muted-foreground">{group.tx_count}건</span>
            </div>
            <span className="font-mono tabular-nums text-sm font-medium text-[#8B5CF6]">
              순 {formatByEntity(group.net, entityId)}
            </span>
          </div>
          {group.members.map((member, i) => (
            <MemberAccordion key={member.member_id ?? `none-${i}`} member={member} entityId={entityId} />
          ))}
        </Card>
      ))}

      {/* Total */}
      {data.groups.length > 1 && (
        <div className="flex justify-end px-4">
          <span className="text-sm font-medium">
            합계: <span className="font-mono tabular-nums text-[#8B5CF6]">{formatByEntity(data.total_net, entityId)}</span>
          </span>
        </div>
      )}

      {/* Comparison boxes */}
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        {/* Account breakdown */}
        <Card className="bg-secondary rounded-xl p-4">
          <h4 className="text-xs font-semibold text-cyan-400 mb-3">내부 계정별 ({m}월)</h4>
          <div className="space-y-2 text-sm">
            {data.groups.flatMap((g) => g.account_breakdown).reduce<AccountBreakdown[]>((acc, item) => {
              const existing = acc.find((a) => a.account_name === item.account_name)
              if (existing) {
                existing.amount += item.amount
                existing.tx_count += item.tx_count
              } else {
                acc.push({ ...item })
              }
              return acc
            }, []).sort((a, b) => b.amount - a.amount).map((item) => (
              <div key={item.account_name} className="flex justify-between items-center">
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className={cn("text-[10px] px-1.5 py-0", getAccountBadgeClass(item.account_name))}>
                    {item.account_name}
                  </Badge>
                </div>
                <span className="font-mono tabular-nums">{formatByEntity(item.amount, entityId)}</span>
              </div>
            ))}
            <div className="border-t border-border pt-2 flex justify-between font-medium">
              <span>합계</span>
              <span className="font-mono tabular-nums">{formatByEntity(data.total_net, entityId)}</span>
            </div>
          </div>
        </Card>

        {/* Month-over-month */}
        <Card className="bg-secondary rounded-xl p-4">
          <h4 className="text-xs font-semibold text-[hsl(var(--warning))] mb-3">월별 비교</h4>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">{m - 1 || 12}월</span>
              <span className="font-mono tabular-nums">{formatByEntity(data.prev_month_net, entityId)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">{m}월</span>
              <span className="font-mono tabular-nums">{formatByEntity(data.total_net, entityId)}</span>
            </div>
            <div className="border-t border-border pt-2 flex justify-between font-medium">
              <span>변동</span>
              <span className={cn(
                "font-mono tabular-nums",
                data.change_pct != null && data.change_pct <= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]",
              )}>
                {data.change_pct != null ? `${data.change_pct > 0 ? "+" : ""}${data.change_pct}%` : "—"}
              </span>
            </div>
            {data.change_pct != null && data.change_pct < 0 && (
              <p className="text-xs text-[hsl(var(--profit))]">(비용 감소)</p>
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}
