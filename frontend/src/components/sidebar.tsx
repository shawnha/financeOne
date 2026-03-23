"use client"

import { useState, useEffect, useCallback } from "react"
import Link from "next/link"
import { usePathname, useSearchParams } from "next/navigation"
import { cn } from "@/lib/utils"
import {
  LayoutDashboard,
  TrendingUp,
  CreditCard,
  Upload,
  MessageSquare,
  Settings,
  FileText,
  BarChart3,
  Users,
  BookOpen,
  Menu,
  X,
} from "lucide-react"

const sections = [
  {
    label: "요약",
    items: [
      { label: "대시보드", icon: LayoutDashboard, href: "/", enabled: true },
      { label: "현금흐름표", icon: TrendingUp, href: "/cashflow", enabled: true },
      { label: "재무제표", icon: FileText, href: "/statements", enabled: true },
      { label: "리포트", icon: BarChart3, href: "/reports", enabled: false },
    ],
  },
  {
    label: "데이터",
    items: [
      { label: "거래내역", icon: CreditCard, href: "/transactions", enabled: true },
      { label: "업로드", icon: Upload, href: "/upload", enabled: true },
      { label: "Slack 매칭", icon: MessageSquare, href: "/slack-match", enabled: true },
    ],
  },
  {
    label: "계정",
    items: [
      { label: "내부 계정", icon: BookOpen, href: "/accounts/internal", enabled: false },
      { label: "표준 계정", icon: BookOpen, href: "/accounts/standard", enabled: false },
    ],
  },
  {
    label: "관리",
    items: [
      { label: "멤버 관리", icon: Users, href: "/settings/members", enabled: false },
      { label: "설정", icon: Settings, href: "/settings", enabled: true },
    ],
  },
]

const ENTITY_NAMES: Record<string, { name: string; color: string }> = {
  "1": { name: "한아원인터내셔널", color: "bg-blue-500" },
  "2": { name: "한아원코리아", color: "bg-green-500" },
  "3": { name: "한아원리테일", color: "bg-amber-500" },
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

  // Close mobile sidebar on route change
  useEffect(() => {
    setMobileOpen(false)
  }, [pathname])

  // Close on Escape
  useEffect(() => {
    if (!mobileOpen) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false)
    }
    document.addEventListener("keydown", handleKey)
    return () => document.removeEventListener("keydown", handleKey)
  }, [mobileOpen])

  // Prevent body scroll when mobile sidebar is open
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = "hidden"
    } else {
      document.body.style.overflow = ""
    }
    return () => {
      document.body.style.overflow = ""
    }
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
      <div className="p-6">
        <div className="text-xl font-bold text-foreground">FinanceOne</div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 overflow-y-auto" aria-label="Main navigation">
        {sections.map((section) => (
          <div key={section.label}>
            <p className="mt-6 mb-2 px-3 text-[10px] uppercase tracking-[1.5px] text-muted-foreground select-none">
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
                        className={cn(
                          "flex items-center gap-3 rounded-md px-3 h-10 text-sm",
                          "text-muted-foreground/50 cursor-not-allowed select-none",
                        )}
                        aria-disabled="true"
                      >
                        <Icon className="h-5 w-5 shrink-0" />
                        {item.label}
                      </span>
                    </li>
                  )
                }

                return (
                  <li key={item.href}>
                    <Link
                      href={buildHref(item.href)}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex items-center gap-3 rounded-md px-3 h-10 text-sm transition-colors",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#22C55E]",
                        active
                          ? "border-l-[3px] border-[hsl(var(--accent))] text-[hsl(var(--accent))] bg-secondary"
                          : "text-muted-foreground hover:bg-secondary hover:text-foreground",
                      )}
                    >
                      <Icon className="h-5 w-5 shrink-0" />
                      {item.label}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* Entity indicator at bottom */}
      <div className="border-t border-border p-4">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span
            className={cn("inline-block h-2 w-2 rounded-full shrink-0", entityInfo.color)}
            aria-hidden="true"
          />
          <span className="truncate">{entityInfo.name}</span>
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
          "flex items-center justify-center h-11 w-11 rounded-md",
          "bg-primary text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#22C55E]",
        )}
        aria-label="메뉴 열기"
      >
        <Menu className="h-5 w-5" />
      </button>

      {/* Desktop sidebar */}
      <aside
        className={cn(
          "hidden md:flex md:flex-col md:fixed md:inset-y-0",
          "w-[var(--sidebar-width)] bg-primary",
        )}
      >
        {sidebarContent}
      </aside>

      {/* Desktop spacer */}
      <div className="hidden md:block md:w-[var(--sidebar-width)] md:shrink-0" />

      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />

          {/* Slide-over */}
          <aside
            className="relative flex flex-col w-[var(--sidebar-width)] h-full bg-primary animate-in slide-in-from-left duration-200"
            role="dialog"
            aria-modal="true"
            aria-label="Navigation menu"
          >
            {/* Close button */}
            <button
              type="button"
              onClick={() => setMobileOpen(false)}
              className={cn(
                "absolute top-4 right-4",
                "flex items-center justify-center h-11 w-11 rounded-md",
                "text-muted-foreground hover:text-foreground",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#22C55E]",
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
