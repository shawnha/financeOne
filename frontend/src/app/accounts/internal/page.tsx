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
import { AlertTriangle, FolderTree, Plus, Copy } from "lucide-react"
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

interface EntityOption {
  id: number
  name: string
  code: string
}

interface CopyResult {
  source: { entity_id: number; name: string; total: number }
  target: { entity_id: number; name: string; before: number; after: number }
  mode: "merge" | "replace"
  preview: boolean
  inserted: number
  skipped_existing: number
  deactivated: number
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

  // Copy-from-other-entity state
  const [entities, setEntities] = useState<EntityOption[]>([])
  const [copyDialogOpen, setCopyDialogOpen] = useState(false)
  const [copySourceId, setCopySourceId] = useState<string>("")
  const [copyMode, setCopyMode] = useState<"merge" | "replace">("merge")
  const [copyIncludeRecurring, setCopyIncludeRecurring] = useState(true)
  const [copyIncludeMapping, setCopyIncludeMapping] = useState(true)
  const [copyPreview, setCopyPreview] = useState<CopyResult | null>(null)
  const [copyRunning, setCopyRunning] = useState(false)

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

  useEffect(() => {
    fetchAPI<EntityOption[]>("/entities")
      .then(setEntities)
      .catch(() => {})
  }, [])

  useEffect(() => { load() }, [load])

  // ---------------------------------------------------------------------------
  // Copy from another entity
  // ---------------------------------------------------------------------------

  const resetCopyDialog = () => {
    setCopyDialogOpen(false)
    setCopySourceId("")
    setCopyMode("merge")
    setCopyIncludeRecurring(true)
    setCopyIncludeMapping(true)
    setCopyPreview(null)
  }

