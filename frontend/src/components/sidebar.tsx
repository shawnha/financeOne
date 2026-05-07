"use client"

import { useState, useEffect, useCallback } from "react"
import Link from "next/link"
import { usePathname, useSearchParams } from "next/navigation"
import { cn } from "@/lib/utils"
import { fetchAPI } from "@/lib/api"
import {
  LayoutDashboard,
  TrendingUp,
  CreditCard,
  Upload,
  // MessageSquare,  // Slack 매칭 재활성화 시 import 복원
  Settings,
  FileText,
  BarChart3,
  Users,
  BookOpen,
  Menu,
  X,
  ArrowLeftRight,
  DollarSign,
  Link2,
  Receipt,
  FileSpreadsheet,
  Wallet,
  FileBarChart,
} from "lucide-react"

type SidebarItem = {
  label: string
  icon: typeof LayoutDashboard
  href: string
  enabled: boolean
  badgeKey?: "expenseone_unmatched"
}

const sections: { label: string; items: SidebarItem[] }[] = [
  {
    label: "요약",
    items: [
      { label: "대시보드", icon: LayoutDashboard, href: "/", enabled: true },
      { label: "현금흐름표", icon: TrendingUp, href: "/cashflow", enabled: true },
      { label: "운영비", icon: Wallet, href: "/opex", enabled: true },
      { label: "손익계산서", icon: FileBarChart, href: "/pnl", enabled: true },
      { label: "재무제표", icon: FileText, href: "/statements", enabled: true },
      { label: "리포트", icon: BarChart3, href: "/reports", enabled: false },
    ],
  },
  {
    label: "데이터",
    items: [
      { label: "거래내역", icon: CreditCard, href: "/transactions", enabled: true },
      { label: "세금계산서", icon: FileSpreadsheet, href: "/invoices", enabled: true },
      { label: "카드 청구서", icon: CreditCard, href: "/card-billings", enabled: true },
      { label: "업로드", icon: Upload, href: "/upload", enabled: true },
      // Slack 매칭은 ExpenseOne 도입 후 사용 빈도 낮아 숨김 (코드 보존, 재활성 원하면 enabled: true)
      // { label: "Slack 매칭", icon: MessageSquare, href: "/slack-match", enabled: true },
      {
        label: "ExpenseOne 매칭",
        icon: Receipt,
        href: "/expenseone-match",
        enabled: true,
        badgeKey: "expenseone_unmatched",
      },
      { label: "법인간 거래", icon: ArrowLeftRight, href: "/intercompany", enabled: true },
      { label: "환율 관리", icon: DollarSign, href: "/exchange-rates", enabled: true },
    ],
  },
  {
    label: "계정",
    items: [
      { label: "내부 계정", icon: BookOpen, href: "/accounts/internal", enabled: true },
      { label: "표준 계정", icon: BookOpen, href: "/accounts/standard", enabled: true },
      { label: "계정별 원장", icon: BookOpen, href: "/accounts/ledger", enabled: true },
      { label: "매핑 규칙", icon: Link2, href: "/accounts/mapping-rules", enabled: true },
    ],
  },
  {
    label: "관리",
    items: [
      { label: "멤버 관리", icon: Users, href: "/members", enabled: true },
      { label: "설정", icon: Settings, href: "/settings", enabled: true },
    ],
  },
]

const ENTITY_NAMES: Record<string, { name: string; colorVar: string }> = {
  "1": { name: "한아원인터내셔널", colorVar: "var(--entity-hoi)" },
  "2": { name: "한아원코리아", colorVar: "var(--entity-hok)" },
  "3": { name: "한아원리테일", colorVar: "var(--entity-hor)" },
}

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/"
  return pathname.startsWith(href)
}

