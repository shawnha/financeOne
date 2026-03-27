"use client"

import { Suspense, useCallback, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { fetchAPI } from "@/lib/api"
import { EntityTabs } from "@/components/entity-tabs"
import { toast } from "sonner"
import { cn } from "@/lib/utils"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"
import {
  BookOpen, Plus, Pencil, Trash2, AlertTriangle,
} from "lucide-react"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface InternalAccount {
  id: number
  entity_id: number
  code: string
  name: string
  standard_code: string | null
  standard_name: string | null
  sort_order: number
  parent_id: number | null
}

interface StandardAccount {
  id: number
  code: string
  name: string
  category: string
  subcategory: string
}

interface FormData {
  code: string
  name: string
  standard_account_id: string
  parent_id: string
  sort_order: string
}

const EMPTY_FORM: FormData = {
  code: "",
  name: "",
  standard_account_id: "",
  parent_id: "",
  sort_order: "0",
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a flat list with depth info for hierarchy display */
function buildHierarchy(accounts: InternalAccount[]) {
  const map = new Map<number, InternalAccount[]>()
  const roots: InternalAccount[] = []

  for (const a of accounts) {
    if (a.parent_id) {
      const children = map.get(a.parent_id) || []
      children.push(a)
      map.set(a.parent_id, children)
    } else {
      roots.push(a)
    }
  }

  const result: { account: InternalAccount; depth: number }[] = []
  function walk(items: InternalAccount[], depth: number) {
    for (const item of items.sort((a, b) => a.sort_order - b.sort_order)) {
      result.push({ account: item, depth })
      const children = map.get(item.id)
      if (children) walk(children, depth + 1)
    }
  }
  walk(roots.sort((a, b) => a.sort_order - b.sort_order), 0)
  return result
}

// ---------------------------------------------------------------------------
// Content Component
// ---------------------------------------------------------------------------

function InternalAccountsContent() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity")

  const [accounts, setAccounts] = useState<InternalAccount[]>([])
  const [standardAccounts, setStandardAccounts] = useState<StandardAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<FormData>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<InternalAccount | null>(null)

  // Fetch accounts
  const load = useCallback(async () => {
    if (!entityId) return
    setLoading(true)
    try {
      const data = await fetchAPI<InternalAccount[]>(
        `/accounts/internal?entity_id=${entityId}`,
      )
      setAccounts(data)
    } catch {
      toast.error("계정 목록을 불러오지 못했습니다")
    } finally {
      setLoading(false)
    }
  }, [entityId])

  // Fetch standard accounts (once)
  useEffect(() => {
    fetchAPI<StandardAccount[]>("/accounts/standard")
      .then(setStandardAccounts)
      .catch(() => {})
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const hierarchy = useMemo(() => buildHierarchy(accounts), [accounts])

  // Open dialog for create
  const handleAdd = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setDialogOpen(true)
  }

  // Open dialog for edit
  const handleEdit = (account: InternalAccount) => {
    setEditingId(account.id)
    // Find the matching standard account ID
    const std = standardAccounts.find(
      (s) => s.code === account.standard_code,
    )
    setForm({
      code: account.code,
      name: account.name,
      standard_account_id: std ? String(std.id) : "",
      parent_id: account.parent_id ? String(account.parent_id) : "",
      sort_order: String(account.sort_order),
    })
    setDialogOpen(true)
  }

  // Save (create or update)
  const handleSave = async () => {
    if (!form.code.trim() || !form.name.trim()) {
      toast.error("코드와 계정명은 필수입니다")
      return
    }
    setSaving(true)
    const body = {
      entity_id: Number(entityId),
      code: form.code.trim(),
      name: form.name.trim(),
      standard_account_id: form.standard_account_id
        ? Number(form.standard_account_id)
        : null,
      parent_id: form.parent_id ? Number(form.parent_id) : null,
      sort_order: Number(form.sort_order) || 0,
    }
    try {
      if (editingId) {
        await fetchAPI(`/accounts/internal/${editingId}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        })
        toast.success("계정이 수정되었습니다")
      } else {
        await fetchAPI("/accounts/internal", {
          method: "POST",
          body: JSON.stringify(body),
        })
        toast.success("계정이 추가되었습니다")
      }
      setDialogOpen(false)
      load()
    } catch {
      toast.error("저장에 실패했습니다")
    } finally {
      setSaving(false)
    }
  }

  // Delete
  const handleDelete = async () => {
    if (!deleteTarget) return
    try {
      await fetchAPI(`/accounts/internal/${deleteTarget.id}`, {
        method: "DELETE",
      })
      toast.success("계정이 삭제되었습니다")
      setDeleteTarget(null)
      load()
    } catch {
      toast.error("삭제에 실패했습니다")
    }
  }

  // Loading state
  if (loading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-48" />
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </CardContent>
      </Card>
    )
  }

  // Waiting for entity selection
  if (!entityId) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-muted-foreground">
          법인을 선택해주세요.
        </CardContent>
      </Card>
    )
  }

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base font-medium">
            내부 계정과목 ({accounts.length}건)
          </CardTitle>
          <Button size="sm" onClick={handleAdd}>
            <Plus className="mr-1.5 h-4 w-4" />
            계정 추가
          </Button>
        </CardHeader>
        <CardContent>
          {accounts.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
              <BookOpen className="mb-3 h-10 w-10 opacity-40" />
              <p className="text-sm">등록된 내부 계정이 없습니다</p>
              <p className="mt-1 text-xs">
                &quot;계정 추가&quot; 버튼을 눌러 첫 번째 계정을 등록해보세요.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="w-[120px]">코드</TableHead>
                    <TableHead>계정명</TableHead>
                    <TableHead>표준계정</TableHead>
                    <TableHead>상위계정</TableHead>
                    <TableHead className="w-[80px] text-right">정렬순서</TableHead>
                    <TableHead className="w-[80px]" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {hierarchy.map(({ account, depth }) => {
                    const parentAccount = depth > 0
                      ? accounts.find((a) => a.id === account.parent_id)
                      : null
                    return (
                      <TableRow
                        key={account.id}
                        className="cursor-pointer hover:bg-secondary/50"
                        onClick={() => handleEdit(account)}
                      >
                        <TableCell className="font-mono text-sm">
                          {account.code}
                        </TableCell>
                        <TableCell>
                          <span
                            style={{ paddingLeft: `${depth * 20}px` }}
                            className="inline-flex items-center gap-1"
                          >
                            {depth > 0 && (
                              <span className="text-muted-foreground">└</span>
                            )}
                            {account.name}
                          </span>
                        </TableCell>
                        <TableCell>
                          {account.standard_code ? (
                            <Badge variant="secondary" className="font-normal">
                              {account.standard_code} {account.standard_name}
                            </Badge>
                          ) : (
                            <span className="text-xs text-muted-foreground">-</span>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {parentAccount
                            ? `${parentAccount.code} ${parentAccount.name}`
                            : "-"}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {account.sort_order}
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-muted-foreground hover:text-destructive"
                            onClick={(e) => {
                              e.stopPropagation()
                              setDeleteTarget(account)
                            }}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create / Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>
              {editingId ? "계정 수정" : "계정 추가"}
            </DialogTitle>
            <DialogDescription>
              {editingId
                ? "내부 계정과목 정보를 수정합니다."
                : "새로운 내부 계정과목을 등록합니다."}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <label className="text-sm font-medium">코드 *</label>
              <Input
                placeholder="예: 1010"
                value={form.code}
                onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))}
              />
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-medium">계정명 *</label>
              <Input
                placeholder="예: 보통예금"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-medium">표준계정</label>
              <Select
                value={form.standard_account_id}
                onValueChange={(v) =>
                  setForm((f) => ({ ...f, standard_account_id: v }))
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="표준계정 선택 (선택사항)" />
                </SelectTrigger>
                <SelectContent>
                  {standardAccounts.map((sa) => (
                    <SelectItem key={sa.id} value={String(sa.id)}>
                      {sa.code} {sa.name}
                      <span className="ml-2 text-xs text-muted-foreground">
                        {sa.category}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-medium">상위계정</label>
              <Select
                value={form.parent_id}
                onValueChange={(v) =>
                  setForm((f) => ({ ...f, parent_id: v }))
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="상위계정 선택 (선택사항)" />
                </SelectTrigger>
                <SelectContent>
                  {accounts
                    .filter((a) => a.id !== editingId)
                    .map((a) => (
                      <SelectItem key={a.id} value={String(a.id)}>
                        {a.code} {a.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-medium">정렬순서</label>
              <Input
                type="number"
                placeholder="0"
                value={form.sort_order}
                onChange={(e) =>
                  setForm((f) => ({ ...f, sort_order: e.target.value }))
                }
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDialogOpen(false)}
              disabled={saving}
            >
              취소
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "저장 중..." : editingId ? "수정" : "추가"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              계정 삭제
            </DialogTitle>
            <DialogDescription>
              <strong>{deleteTarget?.code} {deleteTarget?.name}</strong> 계정을
              삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteTarget(null)}
            >
              취소
            </Button>
            <Button variant="destructive" onClick={handleDelete}>
              삭제
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function InternalAccountsPage() {
  return (
    <div className="space-y-6">
      <Suspense fallback={<Skeleton className="h-10 w-full border-b" />}>
        <EntityTabs />
      </Suspense>

      <div className="flex items-center gap-2">
        <BookOpen className="h-6 w-6 text-muted-foreground" />
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          내부 계정과목
        </h1>
      </div>

      <Suspense fallback={<Skeleton className="h-64 w-full" />}>
        <InternalAccountsContent />
      </Suspense>
    </div>
  )
}
