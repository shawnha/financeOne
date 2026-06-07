"use client"

import { useState, useRef, useEffect, useMemo, useCallback } from "react"
import { createPortal } from "react-dom"
import { Search, ChevronDown, X, Plus } from "lucide-react"
import { cn } from "@/lib/utils"

interface AccountOption {
  id: number
  code: string
  name: string
  parent_id?: number | null
  is_recurring?: boolean
  subcategory?: string | null
  // 표준 골격 기반 그룹핑용 (있으면 표준 기준, 없으면 parent_id 트리 fallback)
  standard_code?: string | null
  standard_name?: string | null
  standard_category?: string | null
  standard_account_id?: number | null
  standard_sort_order?: number | null
}

const CAT_ORDER = ["자산", "부채", "자본", "수익", "매출", "매출원가", "비용", "기타"]

// 표준계정 code 앞자리로 K-GAAP 카테고리 라벨 결정
function saCategoryLabel(code: string): string | null {
  if (!code || !/^\d/.test(code)) return null
  const p = code[0]
  if (p === '1') return '자산'
  if (p === '2') return '부채'
  if (p === '3') return '자본'
  if (p === '4') return '매출'
  if (p === '5') return '매출원가'
  if (p === '8') return '판관비'
  if (p === '9') return '영업외'
  return null
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
  /** Callback to create a new account inline. If provided, shows "+ 새 계정 추가" button */
  onCreateAccount?: (name: string, parentId: number | null) => Promise<AccountOption | null>
  /** Extra classes appended to the trigger button (use to match filter chip styling, etc.) */
  triggerClassName?: string
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
  onCreateAccount,
  triggerClassName,
}: AccountComboboxProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const [dropdownStyle, setDropdownStyle] = useState<React.CSSProperties>({})
  const [mounted, setMounted] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Client-side mount check for portal
  useEffect(() => { setMounted(true) }, [])

  // Find the nearest dialog/modal as portal container, fallback to body
  const [portalContainer, setPortalContainer] = useState<HTMLElement | null>(null)
  useEffect(() => {
    if (!mounted || !ref.current) { setPortalContainer(document.body); return }
    // Radix Dialog renders inside [role="dialog"]
    const dialog = ref.current.closest("[role='dialog']")
    setPortalContainer((dialog as HTMLElement) ?? document.body)
  }, [mounted])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      const target = e.target as Node
      if (ref.current && !ref.current.contains(target) && dropdownRef.current && !dropdownRef.current.contains(target)) {
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

  // Position dropdown using fixed positioning via portal to body
  useEffect(() => {
    if (!open || !ref.current) return

    const update = () => {
      if (!ref.current) return
      const rect = ref.current.getBoundingClientRect()
      const spaceBelow = window.innerHeight - rect.bottom
      const openUp = dropUp || spaceBelow < 300

      // When portaling into a transformed container (e.g. Radix Dialog with translate),
      // fixed positioning is relative to the container, not viewport.
      // Compute offset by comparing container's getBoundingClientRect with its position.
      let offsetX = 0
      let offsetY = 0
      if (portalContainer && portalContainer !== document.body) {
        const containerRect = portalContainer.getBoundingClientRect()
        offsetX = containerRect.left
        offsetY = containerRect.top
      }

      const style: React.CSSProperties = {
        position: "fixed",
        left: rect.left - offsetX,
        minWidth: Math.max(340, rect.width),
        zIndex: 99999,
      }

      if (openUp) {
        style.bottom = window.innerHeight - rect.top - offsetY
      } else {
        style.top = rect.bottom - offsetY + 4
      }

      setDropdownStyle(style)
    }

    update()
    setTimeout(() => inputRef.current?.focus(), 50)

    // Reposition on scroll in any ancestor
    const ancestors: Element[] = []
    let el: Element | null = ref.current
    while (el) {
      if (el.scrollHeight > el.clientHeight || el.scrollWidth > el.clientWidth) {
        ancestors.push(el)
        el.addEventListener("scroll", update)
      }
      el = el.parentElement
    }
    window.addEventListener("resize", update)

    return () => {
      ancestors.forEach(a => a.removeEventListener("scroll", update))
      window.removeEventListener("resize", update)
    }
  }, [open, dropUp, portalContainer])

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

    // 띄어쓰기 무시 매칭
    const normalize = (s: string) => s.toLowerCase().replace(/\s+/g, "")
    const qn = normalize(q)
    const directMatches = new Set<number>()
    for (const o of treeOrdered) {
      const cat = saCategoryLabel(o.code) || ""
      if (
        normalize(o.code).includes(qn) ||
        normalize(o.name).includes(qn) ||
        normalize(cat).includes(qn)
      ) {
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

  // 표준 골격 기반 그룹핑 렌더 — 옵션에 표준정보 있으면 카테고리>표준>잎, 없으면 parent_id fallback
  const hasStandard = useMemo(() => options.some(o => o.standard_account_id != null), [options])
  type StdRow =
    | { kind: "std"; key: string; code: string; name: string }
    | { kind: "leaf"; key: string; opt: AccountOption; groupName: string | null }
  const stdRows = useMemo<StdRow[]>(() => {
    if (!hasStandard) return []
    const norm = (s: string) => s.toLowerCase().replace(/\s+/g, "")
    const hasChild = new Set<number>()
    for (const o of options) if (o.parent_id != null) hasChild.add(o.parent_id)
    const byId = new Map(options.map(o => [o.id, o]))
    const isContainer = (o: AccountOption) => ROOT_CODES.includes(o.code) || ["지출", "수입"].includes(o.name)
    const groupNameOf = (o: AccountOption): string | null => {
      if (o.parent_id == null) return null
      const p = byId.get(o.parent_id)
      return !p || isContainer(p) ? null : p.name
    }
    const leaves = options.filter(o => !hasChild.has(o.id) && !ROOT_CODES.includes(o.code))
    const byStd = new Map<number, AccountOption[]>()
    const unmapped: AccountOption[] = []
    for (const lf of leaves) {
      if (lf.standard_account_id == null) { unmapped.push(lf); continue }
      const l = byStd.get(lf.standard_account_id) || []
      l.push(lf); byStd.set(lf.standard_account_id, l)
    }
    const stds = [...byStd.entries()].map(([sid, lvs]) => ({
      sid, code: lvs[0].standard_code || "", name: lvs[0].standard_name || "",
      cat: lvs[0].standard_category || "기타", sort: lvs[0].standard_sort_order ?? 0, leaves: lvs,
    }))
    stds.sort((a, b) => {
      const ca = CAT_ORDER.indexOf(a.cat), cb = CAT_ORDER.indexOf(b.cat)
      if (ca !== cb) return (ca < 0 ? 99 : ca) - (cb < 0 ? 99 : cb)
      return a.sort - b.sort || a.code.localeCompare(b.code)
    })
    const q = search ? norm(search) : ""
    const rows: StdRow[] = []
    for (const st of stds) {
      const lvs = q
        ? st.leaves.filter(l => norm(l.name).includes(q) || norm(st.name).includes(q) || norm(st.code).includes(q))
        : st.leaves
      if (lvs.length === 0) continue
      rows.push({ kind: "std", key: `s${st.sid}`, code: st.code, name: st.name })
      for (const l of lvs.sort((a, b) => (a.name).localeCompare(b.name))) {
        rows.push({ kind: "leaf", key: `l${l.id}`, opt: l, groupName: groupNameOf(l) })
      }
    }
    const uq = q ? unmapped.filter(l => norm(l.name).includes(q)) : unmapped
    if (uq.length) {
      rows.push({ kind: "std", key: "s-unmapped", code: "—", name: "미분류" })
      for (const l of uq) rows.push({ kind: "leaf", key: `l${l.id}`, opt: l, groupName: null })
    }
    return rows
  }, [options, search, hasStandard])

  // Inline create state
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState("")
  const [newParentId, setNewParentId] = useState<number | null>(null)
  const [createLoading, setCreateLoading] = useState(false)
  const newNameRef = useRef<HTMLInputElement>(null)

  // Get selectable parent categories (depth=1, has children)
  const parentCategories = useMemo(() => {
    return treeOrdered.filter(o => {
      const depth = depthMap.get(o.id) ?? 0
      return depth === 1 && treeOrdered.some(c => c.parent_id === o.id)
    })
  }, [treeOrdered, depthMap])

  const handleCreate = useCallback(async () => {
    if (!newName.trim() || !onCreateAccount) return
    setCreateLoading(true)
    try {
      const created = await onCreateAccount(newName.trim(), newParentId)
      if (created) {
        onChange(String(created.id))
        setOpen(false)
        setSearch("")
        setCreating(false)
        setNewName("")
        setNewParentId(null)
      }
    } finally {
      setCreateLoading(false)
    }
  }, [newName, newParentId, onCreateAccount, onChange])

  // Focus new name input when creating
  useEffect(() => {
    if (creating) setTimeout(() => newNameRef.current?.focus(), 50)
  }, [creating])

  // Selected display
  const selected = options.find((o) => String(o.id) === value)

  const dropdownContent = open && mounted && portalContainer ? createPortal(
    <div
      ref={dropdownRef}
      style={dropdownStyle}
      className="rounded-lg border border-border bg-popover shadow-xl animate-in fade-in-0 zoom-in-95 duration-150"
    >
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
        {(hasStandard ? stdRows.length === 0 : filtered.length === 0) && !creating ? (
          <div className="px-3 py-4 text-center text-xs text-muted-foreground">
            검색 결과가 없습니다
          </div>
        ) : !creating && hasStandard ? (
          // 표준 골격 기반: 카테고리>표준>잎
          stdRows.map((row) => {
            if (row.kind === "std") {
              return (
                <div
                  key={row.key}
                  className="flex items-center gap-1.5 px-3 py-1.5 mt-1 first:mt-0 border-t first:border-t-0 text-[11px] font-semibold text-blue-300/90"
                >
                  <span className="font-mono text-[10px] text-blue-400">{row.code}</span>
                  {row.name}
                </div>
              )
            }
            const opt = row.opt
            const isSelected = String(opt.id) === value
            return (
              <button
                key={row.key}
                type="button"
                onClick={() => { onChange(String(opt.id)); setOpen(false); setSearch("") }}
                className={cn(
                  "w-full text-left px-3 py-1.5 text-xs transition-colors flex items-center gap-1.5 pl-6",
                  "hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none",
                  isSelected && "bg-accent/20 text-accent-foreground font-medium",
                )}
              >
                <span className="text-muted-foreground/40">└</span>
                {row.groupName && (
                  <span className="text-[9px] text-blue-300/70 bg-blue-500/10 px-1 rounded shrink-0">{row.groupName}</span>
                )}
                <span className="flex-1 truncate">{opt.name}</span>
                {opt.is_recurring && (
                  <span className="text-[9px] text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded shrink-0">반복</span>
                )}
                {showCode && (
                  <span className="text-muted-foreground/50 text-[10px] shrink-0">{opt.code}</span>
                )}
              </button>
            )
          })
        ) : !creating ? (
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
            const catBadge = saCategoryLabel(opt.code)
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
                  "w-full text-left px-3 py-1.5 text-xs transition-colors flex items-center gap-1.5",
                  "hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none",
                  isSelected && "bg-accent/20 text-accent-foreground font-medium",
                  "pl-6",
                )}
              >
                <span className="text-muted-foreground/40">└</span>
                {catBadge && (
                  <span className="text-[9px] font-semibold text-amber-300/90 bg-amber-500/10 px-1.5 py-0.5 rounded shrink-0 min-w-[3.5rem] text-center">{catBadge}</span>
                )}
                <span className="flex-1 truncate">{opt.name}</span>
                {opt.is_recurring && (
                  <span className="text-[9px] text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded shrink-0">반복</span>
                )}
                {showCode && (
                  <span className="text-muted-foreground/50 text-[10px] shrink-0">{opt.code}</span>
                )}
              </button>
            )
          })
        ) : (
          /* Inline create form */
          <div className="px-3 py-2 space-y-2">
            <input
              ref={newNameRef}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleCreate() }}
              placeholder="새 계정 이름"
              className="w-full bg-muted/30 rounded px-2 py-1.5 text-xs outline-none border border-border focus:border-accent"
            />
            <select
              value={newParentId ?? ""}
              onChange={(e) => setNewParentId(e.target.value ? Number(e.target.value) : null)}
              className="w-full bg-muted/30 rounded px-2 py-1.5 text-xs outline-none border border-border"
            >
              <option value="">상위 계정 선택 (선택사항)</option>
              {parentCategories.map(p => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <div className="flex gap-1.5">
              <button
                type="button"
                onClick={handleCreate}
                disabled={!newName.trim() || createLoading}
                className="flex-1 bg-accent text-accent-foreground rounded px-2 py-1 text-xs font-medium disabled:opacity-50"
              >
                {createLoading ? "생성 중..." : "추가"}
              </button>
              <button
                type="button"
                onClick={() => { setCreating(false); setNewName(""); setNewParentId(null) }}
                className="px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
              >
                취소
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Create button at bottom */}
      {onCreateAccount && !creating && (
        <div className="border-t border-border px-3 py-1.5">
          <button
            type="button"
            onClick={() => { setCreating(true); setNewName(search) }}
            className="w-full flex items-center gap-1.5 text-xs text-accent hover:text-accent/80 py-1"
          >
            <Plus className="h-3 w-3" />
            새 계정 추가{search && ` "${search}"`}
          </button>
        </div>
      )}
    </div>,
    portalContainer!,
  ) : null

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
          triggerClassName,
        )}
      >
        <span className="truncate">
          {selected ? (
            <>
              {selected.name}
              {saCategoryLabel(selected.code) && (
                <span className="text-muted-foreground/60 ml-1.5 text-[10px]">[{saCategoryLabel(selected.code)}]</span>
              )}
            </>
          ) : placeholder}
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

      {dropdownContent}
    </div>
  )
}
