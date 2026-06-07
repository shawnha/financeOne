"use client"

import { Suspense, useCallback, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { fetchAPI } from "@/lib/api"
import { EntityTabs } from "@/components/entity-tabs"
import { toast } from "sonner"

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
  standard_category: string | null
  standard_subcategory: string | null
  standard_account_id: number | null
  standard_sort_order: number | null
  sort_order: number
  parent_id: number | null
  is_recurring: boolean
}

interface StandardAccount {
  id: number
  code: string
  name: string
  category: string
  subcategory?: string | null
  sort_order?: number
  is_backbone?: boolean
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
  fixed_parents?: number
}

interface AutoMapStdProposal {
  internal_id: number
  internal_code: string
  internal_name: string
  current_std_id: number | null
  best: { std_id: number; code: string; name: string; name_sim: number; kw_freq: number } | null
  confidence: number
  accepted: boolean
  reason: string
}

interface AutoMapStdResult {
  entity_id: number
  gaap_type: "K_GAAP" | "US_GAAP"
  total_targets: number
  accepted: number
  rejected_low_confidence: number
  applied: number
  preview: boolean
  proposals: AutoMapStdProposal[]
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ROOT_CODES = ["INC", "EXP"]

// ---------------------------------------------------------------------------
// 표준 골격 기반 그룹핑 — 카테고리 > 표준(골격) > 잎 (재설계 목표 트리)
// ---------------------------------------------------------------------------

const CAT_ORDER = ["자산", "부채", "자본", "수익", "매출", "매출원가", "비용", "기타"]

interface StdNode {
  std: StandardAccount
  leaves: { leaf: RawAccount; groupName: string | null }[]
}
interface CatNode {
  category: string
  standards: StdNode[]
}

function buildStandardGroups(
  accounts: RawAccount[],
  standards: StandardAccount[],
): { cats: CatNode[]; unmapped: RawAccount[] } {
  // 잎 = 자식 없는 내부계정 (컨테이너/그룹 노드 제외)
  const hasChild = new Set<number>()
  for (const a of accounts) if (a.parent_id != null) hasChild.add(a.parent_id)
  const byId = new Map(accounts.map((a) => [a.id, a]))
  const isContainer = (a: RawAccount) =>
    ROOT_CODES.includes(a.code) || ["지출", "수입"].includes(a.name)
  // 잎의 기능그룹 이름(부모가 컨테이너 아니면 그룹명)
  const groupNameOf = (a: RawAccount): string | null => {
    if (a.parent_id == null) return null
    const p = byId.get(a.parent_id)
    if (!p || isContainer(p)) return null
    return p.name
  }
  const leaves = accounts.filter((a) => !hasChild.has(a.id) && !ROOT_CODES.includes(a.code))

  const byStd = new Map<number, { leaf: RawAccount; groupName: string | null }[]>()
  const unmapped: RawAccount[] = []
  for (const lf of leaves) {
    if (lf.standard_account_id == null) { unmapped.push(lf); continue }
    const list = byStd.get(lf.standard_account_id) || []
    list.push({ leaf: lf, groupName: groupNameOf(lf) })
    byStd.set(lf.standard_account_id, list)
  }
  // /accounts/standard 는 잎당 1행이라 표준이 중복 → id 기준 dedup(backbone 우선)
  const stdById = new Map<number, StandardAccount>()
  for (const s of standards) {
    const prev = stdById.get(s.id)
    if (!prev) stdById.set(s.id, s)
    else if (s.is_backbone && !prev.is_backbone) stdById.set(s.id, s)
  }
  // 표시 표준 = 골격(backbone) 또는 잎 보유
  const shown = [...stdById.values()].filter((s) => s.is_backbone || byStd.has(s.id))
  const byCat = new Map<string, StdNode[]>()
  for (const s of shown) {
    const leavesOf = (byStd.get(s.id) || []).sort((a, b) => {
      const g = (a.groupName || "").localeCompare(b.groupName || "")
      return g !== 0 ? g : a.leaf.name.localeCompare(b.leaf.name)
    })
    const list = byCat.get(s.category) || []
    list.push({ std: s, leaves: leavesOf })
    byCat.set(s.category, list)
  }
  for (const [, list] of byCat) {
    list.sort((a, b) =>
      (a.std.sort_order ?? 0) - (b.std.sort_order ?? 0) || a.std.code.localeCompare(b.std.code),
    )
  }
  const cats = [...CAT_ORDER, ...[...byCat.keys()].filter((c) => !CAT_ORDER.includes(c))]
    .filter((c) => byCat.has(c))
    .map((c) => ({ category: c, standards: byCat.get(c)! }))
  return { cats, unmapped }
}

// M3 정리(평탄화/잡탕)로 "기타 X" 리네임된 잎 = 변경 마커
const isRenamed = (name: string) => name.startsWith("기타 ")

// ---------------------------------------------------------------------------
// Content Component
// ---------------------------------------------------------------------------

function InternalAccountsContent() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity")

