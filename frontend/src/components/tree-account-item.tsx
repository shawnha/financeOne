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
  is_recurring: boolean
}

interface TreeAccountItemProps {
  account: TreeAccount
  collapsed: Set<number>
  onToggle: (id: number) => void
  onEdit: (account: TreeAccount) => void
  onDelete: (account: TreeAccount) => void
  onAddChild: (parentId: number) => void
  budgetAmount?: number | null
  onBudgetClick?: (account: TreeAccount) => void
  onToggleRecurring?: (account: TreeAccount) => void
  /** Override is_recurring from forecast data (month-specific) */
  isRecurringOverride?: boolean
}

export function TreeAccountItem({
  account,
  collapsed,
  onToggle,
  onEdit,
  onDelete,
  onAddChild,
  budgetAmount,
  onBudgetClick,
  onToggleRecurring,
  isRecurringOverride,
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
  const isRecurring = isRecurringOverride ?? account.is_recurring

  return (
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

      {/* Recurring toggle */}
      {!account.isRoot && !account.children?.length && onToggleRecurring && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onToggleRecurring(account) }}
          title={isRecurring ? "고정 해제" : "고정으로 설정"}
          className="shrink-0"
        >
          <Badge
            variant="outline"
            className={cn(
              "text-[10px] cursor-pointer transition-colors",
              isRecurring
                ? "border-blue-500/50 text-blue-400 bg-blue-500/10 hover:bg-blue-500/20"
                : "border-muted-foreground/20 text-muted-foreground/40 hover:border-muted-foreground/40 hover:text-muted-foreground/60",
            )}
          >
            고정
          </Badge>
        </button>
      )}

      {/* Budget amount */}
      {budgetAmount !== undefined && budgetAmount !== null && !account.isRoot && (
        <span
          className={cn(
            "text-xs font-mono shrink-0",
            hasChildren
              ? "text-muted-foreground/60"
              : "text-muted-foreground cursor-pointer hover:text-foreground",
          )}
          onClick={(e) => { if (!hasChildren) { e.stopPropagation(); onBudgetClick?.(account) } }}
        >
          {hasChildren && <span className="text-[10px] mr-0.5">Σ</span>}
          ₩{budgetAmount.toLocaleString()}
        </span>
      )}
      {budgetAmount === null && !account.isRoot && !hasChildren && onBudgetClick && (
        <span
          className="text-xs text-muted-foreground/40 cursor-pointer hover:text-muted-foreground shrink-0"
          onClick={(e) => { e.stopPropagation(); onBudgetClick?.(account) }}
        >
          + 예산
        </span>
      )}

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
  )
}

/** Flatten tree to visible items list (respecting collapsed state) */
export function flattenTree(nodes: TreeAccount[], collapsed: Set<number>): TreeAccount[] {
  const result: TreeAccount[] = []
  for (const node of nodes) {
    result.push(node)
    if (node.children.length > 0 && !collapsed.has(node.id)) {
      result.push(...flattenTree(node.children, collapsed))
    }
  }
  return result
}
