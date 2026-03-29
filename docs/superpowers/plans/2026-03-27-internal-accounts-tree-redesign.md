# Internal Accounts Tree Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 내부계정을 회계사 언어(IA-xxx) → 일상 업무 언어(수입/비용 트리)로 재설계하고, 드래그앤드롭 트리 UI + 표준계정 매핑 + 거래내역 트리 반영까지 구현

**Architecture:** DB 스키마는 변경 없음 (parent_id 계층 그대로 활용). Seed 데이터를 수입/비용 2-top 구조로 교체. 프론트엔드는 @dnd-kit 기반 트리 UI, AccountCombobox는 그룹핑된 트리 드롭다운으로 개선. 표준계정 페이지에 내부계정 매핑 컬럼 추가.

**Tech Stack:** Next.js 14 / @dnd-kit/core + @dnd-kit/sortable / FastAPI / Supabase PostgreSQL

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `backend/database/seed.py` | 수입/비용 트리 seed 데이터 |
| Modify | `backend/routers/accounts.py` | 내부계정 순서 bulk-update API, 표준계정에 매핑 정보 포함 |
| Create | `frontend/src/components/tree-account-item.tsx` | 드래그 가능한 트리 노드 컴포넌트 |
| Modify | `frontend/src/app/accounts/internal/page.tsx` | 테이블 → @dnd-kit 트리 UI 전면 교체 |
| Modify | `frontend/src/app/accounts/standard/page.tsx` | 내부계정 매핑 컬럼 + 매핑 편집 기능 |
| Modify | `frontend/src/components/account-combobox.tsx` | 트리 그룹핑 드롭다운 |

---

### Task 1: Seed 데이터 — 수입/비용 트리 구조

**Files:**
- Modify: `backend/database/seed.py:228-293`

- [ ] **Step 1: seed.py 내부계정 데이터를 수입/비용 트리로 교체**

기존 `internal_accounts` 리스트를 아래로 교체. 코드 체계: `INC-xxx` (수입), `EXP-xxx` (비용). 2레벨=카테고리, 3레벨=구체 항목.

```python
    # 6. internal_accounts — 내부 계정 (수입/비용 트리 구조)
    # --------------------------------------------------
    # (코드, 이름, 표준계정코드, 부모코드)
    # 코드 자동 생성 — 사용자에게 노출 안 됨
    internal_accounts = [
        # ── 수입 (최상위, 드래그 불가) ──
        ("INC", "수입", None, None),
        ("INC-001", "매출", "40100", "INC"),
        ("INC-002", "서비스매출", "40200", "INC"),
        ("INC-003", "이자수익", "40300", "INC"),
        ("INC-004", "기타수입", "40600", "INC"),

        # ── 비용 (최상위, 드래그 불가) ──
        ("EXP", "비용", None, None),

        # 인건비
        ("EXP-010", "인건비", "50200", "EXP"),
        ("EXP-010-001", "급여", "50200", "EXP-010"),
        ("EXP-010-002", "퇴직금", "50300", "EXP-010"),
        ("EXP-010-003", "4대보험", "50400", "EXP-010"),

        # 사무실
        ("EXP-020", "사무실", "50500", "EXP"),
        ("EXP-020-001", "임차료", "50500", "EXP-020"),
        ("EXP-020-002", "관리비", "50800", "EXP-020"),
        ("EXP-020-003", "통신비", "50700", "EXP-020"),

        # 식비/복리후생
        ("EXP-030", "식비/복리후생", "50400", "EXP"),
        ("EXP-030-001", "점심", "50400", "EXP-030"),
        ("EXP-030-002", "간식/커피", "50400", "EXP-030"),
        ("EXP-030-003", "회식", "50600", "EXP-030"),

        # 교통
        ("EXP-040", "교통", "51300", "EXP"),
        ("EXP-040-001", "택시", "51300", "EXP-040"),
        ("EXP-040-002", "주차", "51300", "EXP-040"),
        ("EXP-040-003", "출장", "51300", "EXP-040"),

        # 마케팅
        ("EXP-050", "마케팅", "51600", "EXP"),
        ("EXP-050-001", "광고비", "51600", "EXP-050"),
        ("EXP-050-002", "인플루언서", "51600", "EXP-050"),
        ("EXP-050-003", "이벤트", "51600", "EXP-050"),

        # IT/SaaS
        ("EXP-060", "IT/SaaS", "51510", "EXP"),
        ("EXP-060-001", "ChatGPT", "51510", "EXP-060"),
        ("EXP-060-002", "Cursor", "51510", "EXP-060"),
        ("EXP-060-003", "Google Workspace", "51510", "EXP-060"),
        ("EXP-060-004", "AWS", "51510", "EXP-060"),
        ("EXP-060-005", "기타 구독", "51510", "EXP-060"),

        # 수수료
        ("EXP-070", "수수료", "51500", "EXP"),
        ("EXP-070-001", "카드수수료", "51500", "EXP-070"),
        ("EXP-070-002", "결제수수료", "51520", "EXP-070"),
        ("EXP-070-003", "배달수수료", "51530", "EXP-070"),

        # 세금/공과
        ("EXP-080", "세금/공과", "50900", "EXP"),
        ("EXP-080-001", "부가세", "50900", "EXP-080"),
        ("EXP-080-002", "법인세", "50900", "EXP-080"),

        # 기타비용
        ("EXP-090", "기타비용", "52300", "EXP"),
    ]
```

