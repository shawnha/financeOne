"use client"

import { useState, useEffect, useCallback, Suspense } from "react"
import { useSearchParams, useRouter, usePathname } from "next/navigation"
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
import { BookOpen, RefreshCw } from "lucide-react"

interface StandardAccount {
  id: number
  code: string
  name: string
  category: string
  subcategory: string | null
  normal_side: "debit" | "credit"
}

interface LedgerLine {
  journal_entry_id: number
  entry_date: string
  entry_description: string | null
  debit: number
  credit: number
  line_description: string | null
  running_balance: number
  transaction_id: number | null
  counterparty: string | null
  source_type: string | null
}

interface LedgerResponse {
  account: StandardAccount
  entity_id: number
  start_date: string | null
  end_date: string | null
  opening_balance: number
  lines: LedgerLine[]
  summary: {
    total_debit: number
    total_credit: number
    net_change: number
    ending_balance: number
    line_count: number
  }
  pagination: { page: number; per_page: number; total: number; pages: number }
}

interface Entity {
  id: number
  code: string
  name: string
  currency: string
}

const currentYear = new Date().getFullYear()
const YEARS = Array.from({ length: 5 }, (_, i) => currentYear - i)
const MONTH_OPTIONS = [
  { value: "all", label: "전체" },
  ...Array.from({ length: 12 }, (_, i) => ({ value: String(i + 1), label: `${i + 1}월` })),
]

function LedgerContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const entityId = searchParams.get("entity") || "1"
  const initialCode = searchParams.get("code") || ""

  const [accounts, setAccounts] = useState<StandardAccount[]>([])
  const [selectedCode, setSelectedCode] = useState(initialCode)
  const [year, setYear] = useState(currentYear.toString())
  const [month, setMonth] = useState("all")
  const [data, setData] = useState<LedgerResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [entities, setEntities] = useState<Entity[]>([])

  const currentEntity = entities.find((e) => e.id === Number(entityId))
  const currency = currentEntity?.currency || "KRW"
  const formatMoney = (n: number) =>
    currency === "USD" ? formatUSD(n) : formatKRW(n)

  // Load entities + standard accounts
  useEffect(() => {
    fetchAPI<Entity[]>("/entities").then(setEntities).catch(() => {})
    fetchAPI<StandardAccount[]>("/accounts/standard")
      .then((rows) => setAccounts(Array.isArray(rows) ? rows : []))
      .catch(() => setAccounts([]))
  }, [])

  // Load ledger for selected account
  const loadLedger = useCallback(async () => {
    if (!selectedCode) {
      setData(null)
      return
    }
    setLoading(true)
    try {
      const params = new URLSearchParams({
        entity_id: entityId,
        per_page: "500",
      })
      if (month !== "all") {
        const m = Number(month)
        const startDate = `${year}-${String(m).padStart(2, "0")}-01`
        const lastDay = new Date(Number(year), m, 0).getDate()
        const endDate = `${year}-${String(m).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`
        params.set("start_date", startDate)
        params.set("end_date", endDate)
      } else {
        params.set("start_date", `${year}-01-01`)
        params.set("end_date", `${year}-12-31`)
      }
      const result = await fetchAPI<LedgerResponse>(
        `/accounts/${selectedCode}/ledger?${params.toString()}`,
      )
      setData(result)
    } catch (e) {
      console.error(e)
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [selectedCode, entityId, year, month])

  useEffect(() => {
    loadLedger()
  }, [loadLedger])

  // Sync selected code to URL (for bookmarking + cross-page jumps)
  useEffect(() => {
    if (selectedCode && selectedCode !== initialCode) {
      const params = new URLSearchParams(searchParams.toString())
      params.set("code", selectedCode)
      router.replace(`${pathname}?${params.toString()}`, { scroll: false })
    }
  }, [selectedCode]) // eslint-disable-line react-hooks/exhaustive-deps

  // Group accounts by category for dropdown
  const grouped: Record<string, StandardAccount[]> = {}
  for (const a of accounts) {
    const cat = a.category || "기타"
    grouped[cat] = grouped[cat] || []
    grouped[cat].push(a)
  }

  return (
    <div className="p-6 space-y-6">
      <Suspense fallback={<Skeleton className="h-10 w-full border-b" />}>
        <EntityTabs />
      </Suspense>

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">계정별 원장</h1>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <Select value={selectedCode} onValueChange={setSelectedCode}>
          <SelectTrigger className="w-[260px]">
            <SelectValue placeholder="계정 선택" />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(grouped).map(([cat, accts]) => (
              <div key={cat}>
                <div className="px-2 py-1 text-xs text-muted-foreground font-semibold">{cat}</div>
                {accts.map((a) => (
                  <SelectItem key={a.code} value={a.code}>
                    {a.code} {a.name}
                  </SelectItem>
                ))}
              </div>
            ))}
          </SelectContent>
        </Select>

        <Select value={year} onValueChange={setYear}>
          <SelectTrigger className="w-[120px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {YEARS.map((y) => (
              <SelectItem key={y} value={y.toString()}>{y}년</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={month} onValueChange={setMonth}>
          <SelectTrigger className="w-[120px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {MONTH_OPTIONS.map((m) => (
              <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button variant="outline" size="sm" onClick={loadLedger} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          새로고침
        </Button>
      </div>

      {/* Empty state */}
      {!selectedCode && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <BookOpen className="h-12 w-12 text-muted-foreground" />
            <h3 className="mt-4 text-lg font-semibold text-foreground">계정을 선택하세요</h3>
            <p className="mt-2 text-sm text-muted-foreground max-w-md">
              상단 드롭다운에서 계정을 선택하면 해당 계정의 모든 분개 history 가 표시됩니다.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Ledger table */}
      {selectedCode && data && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">
              {data.account.code} {data.account.name}
              <span className="ml-2 text-sm text-muted-foreground">
                ({data.account.category} / {data.account.subcategory || "-"})
              </span>
            </CardTitle>
            <div className="flex flex-wrap gap-4 text-sm text-muted-foreground mt-2">
              <span>기초잔액: <span className="font-mono text-foreground">{formatMoney(data.opening_balance)}</span></span>
              <span>차변합: <span className="font-mono text-foreground">{formatMoney(data.summary.total_debit)}</span></span>
              <span>대변합: <span className="font-mono text-foreground">{formatMoney(data.summary.total_credit)}</span></span>
              <span>기말잔액: <span className="font-mono text-foreground font-semibold">{formatMoney(data.summary.ending_balance)}</span></span>
              <span>{data.summary.line_count}건</span>
            </div>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[100px]">날짜</TableHead>
                    <TableHead>적요</TableHead>
                    <TableHead>거래처</TableHead>
                    <TableHead className="text-right w-[120px]">차변</TableHead>
                    <TableHead className="text-right w-[120px]">대변</TableHead>
                    <TableHead className="text-right w-[140px]">잔액</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.lines.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                        해당 기간에 거래가 없습니다
                      </TableCell>
                    </TableRow>
                  ) : (
                    data.lines.map((line, idx) => (
                      <TableRow key={`${line.journal_entry_id}_${idx}`}>
                        <TableCell className="font-mono text-xs">{line.entry_date}</TableCell>
                        <TableCell>{line.line_description || line.entry_description || "-"}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {line.counterparty || ""}
                          {line.source_type && (
                            <span className="ml-1 text-[10px] uppercase">{line.source_type}</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right font-mono tabular-nums">
                          {line.debit !== 0 ? formatMoney(line.debit) : ""}
                        </TableCell>
                        <TableCell className="text-right font-mono tabular-nums">
                          {line.credit !== 0 ? formatMoney(line.credit) : ""}
                        </TableCell>
                        <TableCell className="text-right font-mono tabular-nums">
                          {formatMoney(line.running_balance)}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      {selectedCode && loading && !data && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
          </CardContent>
        </Card>
      )}
    </div>
  )
}

export default function LedgerPage() {
  return (
    <Suspense fallback={<div className="p-6"><Skeleton className="h-32 w-full" /></div>}>
      <LedgerContent />
    </Suspense>
  )
}
