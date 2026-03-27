"use client"

import { Suspense, useCallback, useEffect, useState } from "react"
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
  Users, Plus, Trash2, AlertTriangle,
} from "lucide-react"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Member {
  id: number
  entity_id: number
  name: string
  role: string
  card_number: string | null
  created_at: string
}

type MemberRole = "admin" | "member" | "corporate" | "staff"

interface FormData {
  name: string
  role: MemberRole | ""
}

const EMPTY_FORM: FormData = {
  name: "",
  role: "",
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ROLES: { value: MemberRole; label: string }[] = [
  { value: "admin", label: "관리자" },
  { value: "member", label: "멤버" },
  { value: "corporate", label: "법인" },
  { value: "staff", label: "스태프" },
]

const ROLE_BADGE_STYLES: Record<MemberRole, string> = {
  admin: "bg-green-500/10 text-green-500 border-green-500/20",
  member: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  corporate: "bg-purple-500/10 text-purple-500 border-purple-500/20",
  staff: "bg-gray-500/10 text-gray-400 border-gray-500/20",
}

const ROLE_LABELS: Record<MemberRole, string> = {
  admin: "관리자",
  member: "멤버",
  corporate: "법인",
  staff: "스태프",
}

// ---------------------------------------------------------------------------
// Content Component
// ---------------------------------------------------------------------------

function MembersContent() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity")

  const [members, setMembers] = useState<Member[]>([])
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<FormData>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Member | null>(null)

  // Fetch members
  const load = useCallback(async () => {
    if (!entityId) return
    setLoading(true)
    try {
      const data = await fetchAPI<Member[]>(
        `/accounts/members?entity_id=${entityId}`,
      )
      setMembers(data)
    } catch {
      toast.error("멤버 목록을 불러오지 못했습니다")
    } finally {
      setLoading(false)
    }
  }, [entityId])

  useEffect(() => {
    load()
  }, [load])

  // Open dialog for create
  const handleAdd = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setDialogOpen(true)
  }

  // Open dialog for edit
  const handleEdit = (member: Member) => {
    setEditingId(member.id)
    setForm({
      name: member.name,
      role: member.role as MemberRole,
    })
    setDialogOpen(true)
  }

  // Save (create or update)
  const handleSave = async () => {
    if (!form.name.trim()) {
      toast.error("이름은 필수입니다")
      return
    }
    if (!form.role) {
      toast.error("역할을 선택해주세요")
      return
    }
    setSaving(true)
    const body = {
      entity_id: Number(entityId),
      name: form.name.trim(),
      role: form.role,
    }
    try {
      if (editingId) {
        await fetchAPI(`/accounts/members/${editingId}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        })
        toast.success("멤버가 수정되었습니다")
      } else {
        await fetchAPI("/accounts/members", {
          method: "POST",
          body: JSON.stringify(body),
        })
        toast.success("멤버가 추가되었습니다")
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
      await fetchAPI(`/accounts/members/${deleteTarget.id}`, {
        method: "DELETE",
      })
      toast.success("멤버가 삭제되었습니다")
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
          {Array.from({ length: 5 }).map((_, i) => (
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
            멤버 목록 ({members.length}명)
          </CardTitle>
          <Button size="sm" onClick={handleAdd}>
            <Plus className="mr-1.5 h-4 w-4" />
            멤버 추가
          </Button>
        </CardHeader>
        <CardContent>
          {members.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
              <Users className="mb-3 h-10 w-10 opacity-40" />
              <p className="text-sm">등록된 멤버가 없습니다</p>
              <p className="mt-1 text-xs">
                &quot;멤버 추가&quot; 버튼을 눌러 첫 번째 멤버를 등록해보세요.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>이름</TableHead>
                    <TableHead>역할</TableHead>
                    <TableHead>카드번호</TableHead>
                    <TableHead className="text-right">거래 건수</TableHead>
                    <TableHead className="w-[80px]" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {members.map((member) => {
                    const role = member.role as MemberRole
                    const badgeStyle = ROLE_BADGE_STYLES[role] || ROLE_BADGE_STYLES.staff
                    const roleLabel = ROLE_LABELS[role] || member.role

                    return (
                      <TableRow
                        key={member.id}
                        className="cursor-pointer hover:bg-secondary/50"
                        onClick={() => handleEdit(member)}
                      >
                        <TableCell className="font-medium">
                          {member.name}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={cn("font-normal", badgeStyle)}
                          >
                            {roleLabel}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {member.card_number || (
                            <span className="text-xs text-muted-foreground/50">-</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">
                          -
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-muted-foreground hover:text-destructive"
                            onClick={(e) => {
                              e.stopPropagation()
                              setDeleteTarget(member)
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
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle>
              {editingId ? "멤버 수정" : "멤버 추가"}
            </DialogTitle>
            <DialogDescription>
              {editingId
                ? "멤버 정보를 수정합니다."
                : "새로운 멤버를 등록합니다."}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <label className="text-sm font-medium">이름 *</label>
              <Input
                placeholder="예: 홍길동"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-medium">역할 *</label>
              <Select
                value={form.role}
                onValueChange={(v) =>
                  setForm((f) => ({ ...f, role: v as MemberRole }))
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="역할을 선택하세요" />
                </SelectTrigger>
                <SelectContent>
                  {ROLES.map((r) => (
                    <SelectItem key={r.value} value={r.value}>
                      {r.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
              멤버 삭제
            </DialogTitle>
            <DialogDescription>
              <strong>{deleteTarget?.name}</strong> 멤버를
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

export default function MembersPage() {
  return (
    <div className="space-y-6">
      <Suspense fallback={<Skeleton className="h-10 w-full border-b" />}>
        <EntityTabs />
      </Suspense>

      <div className="flex items-center gap-2">
        <Users className="h-6 w-6 text-muted-foreground" />
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          멤버 관리
        </h1>
      </div>

      <Suspense fallback={<Skeleton className="h-64 w-full" />}>
        <MembersContent />
      </Suspense>
    </div>
  )
}