주의: `INC`, `EXP` 최상위 노드는 `standard_account_id`가 없음(None). seed 코드에서 standard_accounts JOIN이 결과 없으면 INSERT 안 되므로, 최상위 노드 처리를 별도로 해야 함.

- [ ] **Step 2: seed.py의 INSERT 로직을 최상위 노드 지원하도록 수정**

기존 seed 로직(line 273-292)을 교체:

```python
    for entity_id in [1, 2, 3]:
        # Pass 1: insert all accounts without parent
        for idx, (code, name, std_code, _parent) in enumerate(internal_accounts):
            if std_code:
                cur.execute("""
                    INSERT INTO internal_accounts (entity_id, code, name, standard_account_id, sort_order)
                    SELECT %s, %s, %s, sa.id, %s
                    FROM standard_accounts sa WHERE sa.code = %s
                    ON CONFLICT (entity_id, code) DO NOTHING
                """, (entity_id, code, name, (idx + 1) * 100, std_code))
            else:
                # 최상위 노드 (수입/비용) — standard_account 없음
                cur.execute("""
                    INSERT INTO internal_accounts (entity_id, code, name, standard_account_id, sort_order)
                    VALUES (%s, %s, %s, NULL, %s)
                    ON CONFLICT (entity_id, code) DO NOTHING
                """, (entity_id, code, name, (idx + 1) * 100))

        # Pass 2: set parent_id for hierarchical accounts
        for code, _name, _std, parent_code in internal_accounts:
            if parent_code:
                cur.execute("""
                    UPDATE internal_accounts c
                    SET parent_id = p.id
                    FROM internal_accounts p
                    WHERE c.entity_id = %s AND c.code = %s
                      AND p.entity_id = %s AND p.code = %s
                """, (entity_id, code, entity_id, parent_code))
```

- [ ] **Step 3: Supabase에서 기존 내부계정 데이터 교체**

기존 거래에 매핑된 내부계정이 있을 수 있으므로, 기존 데이터를 비활성화하고 새로 seed:

```bash
source .venv/bin/activate && python3 -c "
from backend.database.connection import get_db_connection
conn = get_db_connection()
cur = conn.cursor()
# 기존 내부계정 비활성화 (거래 참조 유지)
cur.execute('UPDATE internal_accounts SET is_active = false')
conn.commit()
cur.close()
conn.close()
print('기존 내부계정 비활성화 완료')
"
```

그 다음 seed 실행:

```bash
source .venv/bin/activate && python3 -c "
from backend.database.seed import seed
seed()
"
```

- [ ] **Step 4: 데이터 확인**

