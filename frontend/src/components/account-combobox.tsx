"use client"

import { useState, useRef, useEffect, useMemo } from "react"
import { Search, ChevronDown, X } from "lucide-react"
import { cn } from "@/lib/utils"

interface AccountOption {
  id: number
  code: string
  name: string
  parent_id?: number | null
  is_recurring?: boolean
}

interface AccountComboboxProps {
  options: AccountOption[]
  value: string
  onChange: (value: string) => void
  placeholder?: string
  /** Show code in dropdown items (default: false for inline, true for dialog) */
  showCode?: boolean
  /** Compact mode for inline table cells */
  compact?: boolean
  /** Open dropdown automatically on mount */
  autoOpen?: boolean
  /** Open dropdown upward (for bottom bars) */
  dropUp?: boolean
}

export function AccountCombobox({
  options,
  value,
  onChange,
  placeholder = "선택하세요",
  showCode = false,
  compact = false,
  autoOpen = false,
  dropUp = false,
}: AccountComboboxProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const ref = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setSearch("")
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [open])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false)
        setSearch("")
      }
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [open])

  // Auto-open on mount (for inline editing)
  useEffect(() => {
    if (autoOpen) setOpen(true)
  }, [autoOpen])

  // Focus search input when opened
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  // Build tree-ordered list with depth
  const { treeOrdered, depthMap } = useMemo(() => {
    const map = new Map<number, number>()
    const childrenOf = new Map<number, AccountOption[]>()
    const roots: AccountOption[] = []

    for (const o of options) {
      if (!o.parent_id) {
        roots.push(o)
      } else {
        const siblings = childrenOf.get(o.parent_id) || []
        siblings.push(o)
        childrenOf.set(o.parent_id, siblings)
      }
    }

    const ordered: AccountOption[] = []
    const walk = (nodes: AccountOption[], depth: number) => {
      for (const n of nodes) {
        ordered.push(n)
        map.set(n.id, depth)
        const children = childrenOf.get(n.id)
        if (children) walk(children, depth + 1)
      }
    }
    walk(roots, 0)

    return { treeOrdered: ordered, depthMap: map }
  }, [options])

  // Filter options by search — matching items + their children + their parents
  const filtered = useMemo(() => {
    if (!search) return treeOrdered
    const q = search.toLowerCase()

    const directMatches = new Set<number>()
    for (const o of treeOrdered) {
      if (o.code.toLowerCase().includes(q) || o.name.toLowerCase().includes(q)) {
        directMatches.add(o.id)
      }
    }

    const includeIds = new Set(directMatches)
    for (const o of treeOrdered) {
      if (o.parent_id && includeIds.has(o.parent_id)) {
        includeIds.add(o.id)
      }
    }

    for (const o of treeOrdered) {
      if (includeIds.has(o.id) && o.parent_id) {
        let pid: number | null | undefined = o.parent_id
        while (pid) {
          includeIds.add(pid)
          const parent = treeOrdered.find(p => p.id === pid)
          pid = parent?.parent_id
        }
      }
    }

    return treeOrdered.filter(o => includeIds.has(o.id))
  }, [treeOrdered, search])

  const ROOT_CODES = ["INC", "EXP"]

  // Selected display
  const selected = options.find((o) => String(o.id) === value)

  return (
    <div ref={ref} className="relative">
      {/* Trigger */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          "flex items-center justify-between w-full rounded-md border border-input bg-background",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          "hover:bg-muted/30 transition-colors",
          compact ? "h-7 px-2 text-xs" : "h-9 px-3 text-sm",
          !selected && "text-muted-foreground",
        )}
      >
        <span className="truncate">
          {selected ? selected.name : placeholder}
        </span>
        <div className="flex items-center gap-0.5 shrink-0 ml-1">
          {selected && (
            <span
              role="button"
              onClick={(e) => {
                e.stopPropagation()
                onChange("")
                setOpen(false)
              }}
              className="p-0.5 rounded hover:bg-muted/50 text-muted-foreground"
            >
              <X className="h-3 w-3" />
            </span>
          )}
          <ChevronDown className={cn("h-3 w-3 text-muted-foreground transition-transform", open && "rotate-180")} />
        </div>
      </button>

      {/* Dropdown — fixed min-width so it doesn't get squished in table cells */}
      {open && (
        <div className={cn(
          "absolute left-0 z-50 min-w-[260px] rounded-lg border border-border bg-popover shadow-xl animate-in fade-in-0 zoom-in-95 duration-150",
          dropUp ? "bottom-full mb-1" : "top-full mt-1",
        )}>
          {/* Search input */}
          <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
            <Search className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            <input
              ref={inputRef}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="계정명 검색..."
              className="flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground/50"
            />
          </div>

          {/* Options list */}
          <div className="max-h-[240px] overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <div className="px-3 py-4 text-center text-xs text-muted-foreground">
                검색 결과가 없습니다
              </div>
            ) : (
              filtered.map((opt) => {
                const depth = depthMap.get(opt.id) ?? 0
                const isGroupHeader = ROOT_CODES.includes(opt.code)
                const isCategory = depth === 1 && treeOrdered.some((o) => o.parent_id === opt.id)
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
                      "w-full text-left px-3 py-1.5 text-xs transition-colors flex items-center",
                      "hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none",
                      isSelected && "bg-accent/20 text-accent-foreground font-medium",
                      "pl-6",
                    )}
                  >
                    <span className="text-muted-foreground/40 mr-1">└</span>
                    <span className="flex-1">{opt.name}</span>
                    {opt.is_recurring && (
                      <span className="text-[9px] text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded ml-2 shrink-0">반복</span>
                    )}
                    {showCode && (
                      <span className="text-muted-foreground/50 text-[10px] ml-2 shrink-0">{opt.code}</span>
                    )}
                  </button>
                )
              })
            )}
          </div>
        </div>
      )}
    </div>
  )
}
