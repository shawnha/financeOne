"use client"

import { useState, useRef, useEffect, useMemo } from "react"
import { Search, ChevronDown, X } from "lucide-react"
import { cn } from "@/lib/utils"

interface AccountOption {
  id: number
  code: string
  name: string
  parent_id?: number | null
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
}

export function AccountCombobox({
  options,
  value,
  onChange,
  placeholder = "선택하세요",
  showCode = false,
  compact = false,
  autoOpen = false,
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

  // Filter options by search (searches both code and name)
  const filtered = useMemo(() => {
    if (!search) return options
    const q = search.toLowerCase()
    return options.filter(
      (o) => o.code.toLowerCase().includes(q) || o.name.toLowerCase().includes(q),
    )
  }, [options, search])

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
        <div className="absolute top-full left-0 mt-1 z-50 min-w-[260px] rounded-lg border border-border bg-popover shadow-xl animate-in fade-in-0 zoom-in-95 duration-150">
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
                const isChild = !!opt.parent_id
                const isSelected = String(opt.id) === value

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
                      isChild && "pl-6",
                    )}
                  >
                    {isChild && <span className="text-muted-foreground/40 mr-1">└</span>}
                    {opt.name}
                    {showCode && (
                      <span className="text-muted-foreground/50 text-[10px] ml-2">{opt.code}</span>
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