```bash
source .venv/bin/activate && python3 -c "
from backend.database.connection import get_db_connection
conn = get_db_connection()
cur = conn.cursor()
cur.execute('''
    SELECT ia.code, ia.name, p.code as parent_code, ia.sort_order
    FROM internal_accounts ia
    LEFT JOIN internal_accounts p ON ia.parent_id = p.id AND p.entity_id = ia.entity_id
    WHERE ia.entity_id = 2 AND ia.is_active = true
    ORDER BY ia.sort_order
''')
for row in cur.fetchall():
    print(row)
cur.close()
conn.close()
"
```

Expected: `INC` → 하위 4개, `EXP` → 하위 카테고리 9개 → 각 하위 항목들. 총 약 40개.

- [ ] **Step 5: Commit**

```bash
git add backend/database/seed.py
git commit -m "feat: 내부계정 seed를 수입/비용 트리 구조로 재설계"
```

---

### Task 2: @dnd-kit 설치 + 트리 노드 컴포넌트

**Files:**
- Create: `frontend/src/components/tree-account-item.tsx`

- [ ] **Step 1: @dnd-kit 패키지 설치**

```bash
cd frontend && npm install @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities
```

- [ ] **Step 2: 트리 노드 컴포넌트 생성**

```tsx
// frontend/src/components/tree-account-item.tsx
"use client"

import { useSortable } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { cn } from "@/lib/utils"
import { GripVertical, Pencil, Trash2, ChevronRight, ChevronDown, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

export interface TreeAccount {
  id: number
  code: string
  name: string
  parent_id: number | null
  sort_order: number
  standard_code: string | null
  standard_name: string | null
  depth: number
  children: TreeAccount[]
  isRoot: boolean // INC or EXP — not draggable
}

interface TreeAccountItemProps {
  account: TreeAccount
  collapsed: Set<number>
  onToggle: (id: number) => void
  onEdit: (account: TreeAccount) => void
  onDelete: (account: TreeAccount) => void
  onAddChild: (parentId: number) => void
}

export function TreeAccountItem({
  account,
  collapsed,
  onToggle,
  onEdit,
  onDelete,
  onAddChild,
}: TreeAccountItemProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: account.id,
    disabled: account.isRoot,
  })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  }

  const hasChildren = account.children.length > 0
  const isCollapsed = collapsed.has(account.id)

  return (
    <>
      <div
        ref={setNodeRef}
        style={style}
        className={cn(
          "flex items-center gap-2 py-1.5 px-2 rounded-md group",
          "hover:bg-muted/40 transition-colors",
          isDragging && "opacity-50 bg-muted/60 shadow-lg z-50",
          account.isRoot && "bg-muted/20 font-semibold",
        )}
      >
        {/* Drag handle — hidden for root nodes */}
        {!account.isRoot ? (
          <span
            {...attributes}
            {...listeners}
            className="cursor-grab active:cursor-grabbing text-muted-foreground/40 hover:text-muted-foreground"
          >
            <GripVertical className="h-4 w-4" />
          </span>
        ) : (
          <span className="w-4" />
        )}

        {/* Indentation */}
        <span style={{ width: `${account.depth * 20}px` }} className="shrink-0" />

        {/* Expand/collapse toggle */}
        {hasChildren ? (
          <button
            type="button"
            onClick={() => onToggle(account.id)}
            className="p-0.5 rounded hover:bg-muted/60 text-muted-foreground"
          >
            {isCollapsed ? (
              <ChevronRight className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
          </button>
        ) : (
          <span className="w-[18px]" />
        )}

        {/* Name */}
        <span className={cn(
          "flex-1 text-sm truncate",
          account.isRoot && "text-base font-medium",
        )}>
          {account.name}
        </span>

        {/* Standard account badge */}
        {account.standard_code && !account.isRoot && (
          <Badge variant="secondary" className="font-normal text-[10px] shrink-0 opacity-60 group-hover:opacity-100">
            {account.standard_code}
          </Badge>
        )}

        {/* Actions — hidden until hover */}
        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => onAddChild(account.id)}
            title="하위 항목 추가"
          >
            <Plus className="h-3 w-3" />
          </Button>
          {!account.isRoot && (
            <>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={() => onEdit(account)}
                title="수정"
              >
                <Pencil className="h-3 w-3" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground hover:text-destructive"
                onClick={() => onDelete(account)}
                title="삭제"
              >
                <Trash2 className="h-3 w-3" />
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Render children recursively if not collapsed */}
      {hasChildren && !isCollapsed && account.children.map((child) => (
        <TreeAccountItem
          key={child.id}
          account={child}
          collapsed={collapsed}
          onToggle={onToggle}
          onEdit={onEdit}
          onDelete={onDelete}
          onAddChild={onAddChild}
        />
      ))}
    </>
  )
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/tree-account-item.tsx frontend/package.json frontend/package-lock.json
git commit -m "feat: @dnd-kit 설치 + TreeAccountItem 컴포넌트"
```

