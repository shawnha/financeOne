"use client"

import { useState, useRef } from "react"
import { useSearchParams } from "next/navigation"
import { toast } from "sonner"
import { FileSpreadsheet, Upload as UploadIcon, Check, AlertCircle } from "lucide-react"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api"

interface ImportResult {
  total_rows: number
  inserted: number
  duplicates: number
  errors?: string[]
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