  const runCopy = async (preview: boolean) => {
    if (!entityId) return
    if (!copySourceId) {
      toast.error("복사해 올 회사를 선택해주세요")
      return
    }
    setCopyRunning(true)
    try {
      const res = await fetchAPI<CopyResult>("/accounts/internal/copy", {
        method: "POST",
        body: JSON.stringify({
          source_entity_id: Number(copySourceId),
          target_entity_id: Number(entityId),
          mode: copyMode,
          include_recurring: copyIncludeRecurring,
          include_standard_mapping: copyIncludeMapping,
          preview,
        }),
      })
      if (preview) {
        setCopyPreview(res)
      } else {
        toast.success(
          `복사 완료 — 추가 ${res.inserted}건` +
          (res.skipped_existing ? ` · 중복 ${res.skipped_existing}건 skip` : "") +
          (res.deactivated ? ` · 기존 ${res.deactivated}건 비활성화` : ""),
        )
        resetCopyDialog()
        await load()
      }
    } catch (e) {
      toast.error(`복사 실패: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setCopyRunning(false)
    }
  }

  const handleToggleRecurring = async (account: TreeAccount) => {
    try {
      await fetchAPI(`/accounts/internal/${account.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_recurring: !account.is_recurring }),
      })
      setAccounts((prev) =>
        prev.map((a) => a.id === account.id ? { ...a, is_recurring: !a.is_recurring } : a),
      )
      toast.success(account.is_recurring ? "고정 해제됨" : "고정 설정됨")
    } catch {
      toast.error("고정 설정에 실패했습니다")
    }
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
        // Check ALL accounts with this prefix to avoid code collision
        const allWithPrefix = accounts
          .map((a) => a.code)
          .filter((c) => c.startsWith(parent.code + "-"))
          .map((c) => {
            const suffix = c.slice(parent.code.length + 1).split("-")[0]
            return parseInt(suffix, 10)
          })
          .filter((n) => !isNaN(n))
        const nextNum = allWithPrefix.length > 0 ? Math.max(...allWithPrefix) + 1 : 1
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
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setCopyPreview(null)
                setCopyDialogOpen(true)
              }}
            >
              <Copy className="mr-1.5 h-4 w-4" />
              다른 회사에서 복사
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
                  {(() => {
                    // Build depth map for tree display
                    const depthMap = new Map<number, number>()
                    const getDepth = (id: number): number => {
                      if (depthMap.has(id)) return depthMap.get(id)!
                      const item = accounts.find((a) => a.id === id)
                      if (!item || !item.parent_id) { depthMap.set(id, 0); return 0 }
                      const d = getDepth(item.parent_id) + 1
                      depthMap.set(id, d)
                      return d
                    }
                    accounts.forEach((a) => getDepth(a.id))
                    // Flatten tree in order
                    const ordered: typeof accounts = []
                    const addChildren = (parentId: number | null) => {
                      accounts
                        .filter((a) => (parentId === null ? !a.parent_id : a.parent_id === parentId))
                        .forEach((a) => { ordered.push(a); addChildren(a.id) })
                    }
                    addChildren(null)
                    return ordered
                      .filter((a) => a.id !== editingId)
                      .map((a) => {
                        const depth = depthMap.get(a.id) ?? 0
                        const prefix = depth === 0 ? "" : "│ ".repeat(depth - 1) + "└ "
                        return (
                          <SelectItem key={a.id} value={String(a.id)}>
                            <span className="font-mono text-muted-foreground/40">{prefix}</span>{a.name}
                          </SelectItem>
                        )
                      })
                  })()}
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

      {/* Copy from another entity */}
      <Dialog
        open={copyDialogOpen}
        onOpenChange={(open) => { if (!open) resetCopyDialog() }}
      >
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Copy className="h-5 w-5" />
              다른 회사에서 내부계정 복사
            </DialogTitle>
            <DialogDescription>
              선택한 회사의 내부계정과목 트리(부모-자식 관계 포함)를 현재 회사로 복사합니다.
              표준계정 매핑과 고정설정도 함께 가져올 수 있습니다.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-2">
              <label className="text-sm font-medium">복사해 올 회사</label>
              <Select value={copySourceId} onValueChange={(v) => { setCopySourceId(v); setCopyPreview(null) }}>
                <SelectTrigger>
                  <SelectValue placeholder="회사 선택" />
                </SelectTrigger>
                <SelectContent>
                  {entities
                    .filter((e) => String(e.id) !== entityId)
                    .map((e) => (
                      <SelectItem key={e.id} value={String(e.id)}>
                        {e.name} <span className="ml-2 text-xs text-muted-foreground">({e.code})</span>
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-2">
              <label className="text-sm font-medium">모드</label>
              <Select
                value={copyMode}
                onValueChange={(v) => { setCopyMode(v as "merge" | "replace"); setCopyPreview(null) }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="merge">병합 (추천) — 같은 코드는 skip, 새로운 계정만 추가</SelectItem>
                  <SelectItem value="replace">덮어쓰기 — 기존 계정 모두 비활성화 후 복사</SelectItem>
                </SelectContent>
              </Select>
              {copyMode === "replace" && (
                <p className="text-[11px] text-amber-300/80">
                  주의: 현재 회사의 모든 활성 계정을 비활성화합니다. 거래·예상 매핑이 끊길 수 있어요.
                </p>
              )}
            </div>

            <div className="grid gap-2">
              <label className="text-sm font-medium">옵션</label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={copyIncludeMapping}
                  onChange={(e) => { setCopyIncludeMapping(e.target.checked); setCopyPreview(null) }}
                  className="h-4 w-4"
                />
                표준계정 매핑 함께 복사
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={copyIncludeRecurring}
                  onChange={(e) => { setCopyIncludeRecurring(e.target.checked); setCopyPreview(null) }}
                  className="h-4 w-4"
                />
                고정설정(매월 반복) 함께 복사
              </label>
            </div>

            {copyPreview && (
              <div className="rounded-md border border-white/[0.06] bg-white/[0.02] p-3 text-xs space-y-1">
                <div className="font-medium text-foreground">미리보기 결과</div>
                <div className="text-muted-foreground">
                  {copyPreview.source.name} · {copyPreview.source.total}건
                  {" → "}
                  {copyPreview.target.name} · {copyPreview.target.before}건
                </div>
                <div>
                  추가 <span className="text-emerald-300">{copyPreview.inserted}</span>건
                  {copyPreview.skipped_existing > 0 && (
                    <> · 중복 skip <span className="text-amber-300">{copyPreview.skipped_existing}</span>건</>
                  )}
                  {copyPreview.deactivated > 0 && (
                    <> · 기존 비활성화 <span className="text-red-300">{copyPreview.deactivated}</span>건</>
                  )}
                </div>
                <div className="text-muted-foreground/70">
                  실행 후 결과: 활성 계정 {copyPreview.target.before} → <span className="text-foreground">{copyPreview.target.after}</span>건
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={resetCopyDialog} disabled={copyRunning}>
              취소
            </Button>
            <Button
              variant="outline"
              onClick={() => runCopy(true)}
              disabled={copyRunning || !copySourceId}
            >
              {copyRunning && copyPreview === null ? "확인 중..." : "미리보기"}
            </Button>
            <Button
              onClick={() => runCopy(false)}
              disabled={copyRunning || !copySourceId || !copyPreview}
            >
              {copyRunning && copyPreview ? "복사 중..." : "실행"}
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
