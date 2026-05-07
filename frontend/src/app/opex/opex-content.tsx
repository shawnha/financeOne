"use client"

import { useEffect, useState, useCallback, useMemo } from "react"
import { useSearchParams } from "next/navigation"
import Link from "next/link"
import {
  Bar,
  BarChart,
  XAxis,
  YAxis,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
} from "recharts"
import { AlertCircle, RefreshCw, Upload, ChevronDown, ChevronUp, Wallet, TrendingDown, TrendingUp } from "lucide-react"

import { useGlobalMonth } from "@/hooks/use-global-month"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { fetchAPI } from "@/lib/api"
import { formatByEntity, abbreviateAmount } from "@/lib/format"
import { cn } from "@/lib/utils"
import { MonthPicker } from "@/components/month-picker"

// ── Types ──────────────────────────────────────────────

interface SummaryMonth {
  month: string
  expense: number
  tx_count: number
}

interface SummaryData {
  months: SummaryMonth[]
  available_months: string[]
}

interface BreakdownItem {
  parent_name?: string
  std_code?: string
  std_name?: string
  amount: number
  tx_count: number
}

interface OpexTx {
  id: number
  date: string
  amount: number
  description: string
  counterparty?: string | null
  source_type?: string | null
  transfer_memo?: string | null
  internal_account_name?: string | null
  parent_account_name?: string | null
  std_code?: string | null
  std_name?: string | null
}

interface DetailData {
  year: number
  month: number
  total: number
  tx_count: number
  prev_total: number
  change_pct: number | null
  yoy_total: number
  yoy_pct: number | null
  std_breakdown: BreakdownItem[]
  parent_breakdown: BreakdownItem[]
  transactions: OpexTx[]
}

type LoadState = "loading" | "empty" | "error" | "success"

// ── KPI Card ───────────────────────────────────────────

function KPICard({
  label,
  value,
  subtext,
  colorClass,
  subtextColor,
  icon: Icon,
}: {
  label: string
  value: string
  subtext?: string
  colorClass?: string
  subtextColor?: string
  icon?: typeof Wallet
}) {
  return (
    <Card className="bg-secondary rounded-xl p-4">
      <div className="flex items-center justify-between">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
        {Icon && <Icon className="h-3.5 w-3.5 text-muted-foreground/60" />}
      </div>
      <p className={cn("text-lg md:text-xl lg:text-[28px] font-bold font-mono tabular-nums mt-1 truncate", colorClass)}>
        {value}
      </p>
      {subtext && <p className={cn("text-[11px] mt-0.5", subtextColor || "text-muted-foreground")}>{subtext}</p>}
    </Card>
  )
}

// ── Component ──────────────────────────────────────────

