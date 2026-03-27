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
  ArrowLeftRight,
  DollarSign,
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
      { label: "법인간 거래", icon: ArrowLeftRight, href: "/intercompany", enabled: true },
      { label: "환율 관리", icon: DollarSign, href: "/exchange-rates", enabled: true },
    ],
  },
  {
    label: "계정",
    items: [
      { label: "내부 계정", icon: BookOpen, href: "/accounts/internal", enabled: true },
      { label: "표준 계정", icon: BookOpen, href: "/accounts/standard", enabled: true },
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
                      {item.label}
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