---

### Task 3: 백엔드 — 순서 bulk-update API + 표준계정 매핑 조회

**Files:**
- Modify: `backend/routers/accounts.py`

- [ ] **Step 1: 순서 bulk-update API 추가**

`accounts.py`의 `delete_internal_account` 함수 다음 (line 236 이후)에 추가:

```python
class SortOrderItem(BaseModel):
    id: int
    sort_order: int
    parent_id: Optional[int] = None


class BulkSortOrderUpdate(BaseModel):
    items: list[SortOrderItem]


@router.put("/internal/sort-order")
def bulk_update_sort_order(
    body: BulkSortOrderUpdate,
    conn: PgConnection = Depends(get_db),
):
    """드래그앤드롭 후 전체 순서 + 부모 일괄 업데이트"""
    cur = conn.cursor()
    try:
        for item in body.items:
            cur.execute(
                """
                UPDATE internal_accounts
                SET sort_order = %s, parent_id = %s
                WHERE id = %s
                """,
                [item.sort_order, item.parent_id, item.id],
            )
        conn.commit()
        return {"updated": len(body.items)}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()
```

- [ ] **Step 2: 표준계정 목록 API에 매핑된 내부계정 정보 포함**

기존 `list_standard_accounts` 함수를 교체:

```python
@router.get("/standard")
def list_standard_accounts(
    entity_id: Optional[int] = None,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    if entity_id is not None:
        cur.execute(
            """
            SELECT sa.id, sa.code, sa.name, sa.category, sa.subcategory,
                   sa.normal_side, sa.sort_order,
                   ia.id AS mapped_internal_id,
                   ia.name AS mapped_internal_name,
                   ia.code AS mapped_internal_code
            FROM standard_accounts sa
            LEFT JOIN internal_accounts ia
              ON ia.standard_account_id = sa.id
              AND ia.entity_id = %s
              AND ia.is_active = true
            WHERE sa.is_active = true
            ORDER BY sa.sort_order, sa.code
            """,
            [entity_id],
        )
    else:
        cur.execute(
            "SELECT id, code, name, category, subcategory, normal_side, sort_order "
            "FROM standard_accounts WHERE is_active = true ORDER BY sort_order, code"
        )
    rows = fetch_all(cur)
    cur.close()
    return rows
```

- [ ] **Step 3: 서버 실행 후 API 확인**

```bash
source .venv/bin/activate && uvicorn backend.main:app --reload &
sleep 2
curl -s http://localhost:8000/api/accounts/standard?entity_id=2 | python3 -m json.tool | head -30
curl -s http://localhost:8000/api/accounts/internal?entity_id=2 | python3 -m json.tool | head -30
kill %1
```

Expected: 표준계정에 `mapped_internal_id`, `mapped_internal_name`, `mapped_internal_code` 필드 포함. 내부계정은 새 트리 구조.

- [ ] **Step 4: Commit**

```bash
git add backend/routers/accounts.py
git commit -m "feat: 내부계정 순서 bulk-update API + 표준계정 매핑 조회"
```

---

### Task 4: 내부계정 관리 → 드래그앤드롭 트리 UI

**Files:**
- Modify: `frontend/src/app/accounts/internal/page.tsx` (전면 교체)

- [ ] **Step 1: 내부계정 페이지 전면 교체**

기존 테이블 UI → @dnd-kit 트리 UI. 파일 전체를 아래로 교체:

```tsx
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
  useSensor,
  useSensors,
  DragEndEvent,
} from "@dnd-kit/core"
import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable"

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
import { AlertTriangle, FolderTree, Plus } from "lucide-react"
import { TreeAccountItem, type TreeAccount } from "@/components/tree-account-item"

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
        children: walk(a.id, depth + 1),
      }))
  }
  return walk(null, 0)
}

/** Flatten tree to a list of all IDs for SortableContext */
function flattenIds(nodes: TreeAccount[], collapsed: Set<number>): number[] {
  const ids: number[] = []
  for (const node of nodes) {
    ids.push(node.id)
    if (!collapsed.has(node.id)) {
      ids.push(...flattenIds(node.children, collapsed))
    }
  }
  return ids
}

/** Flatten tree to a list of {id, sort_order, parent_id} for bulk update */
function flattenForUpdate(nodes: TreeAccount[], parentId: number | null): { id: number; sort_order: number; parent_id: number | null }[] {
  const result: { id: number; sort_order: number; parent_id: number | null }[] = []
  nodes.forEach((node, idx) => {
    result.push({ id: node.id, sort_order: (idx + 1) * 100, parent_id: parentId })
    result.push(...flattenForUpdate(node.children, node.id))
  })
  return result
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

  // DnD sensor — small activation distance to prevent accidental drags
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  )

  // Fetch accounts
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

  const tree = useMemo(() => buildTree(accounts), [accounts])
  const sortableIds = useMemo(() => flattenIds(tree, collapsed), [tree, collapsed])

  // Toggle collapse
  const handleToggle = (id: number) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // DnD handler — reorder within same parent
  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return

    const activeId = active.id as number
    const overId = over.id as number

    // Find both items in flat accounts
    const activeItem = accounts.find((a) => a.id === activeId)
    const overItem = accounts.find((a) => a.id === overId)
    if (!activeItem || !overItem) return

    // Only allow reorder within same parent
    if (activeItem.parent_id !== overItem.parent_id) {
      toast.error("같은 그룹 내에서만 순서를 변경할 수 있습니다")
      return
    }

    // Don't allow moving root nodes
    if (ROOT_CODES.includes(activeItem.code)) return

    // Get siblings, reorder
    const siblings = accounts
      .filter((a) => a.parent_id === activeItem.parent_id)
      .sort((a, b) => a.sort_order - b.sort_order)

    const oldIndex = siblings.findIndex((s) => s.id === activeId)
    const newIndex = siblings.findIndex((s) => s.id === overId)
    if (oldIndex === -1 || newIndex === -1) return

    // Reorder array
    const reordered = [...siblings]
    const [moved] = reordered.splice(oldIndex, 1)
    reordered.splice(newIndex, 0, moved)

    // Build bulk update
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
      load() // rollback
    }
  }

  // Add child — pre-fill parent_id
  const handleAddChild = (parentId: number) => {
    setEditingId(null)
    setForm({ ...EMPTY_FORM, parent_id: String(parentId) })
    setDialogOpen(true)
  }

  // Edit
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

  // Save
  const handleSave = async () => {
    if (!form.name.trim()) {
      toast.error("계정명은 필수입니다")
      return
    }
    setSaving(true)

    // Auto-generate code for new accounts
    const parentId = form.parent_id ? Number(form.parent_id) : null
    const parent = parentId ? accounts.find((a) => a.id === parentId) : null
    const siblings = accounts.filter((a) => a.parent_id === parentId)
    const nextSort = siblings.length > 0
      ? Math.max(...siblings.map((s) => s.sort_order)) + 100
      : 100

    // Generate code: parent code + next number
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
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base font-medium">
            내부 계정과목 ({accounts.length}건)
          </CardTitle>
          <Button size="sm" onClick={() => {
            setEditingId(null)
            setForm(EMPTY_FORM)
            setDialogOpen(true)
          }}>
            <Plus className="mr-1.5 h-4 w-4" />
            계정 추가
          </Button>
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
            >
              <SortableContext items={sortableIds} strategy={verticalListSortingStrategy}>
                <div className="space-y-0.5">
                  {tree.map((node) => (
                    <TreeAccountItem
                      key={node.id}
                      account={node}
                      collapsed={collapsed}
                      onToggle={handleToggle}
                      onEdit={handleEdit}
                      onDelete={(a) => setDeleteTarget(a as unknown as RawAccount)}
                      onAddChild={handleAddChild}
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
```

