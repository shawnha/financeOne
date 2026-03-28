"use client"

import { Suspense, useCallback, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { fetchAPI } from "@/lib/api"
import { EntityTabs } from "@/components/entity-tabs"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import {
  DndContext,
  closestCenter,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from "@dnd-kit/core"
import {
  SortableContext,
  verticalListSortingStrategy,
  arrayMove,
  sortableKeyboardCoordinates,
} from "@dnd-kit/sortable"
import { restrictToVerticalAxis } from "@dnd-kit/modifiers"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"
import { AlertTriangle, Copy, FolderTree, Plus } from "lucide-react"
import { MonthPicker } from "@/components/month-picker"
import { Checkbox } from "@/components/ui/checkbox"
import { TreeAccountItem, flattenTree, type TreeAccount } from "@/components/tree-account-item"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RawAccount {
  id: number
  entity_id: number
  code: string
  name: string
  standard_code: string | null
  standard_name: string | null
  sort_order: number
  parent_id: number | null
  is_recurring: boolean
}

interface StandardAccount {
  id: number
  code: string
  name: string
  category: string
}

interface FormData {
  name: string
  standard_account_id: string
  parent_id: string
}

const EMPTY_FORM: FormData = {
  name: "",
  standard_account_id: "",
  parent_id: "",
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ROOT_CODES = ["INC", "EXP"]

function buildTree(accounts: RawAccount[]): TreeAccount[] {
  const byParent = new Map<number | null, RawAccount[]>()
  for (const a of accounts) {
    const key = a.parent_id
    const list = byParent.get(key) || []
    list.push(a)
    byParent.set(key, list)
  }

  function walk(parentId: number | null, depth: number): TreeAccount[] {
    const children = byParent.get(parentId) || []
    return children
      .sort((a, b) => a.sort_order - b.sort_order)
      .map((a) => ({
        ...a,
        depth,
        isRoot: ROOT_CODES.includes(a.code),
        is_recurring: a.is_recurring ?? false,
        children: walk(a.id, depth + 1),
      }))
  }
  return walk(null, 0)
}

// ---------------------------------------------------------------------------
// Content Component
// ---------------------------------------------------------------------------

function InternalAccountsContent() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity")

  const [accounts, setAccounts] = useState<RawAccount[]>([])
  const [standardAccounts, setStandardAccounts] = useState<StandardAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<FormData>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<RawAccount | null>(null)

  // Budget state
  const now = new Date()
  const [budgetYear, setBudgetYear] = useState(now.getFullYear())
  const [budgetMonth, setBudgetMonth] = useState(now.getMonth() + 1)
  const [budgets, setBudgets] = useState<Record<number, number>>({})
  const [budgetTarget, setBudgetTarget] = useState<TreeAccount | null>(null)
  const [budgetInput, setBudgetInput] = useState("")
  const [budgetSaving, setBudgetSaving] = useState(false)
  const [budgetRecurring, setBudgetRecurring] = useState(false)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const load = useCallback(async () => {
    if (!entityId) return
    setLoading(true)
    try {
      const data = await fetchAPI<RawAccount[]>(
        `/accounts/internal?entity_id=${entityId}`,
      )
      setAccounts(data)
    } catch {
      toast.error("계정 목록을 불러오지 못했습니다")
    } finally {
      setLoading(false)
    }
  }, [entityId])

  useEffect(() => {
    fetchAPI<StandardAccount[]>("/accounts/standard")
      .then(setStandardAccounts)
      .catch(() => {})
  }, [])

  useEffect(() => { load() }, [load])

  // Budget loading
  const budgetMonthStr = useMemo(
    () => `${budgetYear}-${String(budgetMonth).padStart(2, "0")}`,
    [budgetYear, budgetMonth],
  )

  const loadBudgets = useCallback(async () => {
    if (!entityId) return
    try {
      const data = await fetchAPI<{ forecasts: Array<{ internal_account_id: number | null; forecast_amount: number }> }>(
        `/forecasts?entity_id=${entityId}&year=${budgetYear}&month=${budgetMonth}`,
      )
      const map: Record<number, number> = {}
      for (const f of data.forecasts) {
        if (f.internal_account_id) {
          map[f.internal_account_id] = (map[f.internal_account_id] || 0) + f.forecast_amount
        }
      }
      setBudgets(map)
    } catch {
      // silently ignore — budgets are optional
    }
  }, [entityId, budgetYear, budgetMonth])

  useEffect(() => { loadBudgets() }, [loadBudgets])

  const handleSaveBudget = async () => {
    if (!budgetTarget || !entityId) return
    const amount = Number(budgetInput.replace(/,/g, ""))
    if (isNaN(amount)) {
      toast.error("올바른 금액을 입력해주세요")
      return
    }
    setBudgetSaving(true)
    try {
      const isIncome = budgetTarget.code.startsWith("INC")
      await fetchAPI("/forecasts", {
        method: "POST",
        body: JSON.stringify({
          entity_id: Number(entityId),
          internal_account_id: budgetTarget.id,
          year: budgetYear,
          month: budgetMonth,
          category: budgetTarget.name,
          type: isIncome ? "in" : "out",
          forecast_amount: amount,
          is_recurring: budgetRecurring,
        }),
      })
      // Toggle recurring if changed
      const rawAccount = accounts.find((a) => a.id === budgetTarget.id)
      if (rawAccount && rawAccount.is_recurring !== budgetRecurring) {
        await fetchAPI(`/accounts/internal/${budgetTarget.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            entity_id: Number(entityId),
            is_recurring: budgetRecurring,
          }),
        })
      }
      toast.success("예산이 저장되었습니다")
      setBudgetTarget(null)
      loadBudgets()
      load()
    } catch {
      toast.error("예산 저장에 실패했습니다")
    } finally {
      setBudgetSaving(false)
    }
  }

  const handleToggleRecurring = async (account: TreeAccount) => {
    if (!entityId) return
    try {
      await fetchAPI(`/accounts/internal/${account.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          entity_id: Number(entityId),
          is_recurring: !account.is_recurring,
        }),
      })
      load()
    } catch {
      toast.error("고정비 설정에 실패했습니다")
    }
  }

  const handleCopyRecurring = async () => {
    if (!entityId) return
    const recurringAccounts = accounts.filter((a) => a.is_recurring)
    if (recurringAccounts.length === 0) {
      toast.error("고정비 항목이 없습니다")
      return
    }
    // Get previous month
    let prevYear = budgetYear
    let prevMonth = budgetMonth - 1
    if (prevMonth < 1) {
      prevMonth = 12
      prevYear -= 1
    }
    try {
      const prevData = await fetchAPI<{ forecasts: Array<{ internal_account_id: number | null; forecast_amount: number }> }>(
        `/forecasts?entity_id=${entityId}&year=${prevYear}&month=${prevMonth}`,
      )
      let copied = 0
      for (const ra of recurringAccounts) {
        const prev = prevData.forecasts.find((f) => f.internal_account_id === ra.id)
        if (prev) {
          await fetchAPI("/forecasts", {
            method: "POST",
            body: JSON.stringify({
              entity_id: Number(entityId),
              internal_account_id: ra.id,
              year: budgetYear,
              month: budgetMonth,
              forecast_amount: prev.forecast_amount,
            }),
          })
          copied++
        }
      }
      if (copied > 0) {
        toast.success(`고정비 ${copied}건이 복사되었습니다`)
        loadBudgets()
      } else {
        toast.error("이전 달 고정비 데이터가 없습니다")
      }
    } catch {
      toast.error("고정비 복사에 실패했습니다")
    }
  }

  const handleBudgetClick = (account: TreeAccount) => {
    setBudgetTarget(account)
    setBudgetInput(budgets[account.id] != null ? Number(budgets[account.id]).toLocaleString() : "")
    setBudgetRecurring(account.is_recurring)
  }

  const tree = useMemo(() => buildTree(accounts), [accounts])
  const visibleItems = useMemo(() => flattenTree(tree, collapsed), [tree, collapsed])
  const sortableIds = useMemo(() => visibleItems.map((n) => n.id), [visibleItems])

  const handleToggle = (id: number) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return

    const dragId = active.id as number
    const dropId = over.id as number

    const dragItem = accounts.find((a) => a.id === dragId)
    const dropItem = accounts.find((a) => a.id === dropId)
    if (!dragItem || !dropItem) return
    if (dragItem.parent_id !== dropItem.parent_id) return
    if (ROOT_CODES.includes(dragItem.code)) return

    const siblings = accounts
      .filter((a) => a.parent_id === dragItem.parent_id)
      .sort((a, b) => a.sort_order - b.sort_order)

    const oldIndex = siblings.findIndex((s) => s.id === dragId)
    const newIndex = siblings.findIndex((s) => s.id === dropId)
    if (oldIndex === -1 || newIndex === -1) return

    const reordered = arrayMove(siblings, oldIndex, newIndex)

    const items = reordered.map((item, idx) => ({
      id: item.id,
      sort_order: (idx + 1) * 100,
      parent_id: item.parent_id,
    }))

    // Optimistic update
    const updatedAccounts = accounts.map((a) => {
      const updated = items.find((i) => i.id === a.id)
      return updated ? { ...a, sort_order: updated.sort_order } : a
    })
    setAccounts(updatedAccounts)

    try {
      await fetchAPI("/accounts/internal/sort-order", {
        method: "PUT",
        body: JSON.stringify({ items }),
      })
    } catch {
      toast.error("순서 저장에 실패했습니다")
      load()
    }
  }

  const handleAddChild = (parentId: number) => {
    setEditingId(null)
    setForm({ ...EMPTY_FORM, parent_id: String(parentId) })
    setDialogOpen(true)
  }

  const handleEdit = (account: TreeAccount) => {
    if (account.isRoot) return
    setEditingId(account.id)
    const std = standardAccounts.find((s) => s.code === account.standard_code)
    setForm({
      name: account.name,
      standard_account_id: std ? String(std.id) : "",
      parent_id: account.parent_id ? String(account.parent_id) : "",
    })
    setDialogOpen(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) {
      toast.error("계정명은 필수입니다")
      return
    }
    setSaving(true)

    const parentId = form.parent_id ? Number(form.parent_id) : null
    const parent = parentId ? accounts.find((a) => a.id === parentId) : null
    const siblings = accounts.filter((a) => a.parent_id === parentId)
    const nextSort = siblings.length > 0
      ? Math.max(...siblings.map((s) => s.sort_order)) + 100
      : 100

    let code = ""
    if (!editingId) {
      if (parent) {
        const childCodes = siblings
          .map((s) => s.code)
          .filter((c) => c.startsWith(parent.code + "-"))
          .map((c) => {
            const suffix = c.slice(parent.code.length + 1)
            return parseInt(suffix, 10)
          })
          .filter((n) => !isNaN(n))
        const nextNum = childCodes.length > 0 ? Math.max(...childCodes) + 1 : 1
        code = `${parent.code}-${String(nextNum).padStart(3, "0")}`
      } else {
        code = `MISC-${Date.now()}`
      }
    }

    const body: Record<string, unknown> = {
      entity_id: Number(entityId),
      name: form.name.trim(),
      standard_account_id: form.standard_account_id
        ? Number(form.standard_account_id)
        : null,
      parent_id: parentId,
      sort_order: nextSort,
    }
    if (!editingId) {
      body.code = code
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

  if (loading) {
    return (
      <Card>
        <CardHeader><Skeleton className="h-6 w-48" /></CardHeader>
        <CardContent className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </CardContent>
      </Card>
    )
  }

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
        <CardHeader className="flex flex-row items-center justify-between gap-4 flex-wrap">
          <CardTitle className="text-base font-medium">
            내부 계정과목 ({accounts.length}건)
          </CardTitle>
          <div className="flex items-center gap-2">
            <MonthPicker
              months={[]}
              selected={budgetMonthStr}
              onSelect={(m) => {
                const [y, mo] = m.split("-").map(Number)
                setBudgetYear(y)
                setBudgetMonth(mo)
              }}
              allowFuture
            />
            <Button size="sm" variant="outline" onClick={handleCopyRecurring} title="이전 달 고정비를 현재 달에 복사">
              <Copy className="mr-1.5 h-3.5 w-3.5" />
              고정비 복사
            </Button>
            <Button size="sm" onClick={() => {
              setEditingId(null)
              setForm(EMPTY_FORM)
              setDialogOpen(true)
            }}>
              <Plus className="mr-1.5 h-4 w-4" />
              계정 추가
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {accounts.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
              <FolderTree className="mb-3 h-10 w-10 opacity-40" />
              <p className="text-sm">등록된 내부 계정이 없습니다</p>
              <p className="mt-1 text-xs">seed를 실행하거나 계정을 추가해보세요.</p>
            </div>
          ) : (
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
              modifiers={[restrictToVerticalAxis]}
            >
              <SortableContext items={sortableIds} strategy={verticalListSortingStrategy}>
                <div className="space-y-0.5">
                  {visibleItems.map((node) => (
                    <TreeAccountItem
                      key={node.id}
                      account={node}
                      collapsed={collapsed}
                      onToggle={handleToggle}
                      onEdit={handleEdit}
                      onDelete={(a) => setDeleteTarget(a as unknown as RawAccount)}
                      onAddChild={handleAddChild}
                      budgetAmount={budgets[node.id] ?? null}
                      onBudgetClick={handleBudgetClick}
                      onToggleRecurring={handleToggleRecurring}
                    />
                  ))}
                </div>
              </SortableContext>
            </DndContext>
          )}
        </CardContent>
      </Card>

      {/* Create / Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>{editingId ? "계정 수정" : "계정 추가"}</DialogTitle>
            <DialogDescription>
              {editingId
                ? "계정 이름과 표준계정 매핑을 수정합니다."
                : "새로운 계정을 추가합니다. 코드는 자동 생성됩니다."}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <label className="text-sm font-medium">계정명 *</label>
              <Input
                placeholder="예: ChatGPT"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-medium">상위 카테고리</label>
              <Select
                value={form.parent_id}
                onValueChange={(v) => setForm((f) => ({ ...f, parent_id: v }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="카테고리 선택" />
                </SelectTrigger>
                <SelectContent>
                  {accounts
                    .filter((a) => a.id !== editingId)
                    .map((a) => {
                      const depth = accounts.find((p) => p.id === a.parent_id) ? 1 : 0
                      return (
                        <SelectItem key={a.id} value={String(a.id)}>
                          {depth > 0 && "  └ "}{a.name}
                        </SelectItem>
                      )
                    })}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-medium">표준계정 매핑</label>
              <Select
                value={form.standard_account_id}
                onValueChange={(v) => setForm((f) => ({ ...f, standard_account_id: v }))}
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
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={saving}>
              취소
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "저장 중..." : editingId ? "수정" : "추가"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              계정 삭제
            </DialogTitle>
            <DialogDescription>
              <strong>{deleteTarget?.name}</strong> 계정을 삭제하시겠습니까?
              {deleteTarget && accounts.some((a) => a.parent_id === deleteTarget.id) && (
                <span className="block mt-2 text-destructive">
                  하위 항목이 있습니다. 하위 항목도 함께 비활성화됩니다.
                </span>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>취소</Button>
            <Button variant="destructive" onClick={handleDelete}>삭제</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {/* Budget Input Dialog */}
      <Dialog open={!!budgetTarget} onOpenChange={(open) => !open && setBudgetTarget(null)}>
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle>예산 입력</DialogTitle>
            <DialogDescription>
              {budgetTarget?.name} — {budgetYear}년 {budgetMonth}월
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <label className="text-sm font-medium">예산 금액 (원)</label>
              <Input
                placeholder="0"
                value={budgetInput}
                onChange={(e) => {
                  const raw = e.target.value.replace(/[^\d]/g, "")
                  setBudgetInput(raw ? Number(raw).toLocaleString() : "")
                }}
                onKeyDown={(e) => e.key === "Enter" && handleSaveBudget()}
              />
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="budget-recurring"
                checked={budgetRecurring}
                onCheckedChange={(checked) => setBudgetRecurring(checked === true)}
              />
              <label htmlFor="budget-recurring" className="text-sm cursor-pointer">
                고정비 (매월 반복)
              </label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setBudgetTarget(null)} disabled={budgetSaving}>
              취소
            </Button>
            <Button onClick={handleSaveBudget} disabled={budgetSaving}>
              {budgetSaving ? "저장 중..." : "저장"}
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
        <FolderTree className="h-6 w-6 text-muted-foreground" />
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
