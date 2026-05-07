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
  total: number
  matched: number
  ambiguous: number
  unmatched: number
  unmatched_rows?: Array<{ date: string; amount: number; payee: string; memo: string }>
}

export function TransferMemoUpload() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity")
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [overwrite, setOverwrite] = useState(false)
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
        `${API_BASE}/upload/transfer-history?entity_id=${entityId}&overwrite=${overwrite}`,
        { method: "POST", body: fd },
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(data.detail || "업로드 실패")
      }
      setResult(data)
      toast.success(`${data.matched}/${data.total}건 메모 매칭 완료`)
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
    <Card className="p-5 rounded-2xl bg-secondary/40 border-blue-500/15">
      <div className="flex items-start gap-3">
        <FileSpreadsheet className="h-5 w-5 text-blue-300 shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-medium text-sm">이체결과내역 메모 보강</h3>
            <span className="text-[10px] text-muted-foreground/70">
              BZ뱅크 grid_exceldata · 신규 거래 생성 X · 메모만 매칭
            </span>
          </div>
          <p className="text-xs text-muted-foreground/80 mt-1">
            이체 시 입력한 거래메모(주정차과태료/본사임대료/운영자금 상환 등)를
            기존 거래에 매칭해 매핑 정확도 향상.
          </p>

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
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
              <input
                type="checkbox"
                checked={overwrite}
                onChange={(e) => setOverwrite(e.target.checked)}
                className="h-3 w-3"
              />
              기존 메모 덮어쓰기
            </label>
          </div>

          {result && (
            <div className="mt-3 grid grid-cols-4 gap-2 text-xs">
              <div className="flex flex-col items-start gap-0.5">
                <span className="text-muted-foreground">전체</span>
                <span className="font-mono">{result.total}</span>
              </div>
              <div className="flex flex-col items-start gap-0.5">
                <span className="text-muted-foreground">매칭</span>
                <span className="font-mono text-green-400">{result.matched}</span>
              </div>
              <div className="flex flex-col items-start gap-0.5">
                <span className="text-muted-foreground">중복후보</span>
                <span className={cn("font-mono", result.ambiguous > 0 ? "text-amber-400" : "text-muted-foreground/50")}>
                  {result.ambiguous}
                </span>
              </div>
              <div className="flex flex-col items-start gap-0.5">
                <span className="text-muted-foreground">미매칭</span>
                <span className={cn("font-mono", result.unmatched > 0 ? "text-amber-400" : "text-muted-foreground/50")}>
                  {result.unmatched}
                </span>
              </div>
              {result.unmatched_rows && result.unmatched_rows.length > 0 && (
                <div className="col-span-4 mt-1 p-2 bg-amber-500/5 border border-amber-500/15 rounded text-[11px] text-muted-foreground">
                  <div className="flex items-center gap-1 text-amber-300 mb-1">
                    <AlertCircle className="h-3 w-3" /> 미매칭 (최대 20건 표시)
                  </div>
                  {result.unmatched_rows.slice(0, 5).map((row, i) => (
                    <div key={i} className="font-mono">
                      {row.date} ₩{row.amount.toLocaleString()} {row.payee} — {row.memo}
                    </div>
                  ))}
                </div>
              )}
              {result.matched === result.total && result.total > 0 && (
                <div className="col-span-4 flex items-center gap-1 text-green-400 text-[11px]">
                  <Check className="h-3 w-3" /> 모든 행 매칭 성공
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