- [ ] **Step 2: 프론트엔드 빌드 확인**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: Build 성공, 에러 없음.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/accounts/internal/page.tsx
git commit -m "feat: 내부계정 관리 → 드래그앤드롭 트리 UI (@dnd-kit)"
```

---

### Task 5: 표준계정 페이지 — 내부계정 매핑 기능

**Files:**
- Modify: `frontend/src/app/accounts/standard/page.tsx`

- [ ] **Step 1: 표준계정 페이지에 매핑 컬럼 + 편집 기능 추가**

표준계정 테이블에 "내부계정 매핑" 컬럼을 추가하고, 클릭 시 내부계정을 선택할 수 있는 드롭다운 표시. `useSearchParams`로 entity_id를 받아 매핑 정보 조회.

`StandardAccount` 타입에 매핑 필드 추가:

```tsx
interface StandardAccount {
  id: number
  code: string
  name: string
  category: string
  subcategory: string
  normal_side: string
  sort_order: number
  mapped_internal_id: number | null
  mapped_internal_name: string | null
  mapped_internal_code: string | null
}
```

`StandardAccountsContent` 함수에 내부계정 목록 fetch + 매핑 업데이트 핸들러 추가:

```tsx
const [internalAccounts, setInternalAccounts] = useState<{ id: number; code: string; name: string; parent_id: number | null }[]>([])

// entity_id 기반 fetch
const searchParams = useSearchParams()
const entityId = searchParams.get("entity")

useEffect(() => {
  if (entityId) {
    fetchAPI<{ id: number; code: string; name: string; parent_id: number | null }[]>(
      `/accounts/internal?entity_id=${entityId}`
    ).then(setInternalAccounts).catch(() => {})
  }
}, [entityId])

// standard accounts fetch도 entity_id 포함
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

