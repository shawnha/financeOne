"use client"

import { useState, useRef, useEffect } from "react"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { cn } from "@/lib/utils"

const MONTH_LABELS = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
const MONTH_LABELS_KR = ["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월"]

interface MonthPickerProps {
  /** Available months in "YYYY-MM" format */
  months: string[]
  /** Currently selected month "YYYY-MM" */
  selected: string
  /** Callback when month changes */
  onSelect: (month: string) => void
  /** Accent color for selected state (CSS color string) */
  accentColor?: string
  /** Allow selecting future months not in the months list */
  allowFuture?: boolean
}

export function MonthPicker({
  months,
  selected,
  onSelect,
  accentColor = "hsl(var(--accent))",
  allowFuture = false,
}: MonthPickerProps) {
  const [open, setOpen] = useState(false)
  const [viewYear, setViewYear] = useState(() => {
    return selected ? parseInt(selected.slice(0, 4)) : new Date().getFullYear()
  })
  const ref = useRef<HTMLDivElement>(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [open])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false)
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [open])

  // Sync viewYear when selected changes
  useEffect(() => {
    if (selected) {
      setViewYear(parseInt(selected.slice(0, 4)))
    }
  }, [selected])

  const monthSet = new Set(months)

  // Determine year range from available months
  const years = months.map((m) => parseInt(m.slice(0, 4)))
  const minYear = years.length > 0 ? Math.min(...years) : new Date().getFullYear()
  const maxYear = allowFuture
    ? Math.max(years.length > 0 ? Math.max(...years) : new Date().getFullYear(), new Date().getFullYear() + 1)
    : (years.length > 0 ? Math.max(...years) : new Date().getFullYear())

  const isMonthAvailable = (year: number, month: number) => {
    const key = `${year}-${String(month).padStart(2, "0")}`
    if (monthSet.has(key)) return true
    if (allowFuture) {
      // Allow current month and future
      const now = new Date()
      const target = new Date(year, month - 1, 1)
      const current = new Date(now.getFullYear(), now.getMonth(), 1)
      return target >= current
    }
    return false
  }

  // Display label for the pill
  const selectedMonthNum = selected ? parseInt(selected.slice(5)) : 0
  const selectedYear = selected ? parseInt(selected.slice(0, 4)) : 0
  const pillLabel = selected
    ? `${MONTH_LABELS[selectedMonthNum - 1]} ${selectedYear}`
    : "월 선택"

  return (
    <div ref={ref} className="relative inline-flex items-center gap-1">
      {/* Previous month arrow */}
      <button
        onClick={() => {
          const m = selectedMonthNum - 1
          if (m < 1) {
            const key = `${selectedYear - 1}-12`
            if (allowFuture || monthSet.has(key)) onSelect(key)
          } else {
            const key = `${selectedYear}-${String(m).padStart(2, "0")}`
            if (allowFuture || monthSet.has(key)) onSelect(key)
          }
        }}
        className="p-1 rounded-md hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-colors"
        aria-label="이전 월"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>

      {/* Pill trigger */}
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-all",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          "hover:opacity-90 active:scale-[0.97]",
        )}
        style={{ backgroundColor: accentColor, color: "#fff" }}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {pillLabel}
      </button>

      {/* Next month arrow */}
      <button
        onClick={() => {
          const m = selectedMonthNum + 1
          if (m > 12) {
            const key = `${selectedYear + 1}-01`
            if (allowFuture || monthSet.has(key)) onSelect(key)
          } else {
            const key = `${selectedYear}-${String(m).padStart(2, "0")}`
            if (allowFuture || monthSet.has(key)) onSelect(key)
          }
        }}
        className="p-1 rounded-md hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-colors"
        aria-label="다음 월"
      >
        <ChevronRight className="h-4 w-4" />
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute top-full left-0 mt-2 z-50 w-[260px] rounded-xl border border-border bg-popover shadow-xl animate-in fade-in-0 zoom-in-95 duration-150">
          {/* Year navigation */}
          <div className="flex items-center justify-between px-3 py-2.5 border-b border-border">
            <button
              onClick={() => setViewYear((y) => Math.max(minYear, y - 1))}
              disabled={viewYear <= minYear}
              className="p-1 rounded-md hover:bg-muted/50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              aria-label="이전 연도"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="text-sm font-semibold tabular-nums">{viewYear}</span>
            <button
              onClick={() => setViewYear((y) => Math.min(maxYear, y + 1))}
              disabled={viewYear >= maxYear}
              className="p-1 rounded-md hover:bg-muted/50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              aria-label="다음 연도"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          {/* Month grid */}
          <div className="grid grid-cols-4 gap-1 p-2.5" role="listbox" aria-label="월 선택">
            {Array.from({ length: 12 }, (_, i) => {
              const monthNum = i + 1
              const key = `${viewYear}-${String(monthNum).padStart(2, "0")}`
              const available = isMonthAvailable(viewYear, monthNum)
              const isSelected = key === selected

              return (
                <button
                  key={key}
                  role="option"
                  aria-selected={isSelected}
                  disabled={!available}
                  onClick={() => {
                    onSelect(key)
                    setOpen(false)
                  }}
                  className={cn(
                    "py-2 rounded-lg text-xs font-medium transition-all",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    available && !isSelected && "hover:bg-muted/50 text-foreground",
                    !available && "text-muted-foreground/30 cursor-not-allowed",
                    isSelected && "text-white shadow-sm",
                  )}
                  style={isSelected ? { backgroundColor: accentColor } : undefined}
                >
                  {MONTH_LABELS_KR[i]}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
