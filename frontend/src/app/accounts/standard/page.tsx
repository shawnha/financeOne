"use client"

import { Suspense, useCallback, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { fetchAPI } from "@/lib/api"
import { EntityTabs } from "@/components/entity-tabs"
import { AccountCombobox } from "@/components/account-combobox"
import { toast } from "sonner"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { BookOpen, Search } from "lucide-react"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface StandardAccount {
  id: number
  code: string
  name: string
  category: string
  subcategory: string
  normal_side: string
  sort_order: number
  mapped_internal_id?: number | null
  mapped_internal_name?: string | null
  mapped_internal_code?: string | null
}

const CATEGORY_ORDER = ["자산", "부채", "자본", "수익", "비용"] as const

const CATEGORY_COLORS: Record<string, string> = {
  자산: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  부채: "bg-red-500/15 text-red-400 border-red-500/30",
  자본: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  수익: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  비용: "bg-purple-500/15 text-purple-400 border-purple-500/30",
}

// ---------------------------------------------------------------------------
// Content Component
// ---------------------------------------------------------------------------

function StandardAccountsContent() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity_id")

  const [accounts, setAccounts] = useState<StandardAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")
  const [internalAccounts, setInternalAccounts] = useState<{ id: number; code: string; name: string; parent_id: number | null }[]>([])

  useEffect(() => {
    if (entityId) {
      fetchAPI<{ id: number; code: string; name: string; parent_id: number | null }[]>(
        `/accounts/internal?entity_id=${entityId}`
      ).then(setInternalAccounts).catch(() => {})
    }
  }, [entityId])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const url = entityId
        ? `/accounts/standard?entity_id=${entityId}`
        : "/accounts/standard"
      const data = await fetchAPI<StandardAccount[]>(url)
      setAccounts(data)
    } catch {
      toast.error("표준 계정과목을 불러오지 못했습니다")
    } finally {
      setLoading(false)
    }
  }, [entityId])

  useEffect(() => {
    load()
  }, [load])

  const handleMappingChange = async (
    standardAccountId: number,
    internalAccountId: number | null,
    previousInternalId: number | null,
  ) => {
    try {
      if (previousInternalId) {
        await fetchAPI(`/accounts/internal/${previousInternalId}`, {
          method: "PATCH",
          body: JSON.stringify({ standard_account_id: null }),
        })
      }
      if (internalAccountId) {
        await fetchAPI(`/accounts/internal/${internalAccountId}`, {
          method: "PATCH",
          body: JSON.stringify({ standard_account_id: standardAccountId }),
        })
      }
      toast.success("매핑이 업데이트되었습니다")
      load()
    } catch {
      toast.error("매핑 변경에 실패했습니다")
    }
  }

  // Filter by search query
  const filtered = useMemo(() => {
    if (!search.trim()) return accounts
    const q = search.trim().toLowerCase()
    return accounts.filter(
      (a) =>
        a.code.toLowerCase().includes(q) ||
        a.name.toLowerCase().includes(q),
    )
  }, [accounts, search])

  // Group by category
  const grouped = useMemo(() => {
    const map = new Map<string, StandardAccount[]>()
    for (const a of filtered) {
      const list = map.get(a.category) || []
      list.push(a)
      map.set(a.category, list)
    }
    // Return in canonical order
    const result: { category: string; items: StandardAccount[] }[] = []
    for (const cat of CATEGORY_ORDER) {
      const items = map.get(cat)
      if (items && items.length > 0) {
        result.push({ category: cat, items })
      }
    }
    // Append any categories not in CATEGORY_ORDER
    for (const [cat, items] of Array.from(map.entries())) {
      if (!CATEGORY_ORDER.includes(cat as (typeof CATEGORY_ORDER)[number])) {
        result.push({ category: cat, items })
      }
    }
    return result
  }, [filtered])

  // Loading state
  if (loading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-48" />
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-4">
        <CardTitle className="text-base font-medium">
          K-GAAP 표준 계정과목 ({accounts.length}건)
        </CardTitle>
        <div className="relative w-72">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="코드 또는 계정명 검색..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
      </CardHeader>
      <CardContent>
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
            <BookOpen className="mb-3 h-10 w-10 opacity-40" />
            {search.trim() ? (
              <>
                <p className="text-sm">
                  &quot;{search.trim()}&quot;에 대한 검색 결과가 없습니다
                </p>
                <p className="mt-1 text-xs">다른 검색어를 입력해보세요.</p>
              </>
            ) : (
              <p className="text-sm">등록된 표준 계정과목이 없습니다</p>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-[100px]">코드</TableHead>
                  <TableHead>계정명</TableHead>
                  <TableHead className="w-[120px]">분류</TableHead>
                  <TableHead className="w-[140px]">세부분류</TableHead>
                  <TableHead className="w-[100px]">차변/대변</TableHead>
                  <TableHead className="w-[180px]">내부계정</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {grouped.map(({ category, items }) => (
                  <>
                    {/* Category section header */}
                    <TableRow
                      key={`header-${category}`}
                      className="hover:bg-transparent border-t-2 border-border/60"
                    >
                      <TableCell
                        colSpan={6}
                        className="bg-muted/40 py-2.5"
                      >
                        <div className="flex items-center gap-2">
                          <Badge
                            variant="outline"
                            className={CATEGORY_COLORS[category] || ""}
                          >
                            {category}
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            {items.length}개
                          </span>
                        </div>
                      </TableCell>
                    </TableRow>
                    {/* Account rows */}
                    {items.map((account) => (
                      <TableRow key={account.id}>
                        <TableCell className="font-mono text-sm">
                          {account.code}
                        </TableCell>
                        <TableCell className="font-medium">
                          {account.name}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={`font-normal ${CATEGORY_COLORS[account.category] || ""}`}
                          >
                            {account.category}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {account.subcategory || "-"}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={
                              account.normal_side === "debit"
                                ? "bg-blue-500/15 text-blue-400 border-blue-500/30"
                                : "bg-red-500/15 text-red-400 border-red-500/30"
                            }
                          >
                            {account.normal_side === "debit" ? "차변" : "대변"}
                          </Badge>
                        </TableCell>
                        <TableCell onClick={(e) => e.stopPropagation()}>
                          {entityId ? (
                            <AccountCombobox
                              options={internalAccounts}
                              value={account.mapped_internal_id ? String(account.mapped_internal_id) : ""}
                              onChange={(v) => {
                                handleMappingChange(
                                  account.id,
                                  v ? Number(v) : null,
                                  account.mapped_internal_id ?? null,
                                )
                              }}
                              placeholder="매핑 선택"
                              compact
                            />
                          ) : (
                            <span className="text-xs text-muted-foreground">법인 선택 필요</span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Page Header (uses useSearchParams, must be wrapped in Suspense)
// ---------------------------------------------------------------------------

function PageHeader() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity_id")

  return (
    <div className="flex items-center gap-2">
      <BookOpen className="h-6 w-6 text-muted-foreground" />
      <h1 className="text-2xl font-semibold tracking-tight text-foreground">
        표준 계정과목
      </h1>
      <Badge variant="secondary" className="ml-2 text-xs">
        K-GAAP
      </Badge>
      {!entityId && (
        <Badge variant="outline" className="text-xs text-muted-foreground">
          읽기 전용
        </Badge>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function StandardAccountsPage() {
  return (
    <div className="space-y-6">
      <Suspense fallback={<Skeleton className="h-10 w-full border-b" />}>
        <EntityTabs />
      </Suspense>

      <Suspense fallback={
        <div className="flex items-center gap-2">
          <BookOpen className="h-6 w-6 text-muted-foreground" />
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            표준 계정과목
          </h1>
          <Badge variant="secondary" className="ml-2 text-xs">K-GAAP</Badge>
        </div>
      }>
        <PageHeader />
      </Suspense>

      <Suspense fallback={<Skeleton className="h-64 w-full" />}>
        <StandardAccountsContent />
      </Suspense>
    </div>
  )
}