// 매핑 변경 — 내부계정의 standard_account_id를 업데이트
const handleMappingChange = async (
  standardAccountId: number,
  internalAccountId: number | null,
  previousInternalId: number | null,
) => {
  try {
    // 기존 매핑 해제
    if (previousInternalId) {
      await fetchAPI(`/accounts/internal/${previousInternalId}`, {
        method: "PATCH",
        body: JSON.stringify({ standard_account_id: null }),
      })
    }
    // 새 매핑 설정
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
```

테이블 헤더에 "내부계정" 컬럼 추가, 각 행에 `AccountCombobox`로 매핑 선택:

```tsx
import { AccountCombobox } from "@/components/account-combobox"

// TableHead 추가 (차변/대변 뒤에)
<TableHead className="w-[180px]">내부계정</TableHead>

// TableCell 추가 (각 account row에)
<TableCell onClick={(e) => e.stopPropagation()}>
  {entityId ? (
    <AccountCombobox
      options={internalAccounts}
      value={account.mapped_internal_id ? String(account.mapped_internal_id) : ""}
      onChange={(v) => {
        handleMappingChange(
          account.id,
          v ? Number(v) : null,
          account.mapped_internal_id,
        )
      }}
      placeholder="매핑 선택"
      compact
    />
  ) : (
    <span className="text-xs text-muted-foreground">법인 선택 필요</span>
  )}
</TableCell>
```

"읽기 전용" 배지를 조건부로 변경 — entity 선택 시 매핑 편집 가능:

```tsx
// Page header에서 읽기 전용 배지를 조건부로
{!entityId && (
  <Badge variant="outline" className="text-xs text-muted-foreground">
    읽기 전용
  </Badge>
)}
```

- [ ] **Step 2: 프론트엔드 빌드 확인**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: Build 성공.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/accounts/standard/page.tsx
git commit -m "feat: 표준계정 페이지에 내부계정 ↔ 표준계정 매핑 기능"
```

---

### Task 6: AccountCombobox — 트리 그룹핑 드롭다운

**Files:**
- Modify: `frontend/src/components/account-combobox.tsx`

- [ ] **Step 1: AccountCombobox에 트리 그룹핑 표시 추가**

드롭다운에서 최상위 노드(수입/비용)를 그룹 헤더로, 2레벨을 카테고리 구분자로 표시. 3레벨 항목만 선택 가능.

`AccountOption` 인터페이스에 `depth` 추가 (optional, 하위 호환):

```tsx
interface AccountOption {
  id: number
  code: string
  name: string
  parent_id?: number | null
  depth?: number
}
```

필터 로직 후 렌더링 부분을 수정하여 계층 표시:

```tsx
// Build depth map from parent_id relationships
const depthMap = useMemo(() => {
  const map = new Map<number, number>()
  const roots = options.filter((o) => !o.parent_id)
  roots.forEach((r) => map.set(r.id, 0))

  // BFS to assign depths
  let changed = true
  while (changed) {
    changed = false
    for (const opt of options) {
      if (opt.parent_id && map.has(opt.parent_id) && !map.has(opt.id)) {
        map.set(opt.id, (map.get(opt.parent_id) || 0) + 1)
        changed = true
      }
    }
  }
  return map
}, [options])

// Root codes that should be rendered as group headers (not selectable)
const ROOT_CODES = ["INC", "EXP"]
```

드롭다운 항목 렌더링을 그룹 구조로:

```tsx
filtered.map((opt) => {
  const depth = depthMap.get(opt.id) ?? 0
  const isGroupHeader = ROOT_CODES.includes(opt.code)
  const isCategory = depth === 1 && options.some((o) => o.parent_id === opt.id)
  const isSelected = String(opt.id) === value

  // Group header (수입/비용) — not selectable
  if (isGroupHeader) {
    return (
      <div
        key={opt.id}
        className="px-3 py-1.5 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider border-t first:border-t-0 mt-1 first:mt-0"
      >
        {opt.name}
      </div>
    )
  }

  // Category header (인건비, IT/SaaS 등) — selectable but styled differently
  if (isCategory) {
    return (
      <button
        key={opt.id}
        type="button"
        onClick={() => {
          onChange(String(opt.id))
          setOpen(false)
          setSearch("")
        }}
        className={cn(
          "w-full text-left px-3 py-1.5 text-xs font-medium transition-colors",
          "hover:bg-muted/40",
          isSelected && "bg-accent/20 text-accent-foreground",
        )}
      >
        {opt.name}
        {showCode && (
          <span className="text-muted-foreground/50 text-[10px] ml-2">{opt.code}</span>
        )}
      </button>
    )
  }

  // Leaf item — fully selectable
  return (
    <button
      key={opt.id}
      type="button"
      onClick={() => {
        onChange(String(opt.id))
        setOpen(false)
        setSearch("")
      }}
      className={cn(
        "w-full text-left px-3 py-1.5 text-xs transition-colors",
        "hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none",
        isSelected && "bg-accent/20 text-accent-foreground font-medium",
        "pl-6",
      )}
    >
      <span className="text-muted-foreground/40 mr-1">└</span>
      {opt.name}
      {showCode && (
        <span className="text-muted-foreground/50 text-[10px] ml-2">{opt.code}</span>
      )}
    </button>
  )
})
```

- [ ] **Step 2: 프론트엔드 빌드 확인**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: Build 성공.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/account-combobox.tsx
git commit -m "feat: AccountCombobox 트리 그룹핑 드롭다운 (수입/비용 헤더)"
```

---

## Self-Review Checklist

1. **Spec coverage:** Seed 재설계(Task 1) + @dnd-kit 설치(Task 2) + 백엔드 API(Task 3) + 트리 UI(Task 4) + 표준계정 매핑(Task 5) + AccountCombobox(Task 6) — 4가지 요구사항 모두 커버
2. **Placeholder scan:** 모든 step에 실제 코드 포함, TBD/TODO 없음
3. **Type consistency:** `TreeAccount`, `RawAccount`, `AccountOption` 타입이 task 간 일관
