"use client"

import { useState, useRef, useEffect, useMemo } from "react"
import { createPortal } from "react-dom"
import { Search, ChevronDown, X, Check } from "lucide-react"
import { cn } from "@/lib/utils"

interface Option {
  value: string
  label: string
}

interface SearchableSelectProps {
  options: Option[]
  value: string
  onChange: (value: string) => void
  placeholder?: string
  searchPlaceholder?: string
  className?: string
}

export function SearchableSelect({
  options,
  value,
  onChange,
  placeholder = "선택하세요",
  searchPlaceholder = "검색...",
  className,
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const [dropdownStyle, setDropdownStyle] = useState<React.CSSProperties>({})
  const [mounted, setMounted] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { setMounted(true) }, [])

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

  // Position dropdown
  useEffect(() => {
    if (!open || !ref.current) return

    const update = () => {
      if (!ref.current) return
      const rect = ref.current.getBoundingClientRect()
      const spaceBelow = window.innerHeight - rect.bottom

      const style: React.CSSProperties = {
        position: "fixed",
        left: rect.left,
        minWidth: Math.max(200, rect.width),
        zIndex: 99999,
      }

      if (spaceBelow < 260) {
        style.bottom = window.innerHeight - rect.top
      } else {
        style.top = rect.bottom + 4
      }

      setDropdownStyle(style)
    }

    update()
    setTimeout(() => inputRef.current?.focus(), 50)

    window.addEventListener("resize", update)
    window.addEventListener("scroll", update, true)
    return () => {
      window.removeEventListener("resize", update)
      window.removeEventListener("scroll", update, true)
    }
  }, [open])

  const filtered = useMemo(() => {
    if (!search) return options
    const q = search.toLowerCase()
    return options.filter(o => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q))
  }, [options, search])

  const selected = options.find(o => o.value === value)

  const dropdownContent = open && mounted ? createPortal(
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
          placeholder={searchPlaceholder}
          className="flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground/50"
        />
      </div>

      {/* Options list */}
      <div className="max-h-[240px] overflow-y-auto py-1">
        {/* "전체" option */}
        <button
          type="button"
          onClick={() => {
            onChange("")
            setOpen(false)
            setSearch("")
          }}
          className={cn(
            "w-full text-left px-3 py-1.5 text-xs transition-colors flex items-center gap-2",
            "hover:bg-muted/40",
            !value && "bg-accent/20 text-accent-foreground font-medium",
          )}
        >
          {!value && <Check className="h-3 w-3 shrink-0" />}
          {!value ? "" : <span className="w-3 shrink-0" />}
          전체
        </button>

        {filtered.length === 0 ? (
          <div className="px-3 py-4 text-center text-xs text-muted-foreground">
            검색 결과가 없습니다
          </div>
        ) : (
          filtered.map((opt) => {
            const isSelected = opt.value === value
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => {
                  onChange(opt.value)
                  setOpen(false)
                  setSearch("")
                }}
                className={cn(
                  "w-full text-left px-3 py-1.5 text-xs transition-colors flex items-center gap-2",
                  "hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none",
                  isSelected && "bg-accent/20 text-accent-foreground font-medium",
                )}
              >
                {isSelected ? <Check className="h-3 w-3 shrink-0" /> : <span className="w-3 shrink-0" />}
                {opt.label}
              </button>
            )
          })
        )}
      </div>
    </div>,
    document.body,
  ) : null

  return (
    <div ref={ref} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          "flex items-center justify-between w-full h-9 px-3 rounded-md border border-input bg-background text-sm",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          "hover:bg-muted/30 transition-colors",
          !selected && "text-muted-foreground",
        )}
      >
        <span className="truncate">
          {selected ? selected.label : placeholder}
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