export function Sidebar() {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const [mobileOpen, setMobileOpen] = useState(false)
  const entityId = searchParams.get("entity") || "1"
  const entityInfo = ENTITY_NAMES[entityId] || ENTITY_NAMES["1"]

  // ── ExpenseOne 미매칭 뱃지 카운트 ─────────────
  const [expenseOneUnmatched, setExpenseOneUnmatched] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    const refresh = async () => {
      try {
        const data = await fetchAPI<{ unmatched_count: number }>(
          "/expenseone-match/unmatched-count",
        )
        if (!cancelled) setExpenseOneUnmatched(data.unmatched_count)
      } catch {
        // 조용히 실패 — 뱃지만 숨김
      }
    }
    refresh()
    const id = setInterval(refresh, 60_000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [pathname])

  const badgeCounts: Record<string, number | null> = {
    expenseone_unmatched: expenseOneUnmatched,
  }

  useEffect(() => {
    setMobileOpen(false)
  }, [pathname])

  useEffect(() => {
    if (!mobileOpen) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false)
    }
    document.addEventListener("keydown", handleKey)
    return () => document.removeEventListener("keydown", handleKey)
  }, [mobileOpen])

  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = "hidden"
    } else {
      document.body.style.overflow = ""
    }
    return () => { document.body.style.overflow = "" }
  }, [mobileOpen])

  const buildHref = useCallback(
    (href: string) => {
      const params = new URLSearchParams(searchParams.toString())
      if (params.toString()) return `${href}?${params.toString()}`
      return href
    },
    [searchParams],
  )

  const sidebarContent = (
    <>
      {/* Logo */}
      <div className="p-6 pb-4">
        <div className="text-lg font-semibold tracking-tight text-foreground">
          FinanceOne
        </div>
        <div className="text-[10px] font-mono text-muted-foreground/60 mt-0.5">
          v0.3.0
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 overflow-y-auto" aria-label="Main navigation">
        {sections.map((section) => (
          <div key={section.label}>
            <p className="mt-6 mb-2 px-3 text-[10px] uppercase tracking-[0.15em] font-medium text-muted-foreground/60 select-none">
              {section.label}
            </p>
            <ul className="space-y-0.5">
              {section.items.map((item) => {
                const Icon = item.icon
                const active = isActive(pathname, item.href)
                const disabled = !item.enabled

                if (disabled) {
                  return (
                    <li key={item.href}>
                      <span
                        className="flex items-center gap-3 rounded-lg px-3 h-10 text-sm text-muted-foreground/30 cursor-not-allowed select-none"
                        aria-disabled="true"
                      >
                        <Icon className="h-4 w-4 shrink-0" />
                        {item.label}
                      </span>
                    </li>
                  )
                }

                const badgeCount = item.badgeKey ? badgeCounts[item.badgeKey] : null
                const showBadge = badgeCount !== null && badgeCount !== undefined && badgeCount > 0

                return (
                  <li key={item.href}>
                    <Link
                      href={buildHref(item.href)}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex items-center gap-3 rounded-lg px-3 h-10 text-sm",
                        "transition-all duration-300 ease-[var(--ease-premium)]",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        active
                          ? "bg-white/[0.06] text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]"
                          : "text-muted-foreground hover:bg-white/[0.04] hover:text-foreground",
                      )}
                    >
                      <Icon className={cn("h-4 w-4 shrink-0", active && "text-accent")} />
                      <span className="flex-1 truncate">{item.label}</span>
                      {showBadge && (
                        <span
                          className={cn(
                            "inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full",
                            "text-[10px] font-medium tabular-nums",
                            "bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/30",
                          )}
                          aria-label={`${badgeCount}건 미매칭`}
                        >
                          {badgeCount! > 99 ? "99+" : badgeCount}
                        </span>
                      )}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* Entity indicator */}
      <div className="border-t border-white/[0.04] p-4">
        <div className="flex items-center gap-2.5 text-sm text-muted-foreground">
          <span
            className="inline-block h-2 w-2 rounded-full shrink-0"
            style={{ backgroundColor: `hsl(${entityInfo.colorVar})` }}
            aria-hidden="true"
          />
          <span className="truncate text-xs">{entityInfo.name}</span>
        </div>
      </div>
    </>
  )

  return (
    <>
      {/* Mobile hamburger */}
      <button
        type="button"
        onClick={() => setMobileOpen(true)}
        className={cn(
          "fixed top-3 left-3 z-50 md:hidden",
          "flex items-center justify-center h-11 w-11 rounded-lg",
          "bg-card/80 backdrop-blur-xl text-foreground border border-white/[0.06]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
        aria-label="메뉴 열기"
      >
        <Menu className="h-5 w-5" />
      </button>

      {/* Desktop sidebar — glassmorphism */}
      <aside
        className={cn(
          "hidden md:flex md:flex-col md:fixed md:inset-y-0",
          "w-[var(--sidebar-width)]",
          "bg-black/80 backdrop-blur-2xl",
          "border-r border-white/[0.04]",
        )}
      >
        {sidebarContent}
      </aside>

      {/* Desktop spacer */}
      <div className="hidden md:block md:w-[var(--sidebar-width)] md:shrink-0" />

      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />
          <aside
            className={cn(
              "relative flex flex-col w-[var(--sidebar-width)] h-full",
              "bg-black/90 backdrop-blur-2xl border-r border-white/[0.04]",
              "animate-in slide-in-from-left duration-300",
            )}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation menu"
          >
            <button
              type="button"
              onClick={() => setMobileOpen(false)}
              className={cn(
                "absolute top-4 right-4",
                "flex items-center justify-center h-11 w-11 rounded-lg",
                "text-muted-foreground hover:text-foreground",
                "transition-colors duration-200",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              )}
              aria-label="메뉴 닫기"
            >
              <X className="h-5 w-5" />
            </button>
            {sidebarContent}
          </aside>
        </div>
      )}
    </>
  )
}
