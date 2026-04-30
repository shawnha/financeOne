"use client"

import { useCallback, useRef } from "react"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useDashboard } from "@/contexts/dashboard-context"
import { formatCurrency } from "@/lib/format"
import type { BentoEntity, Currency, Gaap } from "@/lib/dashboard-types"

interface BentoEntitySelectorProps {
  loading?: boolean
}

export function BentoEntitySelector({ loading = false }: BentoEntitySelectorProps) {
  const { scope, setScope, currency, setCurrency, gaap, setGaap, data } =
    useDashboard()

  if (loading || !data) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-5 gap-2 mb-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Card key={i} className="p-3">
            <Skeleton className="h-3 w-16 mb-2" />
            <Skeleton className="h-5 w-24 mb-2" />
            <Skeleton className="h-4 w-full" />
          </Card>
        ))}
      </div>
    )
  }

  return (
    <div
      className="grid grid-cols-1 md:grid-cols-5 gap-2 mb-3"
      role="tablist"
      aria-label="법인 선택"
    >
      <GroupCard
        active={scope === "group"}
        onClick={() => setScope("group")}
        currency={currency}
        gaap={gaap}
        onCurrencyChange={setCurrency}
        onGaapChange={setGaap}
        groupTotalUsd={data.bento.group_total_usd}
        eliminationsUsd={data.bento.eliminations_usd}
        eliminationsCount={data.bento.eliminations_count}
      />
      {data.bento.entities.map((e) => (
        <EntityCard
          key={e.entity_id}
          entity={e}
          active={scope === e.entity_id}
          onClick={() => setScope(e.entity_id)}
        />
      ))}
    </div>
  )
}

// ── Group Card ─────────────────────────────────────────────

function GroupCard({
  active,
  onClick,
  currency,
  gaap,
  onCurrencyChange,
  onGaapChange,
  groupTotalUsd,
  eliminationsUsd,
  eliminationsCount,
}: {
  active: boolean
  onClick: () => void
  currency: Currency
  gaap: Gaap
  onCurrencyChange: (c: Currency) => void
  onGaapChange: (g: Gaap) => void
  groupTotalUsd: string
  eliminationsUsd: string
  eliminationsCount: number
}) {
  const total = Number(groupTotalUsd)
  const elimAmt = Number(eliminationsUsd)

  return (
    <Card
      className={`relative p-3 cursor-pointer transition-all bg-gradient-to-br from-[hsl(var(--profit))]/10 to-[hsl(var(--color-secondary))] ${
        active
          ? "ring-2 ring-[hsl(var(--profit))] border-[hsl(var(--profit))]"
          : "hover:border-[hsl(var(--profit))]/40"
      }`}
      role="tab"
      aria-selected={active}
      aria-label={`그룹 통합 잔고 ${formatCurrency(total, currency)}`}
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          onClick()
        }
      }}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-base" aria-hidden>🌐</span>
        <span className="text-[11px] font-bold uppercase tracking-wide text-[hsl(var(--ai-accent))] flex-1">
          GROUP
        </span>
        <span className="text-[9px] text-muted-foreground">{currency}</span>
      </div>
      <p className="font-mono font-bold text-lg tabular-nums text-foreground leading-none">
        {formatCurrency(total, currency)}
      </p>
      {eliminationsCount > 0 && (
        <p className="text-[10px] text-muted-foreground mt-1">
          💡 IC: {formatCurrency(elimAmt, currency)} ({eliminationsCount}건)
        </p>
      )}

      {/* Currency / GAAP toggles — event.stopPropagation 으로 카드 select 와 분리 */}
      <div
        className="flex flex-wrap gap-1 mt-2"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
        role="group"
        aria-label="통화 및 GAAP 기준 선택"
      >
        <ToggleGroup
          options={[
            { value: "USD", label: "USD" },
            { value: "KRW", label: "KRW" },
          ]}
          selected={currency}
          onChange={(v) => onCurrencyChange(v as Currency)}
          ariaLabel="통화"
        />
        <span className="text-muted-foreground text-[10px] self-center" aria-hidden>
          |
        </span>
        <ToggleGroup
          options={[
            { value: "US", label: "US-GAAP" },
            { value: "K", label: "K-GAAP" },
          ]}
          selected={gaap}
          onChange={(v) => onGaapChange(v as Gaap)}
          ariaLabel="회계 기준"
        />
      </div>
    </Card>
  )
}

