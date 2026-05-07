"use client"

import { useState, useRef } from "react"
import { useSearchParams } from "next/navigation"
import { toast } from "sonner"
import { FileSpreadsheet, Upload as UploadIcon, Check, AlertCircle } from "lucide-react"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api"

interface AlertExample {
  date: string
  payee: string
  product: string
  qty: number
  total?: number
  cogs_total?: number
  margin?: number
  cogs_book?: number
  cogs_real?: number
  unit_book?: number
  unit_real?: number
  diff?: number
}

interface SalesAlerts {
  cogs_book_vs_real_diff?: { count: number; total_diff: number; examples: AlertExample[] }
  negative_margin?: { count: number; rows: AlertExample[] }
  missing_cogs?: { count: number; rows: AlertExample[] }
}

interface PurchasesAlerts {
  unit_price_book_vs_real_diff?: { count: number; total_diff: number; examples: AlertExample[] }
  missing_unit_price?: { count: number; rows: AlertExample[] }
}

interface ImportResult {
  total_rows: number
  inserted: number
  duplicates: number
  errors?: string[]
  alerts?: SalesAlerts & PurchasesAlerts
}

function fmtKRW(n: number): string {
  return `₩${Math.round(n).toLocaleString("ko-KR")}`
}

interface Props {
  kind: "sales" | "purchases"
}

const KIND_META = {
  sales: {
    title: "매출관리 (도매 매출 마스터)",
    desc: "매출관리 xlsx — 제품 단위 row 적재. col 41/42 매입가는 매출원가(COGS) 단가.",
    endpoint: "/upload/wholesale-sales",
    accent: "border-emerald-500/15 bg-emerald-500/[0.04]",
    iconColor: "text-emerald-300",
  },
  purchases: {
    title: "매입관리 (도매 매입 마스터)",
    desc: "매입관리 xlsx — 제품 단위 매입 row 적재. 재고/COGS 검증용.",
    endpoint: "/upload/wholesale-purchases",
    accent: "border-purple-500/15 bg-purple-500/[0.04]",
    iconColor: "text-purple-300",
  },
}

