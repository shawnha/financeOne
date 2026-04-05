"use client"

import { useState, useRef, useCallback, useEffect, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { EntityTabs } from "@/components/entity-tabs"
import { fetchAPI } from "@/lib/api"
import { toast } from "sonner"
import {
  Upload,
  FileSpreadsheet,
  CheckCircle2,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  X,
  RefreshCw,
  Trash2,
  RotateCw,
} from "lucide-react"

// ── Types ──────────────────────────────────────────────

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api"

interface UploadResult {
  uploaded: number
  errors: string[]
  file: string
  source_type: string
  duplicates: number
}

interface UploadHistoryItem {
  id: number
  entity_id: number
  entity_name: string
  filename: string
  source_type: string
  row_count: number
  duplicate_count: number
  status: string
  uploaded_at: string
}

interface UploadHistoryResponse {
  items: UploadHistoryItem[]
  total: number
  page: number
  pages: number
}

interface FileUploadState {
  file: File
  progress: number
  result: UploadResult | null
  error: string | null
  status: "pending" | "uploading" | "success" | "error"
}

// ── Source Type Badge ──────────────────────────────────

function SourceBadge({ source }: { source: string }) {
  const config: Record<string, { label: string; className: string }> = {
    lotte_card: { label: "롯데카드", className: "bg-red-500/20 text-red-400 border-red-500/30" },
    woori_card: { label: "우리카드", className: "bg-blue-500/20 text-blue-400 border-blue-500/30" },
    woori_bank: { label: "우리은행", className: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30" },
    kb_bank: { label: "국민은행", className: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30" },
    shinhan_card: { label: "신한카드", className: "bg-indigo-500/20 text-indigo-400 border-indigo-500/30" },
  }
  const c = config[source] || { label: source, className: "bg-secondary text-secondary-foreground" }
  return (
    <Badge variant="outline" className={`text-[11px] px-1.5 py-0 ${c.className}`}>
      {c.label}
    </Badge>
  )
}

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { label: string; className: string }> = {
    completed: { label: "완료", className: "bg-[hsl(var(--profit))]/20 text-[hsl(var(--profit))]" },
    processing: { label: "처리중", className: "bg-blue-500/20 text-blue-400" },
    failed: { label: "실패", className: "bg-[hsl(var(--loss))]/20 text-[hsl(var(--loss))]" },
    partial: { label: "부분완료", className: "bg-[hsl(var(--warning))]/20 text-[hsl(var(--warning))]" },
  }
  const c = config[status] || { label: status, className: "bg-secondary text-secondary-foreground" }
  return (
    <Badge variant="outline" className={`text-[11px] px-1.5 py-0 border-0 ${c.className}`}>
      {c.label}
    </Badge>
  )
}

// ── Upload Zone ────────────────────────────────────────

const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10MB

function UploadZone({
  entityId,
  onUploadComplete,
}: {
  entityId: string
  onUploadComplete: () => void
}) {
  const [isDragging, setIsDragging] = useState(false)
  const [fileStates, setFileStates] = useState<FileUploadState[]>([])
  const [expandedErrors, setExpandedErrors] = useState<Set<number>>(new Set())
  const inputRef = useRef<HTMLInputElement>(null)

  const validateFiles = useCallback(
    (files: FileList | File[]): File[] => {
      const valid: File[] = []
      const fileArr = Array.from(files)

      for (const file of fileArr) {
        if (file.size > MAX_FILE_SIZE) {
          toast.error(`${file.name}: 파일 크기가 10MB를 초과합니다.`)
          continue
        }
        const ext = file.name.toLowerCase().split(".").pop()
        if (ext !== "xls" && ext !== "xlsx") {
          toast.error(`${file.name}: .xls 또는 .xlsx 파일만 업로드 가능합니다.`)
          continue
        }
        valid.push(file)
      }

      return valid
    },
    [],
  )

  const uploadFile = useCallback(
    async (file: File, index: number) => {
      setFileStates((prev) => {
        const next = [...prev]
        next[index] = { ...next[index], status: "uploading", progress: 0 }
        return next
      })

      // Simulate progress since fetch doesn't support progress natively
      const progressInterval = setInterval(() => {
        setFileStates((prev) => {
          const next = [...prev]
          if (next[index] && next[index].status === "uploading" && next[index].progress < 90) {
            next[index] = { ...next[index], progress: next[index].progress + 10 }
          }
          return next
        })
      }, 150)

      try {
        const form = new FormData()
        form.append("file", file)

        const res = await fetch(
          `${API_BASE}/upload?entity_id=${entityId}`,
          { method: "POST", body: form },
        )

        clearInterval(progressInterval)

        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: "업로드 실패" }))
          setFileStates((prev) => {
            const next = [...prev]
            next[index] = {
              ...next[index],
              status: "error",
              progress: 100,
              error: err.detail || "업로드 실패",
            }
            return next
          })
          return
        }

        const result: UploadResult = await res.json()

        setFileStates((prev) => {
          const next = [...prev]
          next[index] = {
            ...next[index],
            status: result.errors?.length > 0 && result.uploaded === 0 ? "error" : "success",
            progress: 100,
            result,
            error: null,
          }
          return next
        })

        onUploadComplete()
      } catch (err) {
        clearInterval(progressInterval)
        setFileStates((prev) => {
          const next = [...prev]
          next[index] = {
            ...next[index],
            status: "error",
            progress: 100,
            error: err instanceof Error ? err.message : "네트워크 오류",
          }
          return next
        })
      }
    },
    [entityId, onUploadComplete],
  )

  const handleFiles = useCallback(
    (files: FileList | File[]) => {
      const valid = validateFiles(files)
      if (valid.length === 0) return

      const startIndex = fileStates.length
      const newStates: FileUploadState[] = valid.map((file) => ({
        file,
        progress: 0,
        result: null,
        error: null,
        status: "pending" as const,
      }))

      setFileStates((prev) => [...prev, ...newStates])

      valid.forEach((file, i) => {
        uploadFile(file, startIndex + i)
      })
    },
    [validateFiles, uploadFile, fileStates.length],
  )

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setIsDragging(false)
      if (e.dataTransfer.files.length > 0) {
        handleFiles(e.dataTransfer.files)
      }
    },
    [handleFiles],
  )

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        handleFiles(e.target.files)
        // Reset input so same file can be re-selected
        e.target.value = ""
      }
    },
    [handleFiles],
  )

  const toggleErrors = useCallback((index: number) => {
    setExpandedErrors((prev) => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }, [])

  const removeFileState = useCallback((index: number) => {
    setFileStates((prev) => prev.filter((_, i) => i !== index))
  }, [])

  // Summary for multiple files
  const completedFiles = fileStates.filter((f) => f.status === "success" || f.status === "error")
  const allDone = fileStates.length > 0 && completedFiles.length === fileStates.length
  const totalUploaded = fileStates
    .filter((f) => f.status === "success")
    .reduce((sum, f) => sum + (f.result?.uploaded || 0), 0)

  return (
    <div className="space-y-4">
      {/* Drop Zone */}
      <div
        role="button"
        tabIndex={0}
        aria-label="파일 업로드 영역. 클릭하거나 파일을 드래그하세요."
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault()
            inputRef.current?.click()
          }
        }}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`
          flex flex-col items-center justify-center gap-4 rounded-xl
          border-2 border-dashed p-12 cursor-pointer transition-colors
          min-h-[280px]
          ${
            isDragging
              ? "border-accent bg-accent/5"
              : "border-border bg-card hover:border-muted-foreground/30"
          }
        `}
      >
        <Upload
          className={`h-12 w-12 ${
            isDragging ? "text-accent" : "text-muted-foreground"
          }`}
        />
        <div className="text-center">
          <p className="text-sm text-foreground">
            Excel 파일을 드래그하거나 클릭하세요
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            .xls, .xlsx &middot; 최대 10MB
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={(e) => {
            e.stopPropagation()
            inputRef.current?.click()
          }}
          type="button"
        >
          파일 선택
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept=".xls,.xlsx"
          multiple
          onChange={handleInputChange}
          className="hidden"
          aria-hidden="true"
        />
      </div>

      {/* File Upload Results */}
      {fileStates.map((fs, index) => (
        <Card key={`${fs.file.name}-${index}`} className="">
          <CardContent className="p-4 space-y-3">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-2 min-w-0">
                <FileSpreadsheet className="h-5 w-5 text-accent shrink-0" />
                <span className="text-sm font-medium truncate">{fs.file.name}</span>
                {fs.result?.source_type && (
                  <SourceBadge source={fs.result.source_type} />
                )}
              </div>
              {(fs.status === "success" || fs.status === "error") && (
                <button
                  onClick={() => removeFileState(index)}
                  className="text-muted-foreground hover:text-foreground p-1"
                  aria-label="닫기"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>

            {/* Progress */}
            <Progress
              value={fs.progress}
              className="h-1"
              aria-label={`업로드 진행률 ${fs.progress}%`}
            />

            {/* Status */}
            {fs.status === "uploading" && (
              <p className="text-xs text-muted-foreground">업로드 중...</p>
            )}

            {fs.status === "success" && fs.result && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm">
                  <CheckCircle2 className="h-4 w-4 text-[hsl(var(--profit))]" />
                  <span>
                    <span className="text-[hsl(var(--profit))] font-medium">
                      {fs.result.uploaded}건
                    </span>
                    {" 파싱 완료"}
                    {fs.result.duplicates > 0 && (
                      <>
                        {" "}
                        &middot;{" "}
                        <span className="text-[hsl(var(--warning))]">
                          중복 {fs.result.duplicates}건
                        </span>
                      </>
                    )}
                  </span>
                </div>

                {/* Errors (expandable) */}
                {fs.result.errors && fs.result.errors.length > 0 && (
                  <div>
                    <button
                      onClick={() => toggleErrors(index)}
                      className="flex items-center gap-1 text-xs text-[hsl(var(--warning))] hover:text-foreground"
                    >
                      <AlertCircle className="h-3 w-3" />
                      오류 {fs.result.errors.length}건
                      {expandedErrors.has(index) ? (
                        <ChevronUp className="h-3 w-3" />
                      ) : (
                        <ChevronDown className="h-3 w-3" />
                      )}
                    </button>
                    {expandedErrors.has(index) && (
                      <ul className="mt-1 space-y-0.5 text-xs text-[hsl(var(--loss))]">
                        {fs.result.errors.map((err, i) => (
                          <li key={i} className="pl-4">
                            {err}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                <Button
                  asChild
                  size="sm"
                  className="bg-[hsl(var(--accent))] text-accent-foreground hover:bg-[hsl(var(--accent))]/90"
                >
                  <a href={`/transactions?entity=${entityId}`}>
                    거래내역 보기
                  </a>
                </Button>
              </div>
            )}

            {fs.status === "error" && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm text-[hsl(var(--loss))]">
                  <AlertCircle className="h-4 w-4" />
                  <span>{fs.error || "업로드 실패"}</span>
                </div>

                {/* Show errors from result if available */}
                {fs.result?.errors && fs.result.errors.length > 0 && (
                  <div>
                    <button
                      onClick={() => toggleErrors(index)}
                      className="flex items-center gap-1 text-xs text-[hsl(var(--loss))] hover:text-foreground"
                    >
                      상세 오류 {fs.result.errors.length}건
                      {expandedErrors.has(index) ? (
                        <ChevronUp className="h-3 w-3" />
                      ) : (
                        <ChevronDown className="h-3 w-3" />
                      )}
                    </button>
                    {expandedErrors.has(index) && (
                      <ul className="mt-1 space-y-0.5 text-xs text-[hsl(var(--loss))]">
                        {fs.result.errors.map((err, i) => (
                          <li key={i} className="pl-4">
                            {err}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => uploadFile(fs.file, index)}
                  className="gap-1"
                >
                  <RefreshCw className="h-3 w-3" />
                  다시 시도
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      ))}

      {/* Multi-file summary */}
      {allDone && fileStates.length > 1 && (
        <div className="text-center text-sm text-muted-foreground py-2">
          {fileStates.filter((f) => f.status === "success").length}개 파일, 총{" "}
          <span className="text-[hsl(var(--profit))] font-medium">{totalUploaded}건</span>{" "}
          업로드 완료
        </div>
      )}
    </div>
  )
}

// ── Upload History ─────────────────────────────────────

function HistorySkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex items-center gap-4">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 w-40 flex-1" />
          <Skeleton className="h-5 w-16" />
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-4 w-12" />
          <Skeleton className="h-4 w-12" />
          <Skeleton className="h-5 w-14" />
        </div>
      ))}
    </div>
  )
}

function extractDataMonth(filename: string, uploadedAt: string): string | null {
  // 1) 연도+월: "2026년01월", "2026-01", "2026_01"
  const withYear = filename.match(/(\d{4})[년\-_.]?\s*(\d{1,2})월/)
  if (withYear) return `${withYear[1]}-${withYear[2].padStart(2, "0")}`

  // 2) 월만: "1월", "12월" → 업로드일에서 연도 추정
  const monthOnly = filename.match(/(\d{1,2})월/)
  if (monthOnly) {
    const fileMonth = Number(monthOnly[1])
    if (fileMonth < 1 || fileMonth > 12) return null
    const uploadDate = new Date(uploadedAt)
    const uploadMonth = uploadDate.getMonth() + 1
    const uploadYear = uploadDate.getFullYear()
    // 파일 월이 업로드 월보다 크면 전년도 데이터 (예: 12월 파일을 3월에 업로드)
    const year = fileMonth > uploadMonth ? uploadYear - 1 : uploadYear
    return `${year}-${String(fileMonth).padStart(2, "0")}`
  }

  return null
}

function groupByMonth(items: UploadHistoryItem[]): { month: string; label: string; items: UploadHistoryItem[] }[] {
  const groups = new Map<string, UploadHistoryItem[]>()
  for (const item of items) {
    const dataMonth = extractDataMonth(item.filename, item.uploaded_at)
    const key = dataMonth || (() => {
      const d = new Date(item.uploaded_at)
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
    })()
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(item)
  }
  return Array.from(groups.entries())
    .sort((a, b) => b[0].localeCompare(a[0]))
    .map(([key, items]) => {
      const [y, m] = key.split("-").map(Number)
      return { month: key, label: `${y}년 ${m}월 데이터`, items }
    })
}

function UploadHistory({ entityId }: { entityId: string }) {
  const [history, setHistory] = useState<UploadHistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchHistory = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchAPI<UploadHistoryResponse>(
        `/upload/history?entity_id=${entityId}`,
      )
      setHistory(data.items)
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "업로드 이력을 불러올 수 없습니다.",
      )
    } finally {
      setLoading(false)
    }
  }, [entityId])

  useEffect(() => {
    fetchHistory()
  }, [fetchHistory])

  // Expose refetch via custom event
  useEffect(() => {
    const handler = () => fetchHistory()
    window.addEventListener("upload-history-refresh", handler)
    return () => window.removeEventListener("upload-history-refresh", handler)
  }, [fetchHistory])

  if (loading) return <HistorySkeleton />

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-8 gap-3">
        <AlertCircle className="h-8 w-8 text-[hsl(var(--loss))]" />
        <p className="text-sm text-muted-foreground">{error}</p>
        <Button variant="secondary" size="sm" onClick={fetchHistory} className="gap-1">
          <RefreshCw className="h-3 w-3" />
          다시 시도
        </Button>
      </div>
    )
  }

  if (history.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 gap-2">
        <Upload className="h-8 w-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          업로드 이력이 없습니다. 첫 데이터를 업로드해보세요!
        </p>
      </div>
    )
  }

  const monthGroups = groupByMonth(history)

  return (
    <div className="space-y-0">
      {monthGroups.map((group) => (
        <div key={group.month}>
          <div className="flex items-center gap-2 px-4 py-2.5 bg-muted/20 border-b border-border">
            <span className="text-xs font-semibold text-muted-foreground">{group.label}</span>
            <Badge variant="outline" className="text-[10px] px-1.5 py-0 bg-muted/30 text-muted-foreground border-0">
              {group.items.length}건
            </Badge>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[120px]">업로드일</TableHead>
                <TableHead>파일명</TableHead>
                <TableHead className="w-[90px]">출처</TableHead>
                <TableHead className="w-[100px]">법인</TableHead>
                <TableHead className="w-[80px] text-right">건수</TableHead>
                <TableHead className="w-[80px] text-right">중복</TableHead>
                <TableHead className="w-[100px]">상태</TableHead>
                <TableHead className="w-[50px]"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {group.items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="text-xs text-muted-foreground">
                    {new Date(item.uploaded_at).toLocaleDateString("ko-KR")}
                  </TableCell>
                  <TableCell className="text-sm font-medium truncate max-w-[200px]">
                    {item.filename}
                  </TableCell>
                  <TableCell>
                    <SourceBadge source={item.source_type} />
                  </TableCell>
                  <TableCell className="text-sm">{item.entity_name}</TableCell>
                  <TableCell className="text-right font-mono text-sm">
                    {item.row_count.toLocaleString()}
                  </TableCell>
                  <TableCell
                    className={`text-right font-mono text-sm ${
                      item.duplicate_count > 0 ? "text-[hsl(var(--warning))]" : ""
                    }`}
                  >
                    {item.duplicate_count > 0 ? item.duplicate_count.toLocaleString() : "-"}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={item.status} />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={async (e) => {
                          e.stopPropagation()
                          try {
                            const result = await fetchAPI<{ member_matched: number; account_matched: number }>(`/upload/file/${item.id}/rematch`, { method: "POST" })
                            toast.success(`재매칭 완료: 멤버 ${result.member_matched}건, 계정 ${result.account_matched}건`)
                            fetchHistory()
                          } catch (err) {
                            toast.error(err instanceof Error ? err.message : "재매칭 실패")
                          }
                        }}
                        className="text-muted-foreground hover:text-accent transition-colors"
                        title="멤버/계정 재매칭"
                      >
                        <RotateCw className="h-4 w-4" />
                      </button>
                      <button
                        onClick={async () => {
                          if (!confirm(`"${item.filename}" 파일과 ${item.row_count}건 거래를 삭제하시겠습니까?`)) return
                          try {
                            await fetchAPI(`/upload/file/${item.id}`, { method: "DELETE" })
                            fetchHistory()
                            window.dispatchEvent(new Event("upload-history-refresh"))
                          } catch (err) {
                            alert(err instanceof Error ? err.message : "삭제 실패")
                          }
                        }}
                        className="text-muted-foreground hover:text-[hsl(var(--loss))] transition-colors"
                        title="삭제"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ))}
    </div>
  )
}

// ── Page Content ───────────────────────────────────────

function UploadContent() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity") || "1"

  const handleUploadComplete = useCallback(() => {
    // Trigger history refresh via custom event
    window.dispatchEvent(new Event("upload-history-refresh"))
  }, [])

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">업로드</h1>

      {/* Upload Zone */}
      <UploadZone entityId={entityId} onUploadComplete={handleUploadComplete} />

      {/* Upload History */}
      <div>
        <h2 className="text-lg font-semibold mb-4">업로드 이력</h2>
        <Card className="">
          <CardContent className="p-0">
            <UploadHistory entityId={entityId} />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

// ── Page Export ─────────────────────────────────────────

export default function UploadPage() {
  return (
    <div>
      <Suspense
        fallback={
          <div className="flex gap-1 border-b border-border">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-10 w-32 animate-pulse rounded-t bg-muted"
              />
            ))}
          </div>
        }
      >
        <EntityTabs />
      </Suspense>
      <Suspense
        fallback={
          <div className="p-6 space-y-6">
            <Skeleton className="h-8 w-32" />
            <Skeleton className="h-[280px] w-full rounded-xl" />
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-[200px] w-full rounded-xl" />
          </div>
        }
      >
        <UploadContent />
      </Suspense>
    </div>
  )
}