// ── Entity Card ───────────────────────────────────────────

function EntityCard({
  entity,
  active,
  onClick,
}: {
  entity: BentoEntity
  active: boolean
  onClick: () => void
}) {
  const cash = Number(entity.cash_balance)

  return (
    <Card
      className={`relative p-3 cursor-pointer transition-all ${
        active
          ? "ring-2 ring-[hsl(var(--profit))] border-[hsl(var(--profit))]"
          : "hover:border-[hsl(var(--profit))]/40"
      }`}
      role="tab"
      aria-selected={active}
      aria-label={`${entity.name} ${formatCurrency(cash, entity.currency)}`}
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          onClick()
        }
      }}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-base" aria-hidden>{entity.flag}</span>
        <span className="text-[11px] font-semibold text-muted-foreground flex-1 truncate">
          {entity.name}
        </span>
        <span className="text-[9px] text-muted-foreground">{entity.currency}</span>
      </div>
      <p className="font-mono font-bold text-lg tabular-nums text-foreground leading-none">
        {formatCurrency(cash, entity.currency)}
      </p>
      {entity.sparkline.length > 0 && (
        <Sparkline values={entity.sparkline} />
      )}
      {entity.badge && (
        <span
          className="absolute top-2 right-2 text-[9px] font-bold tracking-wide px-1.5 py-0.5 rounded-full bg-[hsl(var(--warning))]/15 text-[hsl(var(--warning))]"
          aria-label={`경고: ${entity.badge}`}
        >
          {entity.badge}
        </span>
      )}
      {entity.accrual_data_status === "in_progress" && (
        <span
          className="absolute bottom-2 right-2 text-[9px] text-[hsl(var(--warning))]"
          aria-label="발생주의 데이터 진행 중"
          title="발생주의 데이터 정확도 진행 중"
        >
          ⚠️
        </span>
      )}
    </Card>
  )
}

// ── Sparkline ─────────────────────────────────────────────

function Sparkline({ values }: { values: number[] }) {
  const max = Math.max(...values.map(Math.abs), 1)
  return (
    <div className="flex items-end gap-0.5 h-4 mt-2" aria-hidden>
      {values.map((v, i) => (
        <div
          key={i}
          className="flex-1 bg-[hsl(var(--profit))] opacity-70 rounded-sm"
          style={{ height: `${(Math.abs(v) / max) * 100}%`, minHeight: "1px" }}
        />
      ))}
    </div>
  )
}

// ── Toggle Group (radio pattern) ──────────────────────────

function ToggleGroup({
  options,
  selected,
  onChange,
  ariaLabel,
}: {
  options: { value: string; label: string }[]
  selected: string
  onChange: (v: string) => void
  ariaLabel: string
}) {
  const groupRef = useRef<HTMLDivElement>(null)

  const handleKey = useCallback(
    (e: React.KeyboardEvent) => {
      if (!groupRef.current) return
      const idx = options.findIndex((o) => o.value === selected)
      if (e.key === "ArrowRight") {
        e.preventDefault()
        onChange(options[(idx + 1) % options.length].value)
      } else if (e.key === "ArrowLeft") {
        e.preventDefault()
        onChange(options[(idx - 1 + options.length) % options.length].value)
      }
    },
    [options, selected, onChange],
  )

  return (
    <div
      ref={groupRef}
      role="radiogroup"
      aria-label={ariaLabel}
      onKeyDown={handleKey}
      className="flex gap-0.5"
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={selected === o.value}
          onClick={() => onChange(o.value)}
          tabIndex={selected === o.value ? 0 : -1}
          className={`text-[10px] px-2 py-1 rounded font-medium min-w-[44px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--color-cta))] ${
            selected === o.value
              ? "bg-[hsl(var(--profit))]/20 text-[hsl(var(--profit))]"
              : "bg-muted text-muted-foreground hover:bg-muted/70"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