export function WholesaleUpload({ kind }: Props) {
  const meta = KIND_META[kind]
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity")
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleFile = async (file: File | null) => {
    if (!file || !entityId) return
    setBusy(true)
    setResult(null)
    setError(null)
    const fd = new FormData()
    fd.append("file", file)
    try {
      const res = await fetch(
        `${API_BASE}${meta.endpoint}?entity_id=${entityId}`,
        { method: "POST", body: fd },
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || "업로드 실패")
      setResult(data)
      toast.success(`${data.inserted}/${data.total_rows}건 적재 (${data.duplicates}건 중복)`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : "업로드 실패"
      setError(msg)
      toast.error(msg)
    } finally {
      setBusy(false)
      if (inputRef.current) inputRef.current.value = ""
    }
  }

  return (
    <Card className={cn("p-5 rounded-2xl", meta.accent)}>
      <div className="flex items-start gap-3">
        <FileSpreadsheet className={cn("h-5 w-5 shrink-0 mt-0.5", meta.iconColor)} />
        <div className="flex-1 min-w-0">
          <h3 className="font-medium text-sm">{meta.title}</h3>
          <p className="text-xs text-muted-foreground/80 mt-1">{meta.desc}</p>

          <div className="flex items-center gap-2 mt-3 flex-wrap">
            <input
              ref={inputRef}
              type="file"
              accept=".xlsx,.xls"
              className="hidden"
              onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
            />
            <Button
              variant="secondary"
              size="sm"
              onClick={() => inputRef.current?.click()}
              disabled={busy || !entityId}
              className="gap-2"
            >
              <UploadIcon className="h-3.5 w-3.5" />
              {busy ? "처리 중..." : "Excel 선택"}
            </Button>
          </div>

          {result && (
            <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
              <div className="flex flex-col items-start gap-0.5">
                <span className="text-muted-foreground">전체</span>
                <span className="font-mono">{result.total_rows}</span>
              </div>
              <div className="flex flex-col items-start gap-0.5">
                <span className="text-muted-foreground">신규</span>
                <span className="font-mono text-emerald-400">{result.inserted}</span>
              </div>
              <div className="flex flex-col items-start gap-0.5">
                <span className="text-muted-foreground">중복</span>
                <span className={cn("font-mono", result.duplicates > 0 ? "text-amber-400" : "text-muted-foreground/50")}>
                  {result.duplicates}
                </span>
              </div>
              {result.errors && result.errors.length > 0 && (
                <div className="col-span-3 mt-1 p-2 bg-red-500/5 border border-red-500/15 rounded text-[11px] text-red-300">
                  <div className="flex items-center gap-1 mb-1">
                    <AlertCircle className="h-3 w-3" /> 오류 ({result.errors.length})
                  </div>
                  {result.errors.slice(0, 3).map((err, i) => (
                    <div key={i} className="font-mono truncate">{err}</div>
                  ))}
                </div>
              )}
              {result.errors?.length === 0 && result.inserted > 0 && (
                <div className="col-span-3 flex items-center gap-1 text-emerald-400 text-[11px]">
                  <Check className="h-3 w-3" /> 적재 완료
                </div>
              )}
            </div>
          )}

          {result?.alerts && <AlertsPanel alerts={result.alerts} kind={kind} />}

          {error && (
            <div className="mt-3 flex items-center gap-1.5 text-xs text-red-400">
              <AlertCircle className="h-3 w-3" /> {error}
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}

function AlertsPanel({
  alerts,
  kind,
}: {
  alerts: SalesAlerts & PurchasesAlerts
  kind: "sales" | "purchases"
}) {
  const items: { id: string; level: "warn" | "info"; title: string; subtitle?: string; rows?: AlertExample[] }[] = []

  if (kind === "sales") {
    const diff = alerts.cogs_book_vs_real_diff
    if (diff && diff.count > 0) {
      items.push({
        id: "cogs-diff",
        level: "info",
        title: `매입가 장부≠실 ${diff.count}건`,
        subtitle: `차액 합계 ${fmtKRW(diff.total_diff)}`,
        rows: diff.examples,
      })
    }
    const neg = alerts.negative_margin
    if (neg && neg.count > 0) {
      items.push({
        id: "neg-margin",
        level: "warn",
        title: `손실 판매 ${neg.count}건`,
        subtitle: "매출액 < 매출원가 (loss leader / 재고 처분 / 매입가 오기재 의심)",
        rows: neg.rows,
      })
    }
    const missing = alerts.missing_cogs
    if (missing && missing.count > 0) {
      items.push({
        id: "missing-cogs",
        level: "warn",
        title: `매입가 누락 ${missing.count}건`,
        subtitle: "매출원가 미반영 — 매출관리 xlsx 의 col 41 (매입가-장부) 비어있음",
        rows: missing.rows,
      })
    }
  } else {
    const diff = alerts.unit_price_book_vs_real_diff
    if (diff && diff.count > 0) {
      items.push({
        id: "unit-diff",
        level: "info",
        title: `매입단가 장부≠실 ${diff.count}건`,
        subtitle: `차액 합계 ${fmtKRW(diff.total_diff)}`,
        rows: diff.examples,
      })
    }
    const missing = alerts.missing_unit_price
    if (missing && missing.count > 0) {
      items.push({
        id: "missing-unit",
        level: "warn",
        title: `매입단가 누락 ${missing.count}건`,
        rows: missing.rows,
      })
    }
  }

  if (items.length === 0) {
    return (
      <div className="mt-3 flex items-center gap-1.5 text-[11px] text-emerald-400/80">
        <Check className="h-3 w-3" /> 회계 이상 패턴 없음 (매입가/마진/누락 모두 정상)
      </div>
    )
  }

  return (
    <div className="mt-3 space-y-2">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground/60 font-semibold">
        회계 이상 패턴
      </div>
      {items.map((item) => (
        <details
          key={item.id}
          className={cn(
            "rounded border text-xs",
            item.level === "warn"
              ? "border-amber-500/20 bg-amber-500/[0.04]"
              : "border-blue-500/20 bg-blue-500/[0.04]",
          )}
        >
          <summary
            className={cn(
              "cursor-pointer px-3 py-2 flex items-center gap-2 select-none",
              item.level === "warn" ? "text-amber-300" : "text-blue-300",
            )}
          >
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            <span className="font-medium">{item.title}</span>
            {item.subtitle && (
              <span className="text-muted-foreground text-[11px] truncate">· {item.subtitle}</span>
            )}
          </summary>
          {item.rows && item.rows.length > 0 && (
            <div className="px-3 pb-2 space-y-0.5 text-[11px] font-mono">
              {item.rows.slice(0, 10).map((r, i) => (
                <div key={i} className="grid grid-cols-[80px_120px_1fr_auto] gap-2 truncate">
                  <span className="text-muted-foreground">{r.date}</span>
                  <span className="truncate" title={r.payee}>{r.payee}</span>
                  <span className="truncate text-muted-foreground/80" title={r.product}>{r.product}</span>
                  <span className="text-right tabular-nums">
                    {item.id === "neg-margin"
                      ? `qty ${r.qty} · 매출 ${fmtKRW(r.total ?? 0)} · 원가 ${fmtKRW(r.cogs_total ?? 0)} · ${fmtKRW(r.margin ?? 0)}`
                      : item.id === "cogs-diff"
                      ? `qty ${r.qty} · 장부 ${fmtKRW(r.cogs_book ?? 0)} / 실 ${fmtKRW(r.cogs_real ?? 0)} · 차 ${fmtKRW(r.diff ?? 0)}`
                      : item.id === "unit-diff"
                      ? `qty ${r.qty} · 장부 ${fmtKRW(r.unit_book ?? 0)} / 실 ${fmtKRW(r.unit_real ?? 0)} · 차 ${fmtKRW(r.diff ?? 0)}`
                      : `qty ${r.qty}${r.total ? ` · 매출 ${fmtKRW(r.total)}` : ""}`}
                  </span>
                </div>
              ))}
              {item.rows.length > 10 && (
                <div className="text-muted-foreground/60 pt-1">…외 {item.rows.length - 10}건</div>
              )}
            </div>
          )}
        </details>
      ))}
    </div>
  )
}