export function OpexContent() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity")

  const [summary, setSummary] = useState<SummaryData | null>(null)
  const [detail, setDetail] = useState<DetailData | null>(null)
  const [state, setState] = useState<LoadState>("loading")
  const [detailState, setDetailState] = useState<LoadState>("loading")
  const [error, setError] = useState("")
  const [globalMonth, setGlobalMonth] = useGlobalMonth()
  const [selectedMonth, setSelectedMonthLocal] = useState(globalMonth)
  const setSelectedMonth = useCallback(
    (m: string) => {
      setSelectedMonthLocal(m)
      setGlobalMonth(m)
    },
    [setGlobalMonth],
  )
  const [expandedParents, setExpandedParents] = useState<Set<string>>(new Set())
  const [expandedInternals, setExpandedInternals] = useState<Set<string>>(new Set())

  useEffect(() => setSelectedMonthLocal(globalMonth), [globalMonth])

  const fetchSummary = useCallback(async () => {
    if (!entityId) return
    setState("loading")
    try {
      const data = await fetchAPI<SummaryData>(
        `/opex/summary?entity_id=${entityId}&months=12`,
        { cache: "no-store" },
      )
      setSummary(data)
      if (!data.available_months.length) {
        setState("empty")
        return
      }
      setState("success")
      if (!selectedMonth || !data.available_months.includes(selectedMonth)) {
        setSelectedMonth(data.available_months[data.available_months.length - 1])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "데이터를 불러올 수 없습니다.")
      setState("error")
    }
  }, [entityId]) // eslint-disable-line react-hooks/exhaustive-deps

  const fetchDetail = useCallback(async () => {
    if (!entityId || !selectedMonth) return
    setDetailState("loading")
    const [y, m] = selectedMonth.split("-").map(Number)
    try {
      const data = await fetchAPI<DetailData>(
        `/opex/detail?entity_id=${entityId}&year=${y}&month=${m}`,
        { cache: "no-store" },
      )
      setDetail(data)
      setDetailState(data.tx_count === 0 ? "empty" : "success")
    } catch {
      setDetailState("error")
    }
  }, [entityId, selectedMonth])

  useEffect(() => {
    fetchSummary()
  }, [fetchSummary])
  useEffect(() => {
    fetchDetail()
  }, [fetchDetail])

  const toggleParent = (name: string) => {
    setExpandedParents((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }
  const toggleInternal = (key: string) => {
    setExpandedInternals((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // Group tx: parent_account_name → internal_account_name → tx[]
  type InternalGroup = { internalName: string; rows: OpexTx[]; total: number }
  const txByParent = useMemo(() => {
    if (!detail) return new Map<string, InternalGroup[]>()
    const parentMap = new Map<string, Map<string, OpexTx[]>>()
    for (const tx of detail.transactions) {
      const parentKey = tx.parent_account_name || tx.internal_account_name || "미분류"
      const internalKey = tx.internal_account_name || tx.parent_account_name || "미분류"
      if (!parentMap.has(parentKey)) parentMap.set(parentKey, new Map())
      const inner = parentMap.get(parentKey)!
      if (!inner.has(internalKey)) inner.set(internalKey, [])
      inner.get(internalKey)!.push(tx)
    }
    const result = new Map<string, InternalGroup[]>()
    parentMap.forEach((inner, parentKey) => {
      const groups: InternalGroup[] = []
      inner.forEach((rows, internalName) => {
        const total = rows.reduce((s, r) => s + r.amount, 0)
        groups.push({ internalName, rows, total })
      })
      groups.sort((a, b) => b.total - a.total)
      result.set(parentKey, groups)
    })
    return result
  }, [detail])

  // ── Entity 미선택 가드 ──
  if (!entityId) {
    return (
      <div className="p-6">
        <Skeleton className="h-[260px] w-full rounded-xl" />
      </div>
    )
  }

  // ── LOADING ──
  if (state === "loading") {
    return (
      <div className="p-6 space-y-6">
        <div className="grid grid-cols-4 gap-3 max-md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-[260px] w-full rounded-xl" />
        <Skeleton className="h-[200px] w-full rounded-xl" />
      </div>
    )
  }

  // ── ERROR ──
  if (state === "error") {
    return (
      <div className="p-6">
        <Card className="p-8 flex flex-col items-center justify-center text-center gap-4">
          <AlertCircle className="h-12 w-12 text-[hsl(var(--loss))]" />
          <p className="text-lg font-medium">데이터를 불러올 수 없습니다.</p>
          <p className="text-sm text-muted-foreground">{error}</p>
          <Button onClick={fetchSummary} variant="secondary" className="gap-2">
            <RefreshCw className="h-4 w-4" /> 다시 시도
          </Button>
        </Card>
      </div>
    )
  }

  // ── EMPTY ──
  if (state === "empty" || !summary) {
    return (
      <div className="p-6">
        <Card className="p-12 flex flex-col items-center justify-center text-center gap-4">
          <Wallet className="h-12 w-12 text-muted-foreground" />
          <p className="text-lg font-medium">해당 법인에 OpEx 거래가 없습니다.</p>
          <p className="text-sm text-muted-foreground">
            거래에 SG&amp;A 계정(판매관리비)이 매핑되면 자동으로 표시됩니다.
            <br />
            (HOI는 US-GAAP — 추후 지원 예정)
          </p>
          <Button asChild variant="secondary" className="gap-2">
            <Link href="/upload">
              <Upload className="h-4 w-4" /> 거래 업로드
            </Link>
          </Button>
        </Card>
      </div>
    )
  }

  // ── SUCCESS ──
  const months = summary.available_months
  const chartData = summary.months.map((m) => ({
    ...m,
    isSelected: m.month === selectedMonth,
  }))

  const totalsSum = summary.months.reduce((s, m) => s + m.expense, 0)
  const avg = summary.months.length > 0 ? totalsSum / summary.months.length : 0

  const current = detail?.total ?? 0
  const prev = detail?.prev_total ?? 0
  const txCount = detail?.tx_count ?? 0
  const changePct = detail?.change_pct
  const yoyPct = detail?.yoy_pct

  const maxBreakdownAmount = detail?.parent_breakdown[0]?.amount || 1

  return (
    <div className="p-6 space-y-6">
      {/* Header: 페이지 제목 + 월 picker */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Wallet className="h-5 w-5 text-[hsl(var(--accent))]" />
            OpEx (SG&amp;A)
          </h1>
          <p className="text-xs text-muted-foreground mt-1">
            판매관리비 — 매출원가 / 외상매입금 결제 / 자산취득 / 영업외비용 제외
          </p>
        </div>
        <MonthPicker
          months={months}
          selected={selectedMonth}
          onSelect={setSelectedMonth}
          accentColor="hsl(var(--accent))"
        />
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-3 max-md:grid-cols-2">
        <KPICard
          label="이번달 OpEx"
          value={formatByEntity(current, entityId)}
          subtext={`${txCount}건`}
          colorClass="text-foreground"
          icon={Wallet}
        />
        <KPICard
          label="전월 OpEx"
          value={formatByEntity(prev, entityId)}
          subtext={
            changePct == null
              ? "-"
              : `${changePct >= 0 ? "+" : ""}${changePct.toFixed(1)}% 전월대비`
          }
          subtextColor={
            changePct == null
              ? "text-muted-foreground"
              : changePct < 0
                ? "text-[hsl(var(--profit))]"
                : "text-[hsl(var(--loss))]"
          }
          icon={changePct != null && changePct < 0 ? TrendingDown : TrendingUp}
        />
        <KPICard
          label="전년 동월"
          value={formatByEntity(detail?.yoy_total ?? 0, entityId)}
          subtext={
            yoyPct == null
              ? "전년 동월 데이터 없음"
              : `${yoyPct >= 0 ? "+" : ""}${yoyPct.toFixed(1)}% YoY`
          }
          subtextColor={
            yoyPct == null
              ? "text-muted-foreground"
              : yoyPct < 0
                ? "text-[hsl(var(--profit))]"
                : "text-[hsl(var(--loss))]"
          }
        />
        <KPICard
          label={`최근 ${summary.months.length}개월 평균`}
          value={formatByEntity(avg, entityId)}
          subtext={
            current > 0 && avg > 0
              ? `이번달 ${current > avg ? "+" : ""}${(((current - avg) / avg) * 100).toFixed(0)}% vs 평균`
              : undefined
          }
          subtextColor={
            current > avg ? "text-[hsl(var(--loss))]" : "text-[hsl(var(--profit))]"
          }
        />
      </div>

      {/* Monthly Chart */}
      <Card className="p-6 rounded-2xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-muted-foreground">
            월별 OpEx 추이 ({summary.months.length}개월)
          </h3>
        </div>
        <div className="h-[220px] max-md:h-[180px]">
          <ResponsiveContainer width="100%" height="100%" minWidth={0}>
            <BarChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 5 }}>
              <defs>
                <linearGradient id="opexBarGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity={0.65} />
                  <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="4 4" stroke="rgba(255,255,255,0.03)" vertical={false} />
              <XAxis
                dataKey="month"
                tick={(props: Record<string, unknown>) => {
                  const x = Number(props.x ?? 0)
                  const y = Number(props.y ?? 0)
                  const value = String((props.payload as Record<string, unknown>)?.value ?? "")
                  const isActive = value === selectedMonth
                  return (
                    <text
                      x={x}
                      y={y + 12}
                      textAnchor="middle"
                      fill={isActive ? "hsl(var(--accent))" : "#64748b"}
                      fontSize={11}
                      fontWeight={isActive ? 600 : 400}
                    >
                      {`${parseInt(value.slice(5))}월`}
                    </text>
                  )
                }}
                axisLine={{ stroke: "rgba(255,255,255,0.06)" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: "#64748b", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v) => abbreviateAmount(v)}
                width={55}
              />
              <RechartsTooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null
                  const p = payload[0]
                  const data = p.payload as SummaryMonth
                  return (
                    <div className="rounded-lg bg-popover border border-border px-3 py-2 shadow-lg text-sm">
                      <p className="text-muted-foreground mb-1">{label}</p>
                      <p className="font-mono tabular-nums" style={{ color: "hsl(var(--accent))" }}>
                        {formatByEntity(Number(p.value), entityId)}
                      </p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">{data.tx_count}건</p>
                    </div>
                  )
                }}
              />
              <Bar dataKey="expense" radius={[6, 6, 0, 0]} animationDuration={300} barSize={26}>
                {chartData.map((entry, i) => (
                  <Cell
                    key={`opex-${i}`}
                    fill="url(#opexBarGrad)"
                    stroke="hsl(var(--accent))"
                    strokeWidth={entry.isSelected ? 1 : 0.5}
                    opacity={entry.isSelected ? 1 : 0.4}
                    cursor="pointer"
                    onClick={() => setSelectedMonth(entry.month)}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* Breakdown + Tx List */}
      {detailState === "loading" ? (
        <Skeleton className="h-[300px] w-full rounded-2xl" />
      ) : detailState === "empty" ? (
        <Card className="p-8 text-center text-sm text-muted-foreground rounded-2xl">
          이번 달 OpEx 거래가 없습니다.
        </Card>
      ) : detail ? (
        <Card className="overflow-hidden rounded-2xl">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <h3 className="text-base font-semibold">
              {parseInt(selectedMonth.slice(5))}월 OpEx — 카테고리별
            </h3>
            <span className="text-xs text-muted-foreground">
              {detail.tx_count}건 / {formatByEntity(detail.total, entityId)}
            </span>
          </div>

          {/* Parent breakdown — clickable to expand transactions */}
          <div>
            {detail.parent_breakdown.map((item) => {
              const name = item.parent_name || "미분류"
              const expanded = expandedParents.has(name)
              const txs = txByParent.get(name) || []
              const pct = (item.amount / detail.total) * 100
              const isUnmapped = name === "미분류"
              return (
                <div key={name}>
                  <button
                    onClick={() => toggleParent(name)}
                    className={cn(
                      "w-full grid grid-cols-[1fr_minmax(0,2fr)_140px_60px] items-center gap-3 px-4 py-3 border-t border-border/50 text-left hover:bg-white/[0.02] transition-colors",
                      isUnmapped && "bg-amber-500/[0.03]",
                    )}
                    aria-expanded={expanded}
                  >
                    <span className="flex items-center gap-2 min-w-0">
                      {expanded ? (
                        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
                      ) : (
                        <ChevronUp className="h-3.5 w-3.5 text-muted-foreground rotate-90 flex-shrink-0" />
                      )}
                      <span
                        className={cn(
                          "font-medium truncate",
                          isUnmapped && "text-amber-400",
                        )}
                      >
                        {name}
                      </span>
                    </span>
                    {/* Bar */}
                    <div className="h-1.5 bg-white/[0.04] rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${(item.amount / maxBreakdownAmount) * 100}%`,
                          background:
                            "linear-gradient(90deg, hsl(var(--accent) / 0.5), hsl(var(--accent) / 0.9))",
                        }}
                      />
                    </div>
                    <span className="text-right font-mono tabular-nums text-sm text-foreground">
                      {formatByEntity(item.amount, entityId)}
                    </span>
                    <span className="text-right font-mono tabular-nums text-xs text-muted-foreground">
                      {pct.toFixed(1)}%
                    </span>
                  </button>

                  {/* Drilldown — internal sub-groups → transactions */}
                  {expanded && (
                    <div className="bg-black/[0.08] border-t border-border/30">
                      {(txByParent.get(name) || []).map((g) => {
                        const internalKey = `${name}::${g.internalName}`
                        const internalOpen = expandedInternals.has(internalKey)
                        const internalGroups = txByParent.get(name) || []
                        const directRender =
                          internalGroups.length === 1 && g.internalName === name

                        // Single internal matching parent — skip header, show tx directly
                        if (directRender) {
                          return (
                            <div key={internalKey}>
                              <div className="grid grid-cols-[80px_1fr_140px] px-4 py-2 pl-10 text-[10px] uppercase tracking-wider text-muted-foreground/70 font-semibold">
                                <span>날짜</span>
                                <span>거래</span>
                                <span className="text-right">금액</span>
                              </div>
                              {g.rows.map((tx) => (
                                <div
                                  key={tx.id}
                                  className="grid grid-cols-[80px_1fr_140px] px-4 py-1.5 pl-10 border-t border-border/20 text-[12px]"
                                >
                                  <span className="font-mono text-muted-foreground">
                                    {tx.date.slice(5)}
                                  </span>
                                  <span className="truncate text-muted-foreground" title={tx.transfer_memo ? `${tx.description}\n메모: ${tx.transfer_memo}` : tx.description}>
                                    {tx.description}
                                    {tx.counterparty && (
                                      <span className="text-muted-foreground/50 ml-1.5">
                                        · {tx.counterparty}
                                      </span>
                                    )}
                                    {tx.transfer_memo && (
                                      <span className="ml-1.5 text-[10px] text-blue-300/80 bg-blue-500/10 rounded px-1 py-0.5">
                                        {tx.transfer_memo.length > 16 ? tx.transfer_memo.slice(0, 16) + "…" : tx.transfer_memo}
                                      </span>
                                    )}
                                  </span>
                                  <span className="text-right font-mono tabular-nums text-[hsl(var(--loss))]">
                                    -{formatByEntity(tx.amount, entityId)}
                                  </span>
                                </div>
                              ))}
                            </div>
                          )
                        }

                        // Internal sub-group with toggle
                        return (
                          <div key={internalKey}>
                            <button
                              onClick={() => toggleInternal(internalKey)}
                              className="w-full grid grid-cols-[1fr_140px_60px] items-center gap-3 px-4 py-2 pl-10 border-t border-border/30 text-left hover:bg-white/[0.02] transition-colors text-[13px]"
                              aria-expanded={internalOpen}
                            >
                              <span className="flex items-center gap-2 min-w-0">
                                {internalOpen ? (
                                  <ChevronDown className="h-3 w-3 text-muted-foreground flex-shrink-0" />
                                ) : (
                                  <ChevronUp className="h-3 w-3 text-muted-foreground rotate-90 flex-shrink-0" />
                                )}
                                <span className="text-muted-foreground truncate">
                                  {g.internalName}
                                </span>
                              </span>
                              <span className="text-right font-mono tabular-nums text-xs text-foreground/80">
                                -{formatByEntity(g.total, entityId)}
                              </span>
                              <span className="text-right font-mono tabular-nums text-xs text-muted-foreground">
                                {g.rows.length}건
                              </span>
                            </button>

                            {internalOpen && (
                              <div className="bg-black/[0.12]">
                                <div className="grid grid-cols-[80px_1fr_140px] px-4 py-1.5 pl-16 text-[10px] uppercase tracking-wider text-muted-foreground/60 font-semibold">
                                  <span>날짜</span>
                                  <span>거래</span>
                                  <span className="text-right">금액</span>
                                </div>
                                {g.rows.map((tx) => (
                                  <div
                                    key={tx.id}
                                    className="grid grid-cols-[80px_1fr_140px] px-4 py-1.5 pl-16 border-t border-border/15 text-[12px]"
                                  >
                                    <span className="font-mono text-muted-foreground">
                                      {tx.date.slice(5)}
                                    </span>
                                    <span className="truncate text-muted-foreground" title={tx.transfer_memo ? `${tx.description}\n메모: ${tx.transfer_memo}` : tx.description}>
                                      {tx.description}
                                      {tx.counterparty && (
                                        <span className="text-muted-foreground/50 ml-1.5">
                                          · {tx.counterparty}
                                        </span>
                                      )}
                                      {tx.transfer_memo && (
                                        <span className="ml-1.5 text-[10px] text-blue-300/80 bg-blue-500/10 rounded px-1 py-0.5">
                                          {tx.transfer_memo.length > 16 ? tx.transfer_memo.slice(0, 16) + "…" : tx.transfer_memo}
                                        </span>
                                      )}
                                    </span>
                                    <span className="text-right font-mono tabular-nums text-[hsl(var(--loss))]">
                                      -{formatByEntity(tx.amount, entityId)}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </Card>
      ) : null}
    </div>
  )
}
