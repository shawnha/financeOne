"use client"

import { useCallback, useEffect, useState } from "react"
import { useSearchParams } from "next/navigation"
import { fetchAPI } from "@/lib/api"
import { AccountCombobox } from "@/components/account-combobox"
import { cn } from "@/lib/utils"
import { EntityTabs } from "@/components/entity-tabs"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Trash2, Search, Link2 } from "lucide-react"

type MappingRule = {
  id: number
  counterparty_pattern: string
  internal_account_id: number | null
  internal_account_name: string | null
  internal_account_code: string | null
  standard_account_id: number | null
  standard_account_name: string | null
  standard_account_code: string | null
  confidence: number
  hit_count: number
  updated_at: string
}

type InternalAccount = {
  id: number
  code: string
  name: string
  parent_id: number | null
  parent_name: string | null
}

export default function MappingRulesPage() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity") || "2"

  const [rules, setRules] = useState<MappingRule[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [internalAccounts, setInternalAccounts] = useState<InternalAccount[]>([])
  const [editingId, setEditingId] = useState<number | null>(null)

  const perPage = 50

  const fetchRules = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ entity_id: entityId, page: String(page), per_page: String(perPage) })
      if (search) params.set("search", search)
      const data = await fetchAPI(`/accounts/mapping-rules?${params}`)
      setRules(data.items)
      setTotal(data.total)
    } catch (e) {
      setError(e instanceof Error ? e.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [entityId, page, search])

  const fetchAccounts = useCallback(async () => {
    try {
      const data = await fetchAPI(`/accounts/internal?entity_id=${entityId}`)
      setInternalAccounts(Array.isArray(data) ? data : data.items || [])
    } catch {}
  }, [entityId])

  useEffect(() => { fetchRules() }, [fetchRules])
  useEffect(() => { fetchAccounts() }, [fetchAccounts])
  useEffect(() => { setPage(1) }, [entityId, search])

  const handleUpdateAccount = useCallback(async (ruleId: number, internalAccountId: string) => {
    setEditingId(null)
    try {
      await fetchAPI(`/accounts/mapping-rules/${ruleId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ internal_account_id: Number(internalAccountId) }),
      })
      fetchRules()
    } catch {}
  }, [fetchRules])

  const handleDelete = useCallback(async (ruleId: number) => {
    try {
      await fetchAPI(`/accounts/mapping-rules/${ruleId}`, { method: "DELETE" })
      fetchRules()
    } catch {}
  }, [fetchRules])

  const totalPages = Math.ceil(total / perPage)

  return (
    <div className="space-y-6">
      <EntityTabs />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">매핑 규칙</h1>
          <p className="text-sm text-muted-foreground mt-1">
            거래처 → 내부계정 자동 매핑 규칙 ({total}건)
          </p>
        </div>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="거래처 검색..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-8 text-center text-muted-foreground">로딩 중...</div>
          ) : error ? (
            <div className="p-8 text-center text-destructive">{error}</div>
          ) : rules.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">
              <Link2 className="h-8 w-8 mx-auto mb-3 opacity-40" />
              <p>매핑 규칙이 없습니다</p>
              <p className="text-xs mt-1">거래내역에서 계정을 선택하면 자동으로 학습됩니다</p>
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[300px]">거래처</TableHead>
                    <TableHead className="w-[200px]">내부계정</TableHead>
                    <TableHead className="w-[160px]">표준계정</TableHead>
                    <TableHead className="w-[80px] text-center">신뢰도</TableHead>
                    <TableHead className="w-[80px] text-center">적용</TableHead>
                    <TableHead className="w-[50px]" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rules.map(rule => (
                    <TableRow key={rule.id}>
                      <TableCell className="font-mono text-xs">{rule.counterparty_pattern}</TableCell>
                      <TableCell
                        className="cursor-pointer hover:bg-muted/20 transition-colors"
                        onClick={() => setEditingId(rule.id)}
                      >
                        {editingId === rule.id ? (
                          <AccountCombobox
                            options={internalAccounts}
                            value={rule.internal_account_id ? String(rule.internal_account_id) : ""}
                            onChange={v => handleUpdateAccount(rule.id, v)}
                            placeholder="선택..."
                            compact
                            autoOpen
                          />
                        ) : (
                          <span className={cn("text-xs", rule.internal_account_name ? "text-foreground" : "text-muted-foreground")}>
                            {rule.internal_account_name || "-"}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {rule.standard_account_name || "-"}
                      </TableCell>
                      <TableCell className="text-center">
                        <span className={cn(
                          "text-xs font-mono px-1.5 py-0.5 rounded",
                          rule.confidence >= 0.95 ? "bg-green-500/10 text-green-400" :
                          rule.confidence >= 0.8 ? "bg-yellow-500/10 text-yellow-400" :
                          "bg-red-500/10 text-red-400"
                        )}>
                          {(rule.confidence * 100).toFixed(0)}%
                        </span>
                      </TableCell>
                      <TableCell className="text-center text-xs text-muted-foreground">
                        {rule.hit_count}회
                      </TableCell>
                      <TableCell>
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive">
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>매핑 규칙 삭제</AlertDialogTitle>
                              <AlertDialogDescription>
                                &quot;{rule.counterparty_pattern}&quot; → {rule.internal_account_name} 규칙을 삭제하시겠습니까?
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>취소</AlertDialogCancel>
                              <AlertDialogAction onClick={() => handleDelete(rule.id)}>삭제</AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-2 p-4 border-t">
                  <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>이전</Button>
                  <span className="text-xs text-muted-foreground">{page} / {totalPages}</span>
                  <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>다음</Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