  const [accounts, setAccounts] = useState<RawAccount[]>([])
  const [standardAccounts, setStandardAccounts] = useState<StandardAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

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
  const [copyFixParents, setCopyFixParents] = useState(true)
  const [copyPreview, setCopyPreview] = useState<CopyResult | null>(null)
  const [copyRunning, setCopyRunning] = useState(false)

  // Auto-map-standard state
  const [stdMapDialogOpen, setStdMapDialogOpen] = useState(false)
  const [stdMapOnlyUnmapped, setStdMapOnlyUnmapped] = useState(true)
  const [stdMapMinConf, setStdMapMinConf] = useState(0.55)
  const [stdMapPreview, setStdMapPreview] = useState<AutoMapStdResult | null>(null)
  const [stdMapRunning, setStdMapRunning] = useState(false)


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
    const q = entityId ? `?entity_id=${entityId}` : ""
    fetchAPI<StandardAccount[]>(`/accounts/standard${q}`)
      .then(setStandardAccounts)
      .catch(() => {})
  }, [entityId])

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

  const resetStdMap = () => {
    setStdMapDialogOpen(false)
    setStdMapOnlyUnmapped(true)
    setStdMapMinConf(0.55)
    setStdMapPreview(null)
  }

  const runStdMap = async (apply: boolean) => {
    if (!entityId) return
    setStdMapRunning(true)
    try {
      const res = await fetchAPI<AutoMapStdResult>("/accounts/internal/auto-map-standard", {
        method: "POST",
        body: JSON.stringify({
          entity_id: Number(entityId),
          only_unmapped: stdMapOnlyUnmapped,
          min_confidence: stdMapMinConf,
          apply,
        }),
      })
      if (apply) {
        toast.success(`표준계정 매핑 적용 완료 — ${res.applied}건`)
        resetStdMap()
        await load()
      } else {
        setStdMapPreview(res)
      }
    } catch (e) {
      toast.error(`표준계정 자동매핑 실패: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setStdMapRunning(false)
    }
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
          fix_existing_parents: copyFixParents,
          preview,
        }),
      })
      if (preview) {
        setCopyPreview(res)
      } else {
        toast.success(
          `복사 완료 — 추가 ${res.inserted}건` +
          (res.skipped_existing ? ` · 중복 ${res.skipped_existing}건 skip` : "") +
          (res.fixed_parents ? ` · 트리 보정 ${res.fixed_parents}건` : "") +
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

  const { cats, unmapped } = useMemo(
    () => buildStandardGroups(accounts, standardAccounts),
    [accounts, standardAccounts],
  )
  const backboneCount = useMemo(
    () => standardAccounts.filter((s) => s.is_backbone).length,
    [standardAccounts],
  )

  const handleToggle = (key: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // 표준 골격 뷰의 잎(RawAccount) 수정
  const handleEditRaw = (leaf: RawAccount) => {
    setEditingId(leaf.id)
    setForm({
      name: leaf.name,
      standard_account_id: leaf.standard_account_id ? String(leaf.standard_account_id) : "",
      parent_id: leaf.parent_id ? String(leaf.parent_id) : "",
    })
    setDialogOpen(true)
  }

  // 빈 표준 골격 밑에 새 잎 추가 (표준 사전선택)
  const handleAddUnderStandard = (stdId: number) => {
    setEditingId(null)
    setForm({ ...EMPTY_FORM, standard_account_id: String(stdId) })
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
            {backboneCount > 0 && (
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                · 표준 골격 {backboneCount}개
              </span>
            )}
          </CardTitle>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setStdMapPreview(null)
                setStdMapDialogOpen(true)
              }}
            >
              <FolderTree className="mr-1.5 h-4 w-4" />
              표준계정 자동매핑
            </Button>
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
            <div className="space-y-3">
              {cats.map((cat) => {
                const catKey = `cat:${cat.category}`
                const catCollapsed = collapsed.has(catKey)
                return (
                  <div key={cat.category}>
                    <button
                      type="button"
                      onClick={() => handleToggle(catKey)}
                      className="flex w-full items-center gap-1.5 border-b border-border px-1 py-1.5 text-left text-sm font-bold text-foreground"
                    >
                      <span className="w-2 text-[9px] text-muted-foreground">{catCollapsed ? "▶" : "▼"}</span>
                      {cat.category}
                      <span className="text-xs font-normal text-muted-foreground">표준 {cat.standards.length}</span>
                    </button>
                    {!catCollapsed && cat.standards.map((sn) => {
                      const empty = sn.leaves.length === 0
                      const stdKey = `std:${sn.std.id}`
                      const stdCollapsed = collapsed.has(stdKey)
                      return (
                        <div key={sn.std.id} className="mt-0.5">
                          <div
                            className="group flex items-center gap-2 rounded px-2 py-1.5 hover:bg-muted/30"
                            onClick={() => !empty && handleToggle(stdKey)}
                            role="button"
                            tabIndex={0}
                          >
                            <span className="w-2 text-[9px] text-muted-foreground">
                              {!empty ? (stdCollapsed ? "▶" : "▼") : ""}
                            </span>
                            <span className="min-w-[44px] font-mono text-[11px] font-bold text-blue-400">{sn.std.code}</span>
                            <span className="text-[13px] font-semibold text-foreground">{sn.std.name}</span>
                            {empty ? (
                              <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[9px] text-amber-300">
                                비어있음 · 거래 시 잎 추가
                              </span>
                            ) : (
                              <span className="text-[10px] text-muted-foreground">{sn.leaves.length}개</span>
                            )}
                            {sn.std.is_backbone && (
                              <span className="rounded bg-emerald-500/10 px-1 text-[9px] text-emerald-300">골격</span>
                            )}
                            <span className="ml-auto opacity-0 transition-opacity group-hover:opacity-100">
                              <button
                                type="button"
                                onClick={(e) => { e.stopPropagation(); handleAddUnderStandard(sn.std.id) }}
                                className="text-[10px] text-accent hover:underline"
                              >
                                + 잎 추가
                              </button>
                            </span>
                          </div>
                          {!empty && !stdCollapsed && (
                            <div className="ml-[18px] border-l border-border/40 pl-2">
                              {sn.leaves.map(({ leaf, groupName }) => (
                                <div
                                  key={leaf.id}
                                  className="group flex items-center gap-2 rounded px-2 py-1 text-[12px] hover:bg-muted/30"
                                >
                                  <span className="text-muted-foreground/40">└</span>
                                  {groupName && (
                                    <span className="rounded bg-blue-500/10 px-1 text-[9px] text-blue-300/80">{groupName}</span>
                                  )}
                                  <span className="text-foreground/90">{leaf.name}</span>
                                  {isRenamed(leaf.name) && (
                                    <span className="rounded bg-amber-500/10 px-1 text-[9px] text-amber-300">정리됨</span>
                                  )}
                                  {leaf.is_recurring && (
                                    <span className="rounded bg-blue-500/10 px-1 text-[9px] text-blue-400">반복</span>
                                  )}
                                  <span className="ml-auto flex gap-2 text-[10px] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                                    <button type="button" onClick={() => handleEditRaw(leaf)} className="hover:text-foreground">수정</button>
                                    <button type="button" onClick={() => setDeleteTarget(leaf)} className="hover:text-destructive">삭제</button>
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )
              })}

              {unmapped.length > 0 && (
                <div>
                  <div className="border-b border-amber-500/30 px-1 py-1.5 text-sm font-bold text-amber-300">
                    미분류 (표준 없음) · {unmapped.length}건
                  </div>
                  <div className="ml-[18px] border-l border-amber-500/20 pl-2">
                    {unmapped.map((leaf) => (
                      <div key={leaf.id} className="group flex items-center gap-2 rounded px-2 py-1 text-[12px] hover:bg-muted/30">
                        <span className="text-muted-foreground/40">└</span>
                        <span className="text-foreground/90">{leaf.name}</span>
                        <span className="rounded bg-amber-500/10 px-1 text-[9px] text-amber-300">표준 지정 필요</span>
                        <span className="ml-auto text-[10px] opacity-0 transition-opacity group-hover:opacity-100">
                          <button type="button" onClick={() => handleEditRaw(leaf)} className="text-accent hover:underline">표준 지정</button>
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
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

      {/* Auto-map standard accounts */}
      <Dialog
        open={stdMapDialogOpen}
        onOpenChange={(open) => { if (!open) resetStdMap() }}
      >
        <DialogContent className="sm:max-w-[640px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FolderTree className="h-5 w-5" />
              표준계정 자동매핑
            </DialogTitle>
            <DialogDescription>
              내부계정의 표준계정(GAAP standard) 자동 매핑. 매칭 알고리즘:
              ① internal code 가 standard code 와 정확히 일치 → 즉시 채택
              ② 이름 유사도(pg_trgm) + 거래처 빈도 통계(2025 결산자료 학습)
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-2">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={stdMapOnlyUnmapped}
                  onChange={(e) => { setStdMapOnlyUnmapped(e.target.checked); setStdMapPreview(null) }}
                  className="h-4 w-4"
                />
                비어있는 매핑만 채우기 (기존 매핑 보존)
              </label>
              <div className="text-[11px] text-muted-foreground/70">
                체크 해제 시 기존 매핑도 더 좋은 후보로 교체 시도
              </div>
            </div>

            <div className="grid gap-2">
              <label className="text-sm">
                최소 신뢰도 ({stdMapMinConf.toFixed(2)})
              </label>
              <input
                type="range"
                min={0.4} max={0.95} step={0.05}
                value={stdMapMinConf}
                onChange={(e) => { setStdMapMinConf(Number(e.target.value)); setStdMapPreview(null) }}
                className="w-full"
              />
            </div>

            {stdMapPreview && (
              <div className="rounded-md border border-white/[0.06] bg-white/[0.02] p-3 text-xs space-y-2 max-h-72 overflow-auto">
                <div className="font-medium text-foreground sticky top-0 bg-background/80 backdrop-blur py-1 -mx-3 px-3">
                  {stdMapPreview.gaap_type} · 대상 {stdMapPreview.total_targets}건 ·
                  채택 <span className="text-emerald-300">{stdMapPreview.accepted}</span> /
                  미달 <span className="text-amber-300">{stdMapPreview.rejected_low_confidence}</span>
                </div>
                {stdMapPreview.proposals.slice(0, 30).map((p) => (
                  <div key={p.internal_id} className="pl-2">
                    <span className={p.accepted ? "text-emerald-300" : "text-amber-300"}>
                      {p.accepted ? "✓" : "○"}
                    </span>{" "}
                    <span className="text-muted-foreground/80">{p.internal_code} {p.internal_name}</span>
                    {p.best ? (
                      <>
                        {" → "}
                        <span className="text-foreground">{p.best.code} {p.best.name}</span>
                        <span className="text-muted-foreground/60"> · conf {p.confidence} · {p.reason}</span>
                      </>
                    ) : (
                      <span className="text-muted-foreground/60"> → 후보 없음</span>
                    )}
                  </div>
                ))}
                {stdMapPreview.proposals.length > 30 && (
                  <div className="text-muted-foreground/60">... ({stdMapPreview.proposals.length - 30} more)</div>
                )}
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={resetStdMap} disabled={stdMapRunning}>
              취소
            </Button>
            <Button
              variant="outline"
              onClick={() => runStdMap(false)}
              disabled={stdMapRunning}
            >
              미리보기
            </Button>
            <Button
              onClick={() => runStdMap(true)}
              disabled={stdMapRunning || !stdMapPreview || stdMapPreview.accepted === 0}
            >
              실행 ({stdMapPreview?.accepted ?? 0}건 적용)
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
              {copyMode === "merge" && (
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={copyFixParents}
                    onChange={(e) => { setCopyFixParents(e.target.checked); setCopyPreview(null) }}
                    className="h-4 w-4"
                  />
                  같은 코드가 있어도 부모-자식 트리 보정
                  <span className="ml-1 text-[11px] text-muted-foreground/70">
                    (이미 있는 계정의 parent 만 source 트리에 맞춰 갱신)
                  </span>
                </label>
              )}
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
                  {copyPreview.fixed_parents !== undefined && copyPreview.fixed_parents > 0 && (
                    <> · 트리 보정 <span className="text-blue-300">{copyPreview.fixed_parents}</span>건</>
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
