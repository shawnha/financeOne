"use client"

import { useCallback, useState, useEffect, Suspense } from "react"
import { fetchAPI, APIError } from "@/lib/api"
import { EntityTabs } from "@/components/entity-tabs"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Settings,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Wifi,
  Link,
  Receipt,
  Copy,
  AlertCircle,
} from "lucide-react"

interface ConnectionStatus {
  connected: boolean
  error?: string
  accounts?: number
  account_names?: string[]
  environment?: string
  realm_id?: string | null
  last_sync?: string | null
}

interface QBOSyncResult {
  accounts?: { synced: number; total: number }
  transactions?: { synced: number; duplicates: number; total_fetched: number }
}

interface QBOSeedResult {
  seeded: number
  skipped: number
  unmapped: { payee: string; reason: string }[]
  validation: { total: number; matched: number; match_rate: number }
}

interface CodefStatus {
  configured: boolean
  connected: boolean
  environment?: string
  base_url?: string
  connections?: Record<string, string>
  error?: string
}

interface NpkiCert {
  ca: string
  cn: string
  bank: string
  path: string
  label: string
}

interface CodefCardSyncResult {
  card_type: string
  synced: number
  duplicates: number
  cancels: number
  total_fetched: number
  environment?: string
}

interface CodefBankSyncResult {
  synced: number
  duplicates: number
  total_fetched: number
  environment?: string
}

interface CodefErrorDetail {
  message: string
  code: string | null
  transaction_id: string | null
  extra_message: string | null
  endpoint: string | null
  log_id: number | null
}

interface CodefErrorLogEntry {
  id: number
  entity_id: number | null
  organization: string | null
  endpoint: string | null
  result_code: string | null
  message: string | null
  extra_message: string | null
  transaction_id: string | null
  created_at: string | null
}

interface SchedulerResult {
  entity_id?: number
  org?: string
  ok?: boolean
  range?: string
  detail?: unknown
}

interface SchedulerStatus {
  running: boolean
  enabled: boolean
  interval_min: number
  last_run: {
    started_at: string | null
    finished_at: string | null
    ok_count: number
    error_count: number
    results: SchedulerResult[]
  } | null
  jobs?: Array<{ id: string; name: string; next_run_time: string | null }>
}

type CodefOrg =
  | "woori_bank"
  | "ibk_bank"
  | "lotte_card"
  | "bc_card"
  | "samsung_card"
  | "shinhan_card"
  | "hyundai_card"
  | "nh_card"
  | "woori_card"
  | "kb_card"
  | "hana_card"

const CODEF_ORG_LABELS: Record<CodefOrg, string> = {
  woori_bank: "우리은행",
  ibk_bank: "IBK기업은행",
  lotte_card: "롯데카드",
  bc_card: "BC카드",
  samsung_card: "삼성카드",
  shinhan_card: "신한카드",
  hyundai_card: "현대카드",
  nh_card: "NH농협카드",
  woori_card: "우리카드",
  kb_card: "KB국민카드",
  hana_card: "하나카드",
}

// 사용자가 실 보유한 기관만 우선 노출 (나머지는 향후 확장)
const CODEF_ORG_ORDER: CodefOrg[] = [
  "woori_bank",
  "ibk_bank",
  "lotte_card",
  "woori_card",
  "shinhan_card",
]

const CODEF_BANK_ORGS = new Set<CodefOrg>(["woori_bank", "ibk_bank"])

interface GowidStatus {
  configured: boolean
  connected: boolean
  last_sync?: string | null
  synced_count?: number
  key_source?: "settings" | "env" | null
}

interface GowidSyncResult {
  synced: number
  duplicates: number
  auto_mapped: number
  unmapped: number
  skipped: number
  by_issuer: Record<string, number>
}

interface ExpenseOneStatus {
  configured: boolean
  connected: boolean
  error?: string | null
  synced_count?: number
  last_sync?: string | null
}

interface ExpenseOneSyncResult {
  total_fetched: number
  inserted: number
  enriched: number
  duplicates: number
  unmapped: number
  errors: { expense_id?: string; error: string }[]
}

function SettingsContent() {
  const [mercuryToken, setMercuryToken] = useState("")
  const [mercuryStatus, setMercuryStatus] = useState<ConnectionStatus | null>(null)
  const [codefStatus, setCodefStatus] = useState<CodefStatus | null>(null)
  const [codefEntityId, setCodefEntityId] = useState(2)
  const [codefConnectOrg, setCodefConnectOrg] = useState<CodefOrg | null>(null)
  const [codefAuthMode, setCodefAuthMode] = useState<"idpw" | "cert">("idpw")
  const [codefLoginId, setCodefLoginId] = useState("")
  const [codefLoginPw, setCodefLoginPw] = useState("")
  const [codefCardPw, setCodefCardPw] = useState("")        // 카드 4자리 비번
  const [codefBusinessNo, setCodefBusinessNo] = useState("")  // 사업자번호
  const [codefAdvancedOpen, setCodefAdvancedOpen] = useState(false)
  const [codefCertPw, setCodefCertPw] = useState("")
  const [codefDerFileB64, setCodefDerFileB64] = useState("")
  const [codefKeyFileB64, setCodefKeyFileB64] = useState("")
  const [codefCertFileName, setCodefCertFileName] = useState("")
  const [codefNpkiCerts, setCodefNpkiCerts] = useState<NpkiCert[]>([])
  const [codefNpkiCertPath, setCodefNpkiCertPath] = useState("")
  const [codefCertSource, setCodefCertSource] = useState<"npki" | "upload">("npki")
  const [codefSyncStart, setCodefSyncStart] = useState(() => {
    const d = new Date()
    return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}01`
  })
  const [codefSyncEnd, setCodefSyncEnd] = useState(() => {
    const d = new Date()
    return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`
  })
  const [codefSyncResult, setCodefSyncResult] = useState<string | null>(null)
  const [codefError, setCodefError] = useState<string | null>(null)
  const [codefErrorDetail, setCodefErrorDetail] = useState<CodefErrorDetail | null>(null)
  const [codefErrorLog, setCodefErrorLog] = useState<CodefErrorLogEntry[]>([])
  const [codefErrorLogLoading, setCodefErrorLogLoading] = useState(false)
  const [schedulerStatus, setSchedulerStatus] = useState<SchedulerStatus | null>(null)
  const [schedulerRunning, setSchedulerRunning] = useState(false)
  const [qboStatus, setQboStatus] = useState<ConnectionStatus | null>(null)
  const [qboSyncResult, setQboSyncResult] = useState<QBOSyncResult | null>(null)
  const [qboSeedResult, setQboSeedResult] = useState<QBOSeedResult | null>(null)
  const [gowidStatus, setGowidStatus] = useState<GowidStatus | null>(null)
  const [gowidSyncResult, setGowidSyncResult] = useState<GowidSyncResult | null>(null)
  const [gowidError, setGowidError] = useState<string | null>(null)
  const [gowidEntityId, setGowidEntityId] = useState(2)  // 한아원코리아 default
  const [gowidApiKeyInput, setGowidApiKeyInput] = useState("")
  const [gowidStart, setGowidStart] = useState(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`
  })
  const [gowidEnd, setGowidEnd] = useState(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
  })
  const [expenseoneStatus, setExpenseoneStatus] = useState<ExpenseOneStatus | null>(null)
  const [expenseoneSyncResult, setExpenseoneSyncResult] = useState<ExpenseOneSyncResult | null>(null)
  const [expenseoneError, setExpenseoneError] = useState<string | null>(null)
  const [testing, setTesting] = useState<string | null>(null)

  // ExpenseOne 초기 status 로드
  useEffect(() => {
    fetchAPI<ExpenseOneStatus>("/integrations/expenseone/status?entity_id=2")
      .then(setExpenseoneStatus)
      .catch(() => setExpenseoneStatus({ configured: false, connected: false, error: "fetch failed" }))
  }, [])

  // Gowid 초기 status 로드 — entity 선택 변경 시 재로드
  useEffect(() => {
    fetchAPI<GowidStatus>(`/integrations/gowid/status?entity_id=${gowidEntityId}`)
      .then(setGowidStatus)
      .catch(() =>
        setGowidStatus({ configured: false, connected: false }),
      )
    setGowidSyncResult(null)
    setGowidError(null)
    setGowidApiKeyInput("")
  }, [gowidEntityId])

  const reloadGowidStatus = () => {
    fetchAPI<GowidStatus>(`/integrations/gowid/status?entity_id=${gowidEntityId}`)
      .then(setGowidStatus).catch(() => {})
  }

  const saveGowidApiKey = async () => {
    if (!gowidApiKeyInput.trim()) return
    setTesting("gowid-key-save")
    setGowidError(null)
    try {
      await fetchAPI("/integrations/gowid/api-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entity_id: gowidEntityId,
          api_key: gowidApiKeyInput.trim(),
        }),
      })
      setGowidApiKeyInput("")
      reloadGowidStatus()
    } catch (err) {
      setGowidError(err instanceof Error ? err.message : "API key 저장 실패")
    } finally {
      setTesting(null)
    }
  }

  const deleteGowidApiKey = async () => {
    if (!confirm(`${gowidEntityId === 2 ? "한아원코리아" : "한아원리테일"} Gowid 연결을 해제할까요?`)) return
    setTesting("gowid-key-delete")
    try {
      await fetchAPI(`/integrations/gowid/api-key?entity_id=${gowidEntityId}`, {
        method: "DELETE",
      })
      reloadGowidStatus()
    } catch (err) {
      setGowidError(err instanceof Error ? err.message : "해제 실패")
    } finally {
      setTesting(null)
    }
  }

  const syncGowid = async () => {
    setTesting("gowid-sync")
    setGowidError(null)
    setGowidSyncResult(null)
    try {
      const r = await fetchAPI<GowidSyncResult>("/integrations/gowid/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entity_id: gowidEntityId,
          start_date: gowidStart,
          end_date: gowidEnd,
        }),
      })
      setGowidSyncResult(r)
      reloadGowidStatus()
    } catch (err) {
      setGowidError(err instanceof Error ? err.message : "동기화 실패")
    } finally {
      setTesting(null)
    }
  }

  // Codef 초기 status 로드
  useEffect(() => {
    fetchAPI<CodefStatus>(`/integrations/codef/status?entity_id=${codefEntityId}`)
      .then(setCodefStatus)
      .catch((err) =>
        setCodefStatus({
          configured: false,
          connected: false,
          error: err instanceof Error ? err.message : "fetch failed",
        }),
      )
  }, [codefEntityId])

  // NPKI 인증서 목록 로드 (한 번만)
  useEffect(() => {
    fetchAPI<{ certs: NpkiCert[] }>("/integrations/codef/npki/certs")
      .then((r) => setCodefNpkiCerts(r.certs))
      .catch(() => setCodefNpkiCerts([]))
  }, [])

  // 인증서 모드 진입 시, 법인/기관에 맞는 인증서 자동 선택
  useEffect(() => {
    if (codefAuthMode !== "cert" || !codefConnectOrg || codefNpkiCerts.length === 0) return
    const wantedBank = CODEF_ORG_LABELS[codefConnectOrg] // 예: "우리은행"
    const match = codefNpkiCerts.find((c) => {
      const matchesEntity =
        codefEntityId === 3
          ? c.cn.includes("리테일")
          : c.cn.includes("한아원") && !c.cn.includes("리테일")
      const matchesBank =
        c.bank === wantedBank ||
        (CODEF_BANK_ORGS.has(codefConnectOrg) ? c.bank === wantedBank : true)
      return matchesEntity && matchesBank
    })
    if (match) setCodefNpkiCertPath(match.path)
    else setCodefNpkiCertPath("")
  }, [codefAuthMode, codefConnectOrg, codefEntityId, codefNpkiCerts])

  // QBO callback 후 자동 status 체크
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get("qbo") === "connected") {
      fetchAPI<ConnectionStatus>("/integrations/quickbooks/status?entity_id=1")
        .then(setQboStatus)
        .catch(() => {})
      window.history.replaceState({}, "", "/settings")
    }
  }, [])

  const testMercury = async () => {
    setTesting("mercury")
    try {
      const status = await fetchAPI<ConnectionStatus>("/integrations/mercury/status")
      setMercuryStatus(status)
    } catch (err) {
      setMercuryStatus({ connected: false, error: err instanceof Error ? err.message : "Connection failed" })
    } finally {
      setTesting(null)
    }
  }

  const loadCodefStatus = async () => {
    try {
      const status = await fetchAPI<CodefStatus>(
        `/integrations/codef/status?entity_id=${codefEntityId}`,
      )
      setCodefStatus(status)
    } catch (err) {
      setCodefStatus({
        configured: false,
        connected: false,
        error: err instanceof Error ? err.message : "Connection failed",
      })
    }
  }

  const testCodef = async () => {
    setTesting("codef")
    try {
      await loadCodefStatus()
    } finally {
      setTesting(null)
    }
  }

  const resetCodefForm = () => {
    setCodefLoginId("")
    setCodefLoginPw("")
    setCodefCardPw("")
    setCodefBusinessNo("")
    setCodefAdvancedOpen(false)
    setCodefCertPw("")
    setCodefDerFileB64("")
    setCodefKeyFileB64("")
    setCodefCertFileName("")
    setCodefNpkiCertPath("")
    setCodefCertSource("npki")
    setCodefConnectOrg(null)
    setCodefAuthMode("idpw")
  }

  const handleCertFile = async (
    file: File,
    kind: "der" | "key",
  ) => {
    const buf = await file.arrayBuffer()
    const b64 = btoa(
      new Uint8Array(buf).reduce((s, b) => s + String.fromCharCode(b), ""),
    )
    if (kind === "der") setCodefDerFileB64(b64)
    else setCodefKeyFileB64(b64)
    setCodefCertFileName((prev) =>
      prev ? `${prev}, ${file.name}` : file.name,
    )
  }

  const handleCodefError = useCallback(
    (err: unknown, fallback: string) => {
      if (err instanceof APIError) {
        const detail = err.detail
        if (detail && typeof detail === "object" && "transaction_id" in detail) {
          setCodefErrorDetail(detail as unknown as CodefErrorDetail)
          setCodefError(err.message || fallback)
          loadCodefErrorLog()
          return
        }
      }
      setCodefErrorDetail(null)
      setCodefError(err instanceof Error ? err.message : fallback)
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  const loadCodefErrorLog = useCallback(async () => {
    setCodefErrorLogLoading(true)
    try {
      const data = await fetchAPI<{ errors: CodefErrorLogEntry[] }>(
        "/integrations/codef/errors?limit=20",
      )
      setCodefErrorLog(data.errors)
    } catch {
      // silent — 로그 섹션은 부가 기능
    } finally {
      setCodefErrorLogLoading(false)
    }
  }, [])

  const copyToClipboard = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text)
      alert(`${label} 복사됨:\n${text}`)
    } catch {
      // fallback
      window.prompt(`${label} 복사`, text)
    }
  }

  useEffect(() => {
    loadCodefErrorLog()
  }, [loadCodefErrorLog])

  const loadSchedulerStatus = useCallback(async () => {
    try {
      const data = await fetchAPI<SchedulerStatus>(
        "/integrations/codef/scheduler/status",
      )
      setSchedulerStatus(data)
    } catch {
      // silent
    }
  }, [])

  const runSchedulerNow = async () => {
    setSchedulerRunning(true)
    try {
      await fetchAPI("/integrations/codef/scheduler/run-now", { method: "POST" })
      await loadSchedulerStatus()
      await loadCodefErrorLog()
    } catch (err) {
      alert(err instanceof Error ? err.message : "실행 실패")
    } finally {
      setSchedulerRunning(false)
    }
  }

  useEffect(() => {
    loadSchedulerStatus()
    const id = setInterval(loadSchedulerStatus, 30_000)
    return () => clearInterval(id)
  }, [loadSchedulerStatus])

  const connectCodefOrg = async () => {
    if (!codefConnectOrg) return
    setTesting("codef-connect")
    setCodefError(null)
    setCodefErrorDetail(null)
    try {
      const isBank = codefConnectOrg === "woori_bank"
      const account: Record<string, unknown> = {
        organization: codefConnectOrg,
        business_type: isBank ? "BK" : "CD",
        client_type: "B",
      }
      if (codefAuthMode === "idpw") {
        account.login_type = "1"
        account.login_id = codefLoginId
        account.login_password = codefLoginPw
        if (codefCardPw) account.card_password = codefCardPw
        if (codefBusinessNo) account.business_no = codefBusinessNo
      } else {
        account.login_type = "0"
        account.cert_password = codefCertPw
        if (codefCertSource === "npki" && codefNpkiCertPath) {
          account.npki_cert_path = codefNpkiCertPath
        } else {
          account.der_file_b64 = codefDerFileB64
          account.key_file_b64 = codefKeyFileB64
        }
      }
      await fetchAPI("/integrations/codef/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entity_id: codefEntityId,
          accounts: [account],
        }),
      })
      resetCodefForm()
      await loadCodefStatus()
    } catch (err) {
      handleCodefError(err, "연결 실패")
    } finally {
      setTesting(null)
    }
  }

  const disconnectCodefOrg = async (org: CodefOrg) => {
    if (!confirm(`${org} 연결을 해제할까요?`)) return
    setTesting(`codef-disconnect-${org}`)
    try {
      await fetchAPI("/integrations/codef/connections", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_id: codefEntityId, organization: org }),
      })
      await loadCodefStatus()
    } catch (err) {
      handleCodefError(err, "해제 실패")
    } finally {
      setTesting(null)
    }
  }

  const syncCodefOrg = async (org: CodefOrg) => {
    setTesting(`codef-sync-${org}`)
    setCodefError(null)
    setCodefErrorDetail(null)
    setCodefSyncResult(null)
    try {
      if (org === "woori_bank") {
        const result = await fetchAPI<CodefBankSyncResult>("/integrations/codef/sync-bank", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entity_id: codefEntityId,
            start_date: codefSyncStart,
            end_date: codefSyncEnd,
          }),
        })
        setCodefSyncResult(
          `${org}: 총 ${result.total_fetched}건 — 신규 ${result.synced}, 중복 ${result.duplicates}`,
        )
      } else {
        const result = await fetchAPI<CodefCardSyncResult>("/integrations/codef/sync-card", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entity_id: codefEntityId,
            start_date: codefSyncStart,
            end_date: codefSyncEnd,
            card_type: org,
          }),
        })
        setCodefSyncResult(
          `${org}: 총 ${result.total_fetched}건 — 신규 ${result.synced}, 중복 ${result.duplicates}, 취소 ${result.cancels}`,
        )
      }
    } catch (err) {
      handleCodefError(err, "동기화 실패")
    } finally {
      setTesting(null)
    }
  }

  const connectQBO = async () => {
    setTesting("qbo-connect")
    try {
      const data = await fetchAPI<{ auth_url: string }>("/integrations/quickbooks/authorize?entity_id=1")
      window.location.href = data.auth_url
    } catch (err) {
      setQboStatus({ connected: false, error: err instanceof Error ? err.message : "Connection failed" })
      setTesting(null)
    }
  }

  const testQBO = async () => {
    setTesting("qbo")
    try {
      const status = await fetchAPI<ConnectionStatus>("/integrations/quickbooks/status?entity_id=1")
      setQboStatus(status)
    } catch (err) {
      setQboStatus({ connected: false, error: err instanceof Error ? err.message : "Connection failed" })
    } finally {
      setTesting(null)
    }
  }

  const syncQBO = async () => {
    setTesting("qbo-sync")
    setQboSyncResult(null)
    try {
      const result = await fetchAPI<QBOSyncResult>("/integrations/quickbooks/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_id: 1 }),
      })
      setQboSyncResult(result)
    } catch (err) {
      setQboStatus({ connected: true, error: err instanceof Error ? err.message : "Sync failed" })
    } finally {
      setTesting(null)
    }
  }

  const seedQBORules = async () => {
    setTesting("qbo-seed")
    setQboSeedResult(null)
    try {
      const result = await fetchAPI<QBOSeedResult>("/integrations/quickbooks/seed-rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_id: 1 }),
      })
      setQboSeedResult(result)
    } catch (err) {
      setQboStatus({ connected: true, error: err instanceof Error ? err.message : "Seed failed" })
    } finally {
      setTesting(null)
    }
  }

  const syncExpenseOne = async () => {
    setTesting("expenseone-sync")
    setExpenseoneSyncResult(null)
    setExpenseoneError(null)
    try {
      const result = await fetchAPI<ExpenseOneSyncResult>("/integrations/expenseone/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_id: 2 }),
      })
      setExpenseoneSyncResult(result)
      // status 재조회
      fetchAPI<ExpenseOneStatus>("/integrations/expenseone/status?entity_id=2")
        .then(setExpenseoneStatus)
        .catch(() => {})
    } catch (err) {
      setExpenseoneError(err instanceof Error ? err.message : "동기화 실패")
    } finally {
      setTesting(null)
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Mercury API */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Wifi className="h-5 w-5" />
            Mercury API (HOI)
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            HOI Inc.의 USD 거래를 Mercury에서 자동으로 가져옵니다. Read-only 토큰만 사용합니다.
          </p>
          <div className="flex gap-2">
            <Input
              type="password"
              placeholder="Mercury API Token"
              value={mercuryToken}
              onChange={(e) => setMercuryToken(e.target.value)}
              className="flex-1"
            />
            <Button
              variant="outline"
              onClick={testMercury}
              disabled={testing === "mercury"}
            >
              {testing === "mercury" ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                "연결 테스트"
              )}
            </Button>
          </div>
          {mercuryStatus && (
            <StatusBadge status={mercuryStatus} />
          )}
        </CardContent>
      </Card>

      {/* Codef */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Wifi className="h-5 w-5" />
            Codef API (한국 법인)
            {codefStatus?.environment && (
              <span
                className={`text-xs rounded px-2 py-0.5 ml-2 ${
                  codefStatus.environment === "production"
                    ? "bg-green-500/20 text-green-400"
                    : "bg-yellow-500/20 text-yellow-400"
                }`}
              >
                {codefStatus.environment}
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            우리은행, 롯데/우리/신한카드 거래를 Codef.io로 자동 pull.
            샌드박스에서는 테스트 id/pw로 검증, 프로덕션은 공동인증서 필요.
          </p>

          <div className="flex gap-2 items-center">
            <label className="text-xs text-muted-foreground">법인</label>
            <div className="flex rounded-md overflow-hidden border border-border">
              {[
                { id: 2, name: "한아원코리아" },
                { id: 3, name: "한아원리테일" },
              ].map((e) => (
                <button
                  key={e.id}
                  onClick={() => setCodefEntityId(e.id)}
                  className={`px-3 py-1 text-xs transition-colors ${
                    codefEntityId === e.id
                      ? "bg-accent/20 text-accent"
                      : "bg-transparent text-muted-foreground hover:bg-secondary/50"
                  }`}
                >
                  {e.name}
                </button>
              ))}
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={testCodef}
              disabled={testing === "codef"}
            >
              {testing === "codef" ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                "상태 확인"
              )}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground/70 -mt-2">
            법인별로 은행·카드 연결이 독립적이에요 — 한아원코리아와 한아원리테일은 각자 별도 연결.
          </p>

          {codefStatus && !codefStatus.configured && (
            <div className="text-sm text-red-500">
              <XCircle className="inline h-4 w-4 mr-1" />
              CODEF_CLIENT_ID / CODEF_CLIENT_SECRET 환경변수 미설정
            </div>
          )}

          {codefStatus?.configured && (
            <>
              <div className="text-xs text-muted-foreground">
                {codefStatus.connected ? (
                  <span className="text-green-500">
                    <CheckCircle2 className="inline h-3 w-3 mr-1" />
                    API 인증 성공 · {codefStatus.base_url}
                  </span>
                ) : (
                  <span className="text-red-500">
                    <XCircle className="inline h-3 w-3 mr-1" />
                    API 인증 실패 — {codefStatus.error ?? "확인 필요"}
                  </span>
                )}
              </div>

              <div className="space-y-2 rounded-md border border-border bg-secondary/20 p-3">
                <div className="flex items-center justify-between gap-2 mb-1">
                  <div className="text-xs text-muted-foreground">
                    기간 (YYYYMMDD)
                  </div>
                  <div className="flex gap-1">
                    <Input
                      value={codefSyncStart}
                      onChange={(e) => setCodefSyncStart(e.target.value)}
                      className="w-24 h-7 text-xs font-mono"
                      placeholder="20260301"
                    />
                    <span className="text-xs text-muted-foreground self-center">~</span>
                    <Input
                      value={codefSyncEnd}
                      onChange={(e) => setCodefSyncEnd(e.target.value)}
                      className="w-24 h-7 text-xs font-mono"
                      placeholder="20260331"
                    />
                  </div>
                </div>

                {CODEF_ORG_ORDER.map((org) => {
                    const cid = codefStatus.connections?.[org]
                    const syncKey = `codef-sync-${org}`
                    const disconKey = `codef-disconnect-${org}`
                    return (
                      <div
                        key={org}
                        className="flex items-center justify-between gap-2 py-1 border-t border-border first:border-t-0"
                      >
                        <div className="flex flex-col flex-1">
                          <span className="text-sm font-medium">
                            {CODEF_ORG_LABELS[org]}
                            <span className="text-xs text-muted-foreground/70 ml-2 font-mono">
                              {org}
                            </span>
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {cid ? (
                              <span className="text-green-400">
                                connected · ...{cid.slice(-8)}
                              </span>
                            ) : (
                              <span className="text-muted-foreground/70">미연결</span>
                            )}
                          </span>
                        </div>
                        <div className="flex gap-1">
                          {cid ? (
                            <>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => syncCodefOrg(org)}
                                disabled={testing === syncKey}
                              >
                                {testing === syncKey ? (
                                  <RefreshCw className="h-3 w-3 animate-spin" />
                                ) : (
                                  "동기화"
                                )}
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => disconnectCodefOrg(org)}
                                disabled={testing === disconKey}
                              >
                                해제
                              </Button>
                            </>
                          ) : (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => {
                                setCodefConnectOrg(org)
                                // 은행은 공동인증서 필수 → 자동 전환
                                setCodefAuthMode(CODEF_BANK_ORGS.has(org) ? "cert" : "idpw")
                              }}
                            >
                              연결
                            </Button>
                          )}
                        </div>
                      </div>
                    )
                  },
                )}
              </div>

              {codefConnectOrg && (
                <div className="space-y-3 rounded-md border border-yellow-500/30 bg-yellow-500/5 p-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium">{codefConnectOrg} 연결</div>
                    <div className="flex rounded-md overflow-hidden border border-border">
                      {[
                        { key: "idpw" as const, label: "ID/PW" },
                        { key: "cert" as const, label: "공동인증서" },
                      ].map((m) => (
                        <button
                          key={m.key}
                          onClick={() => setCodefAuthMode(m.key)}
                          className={`px-2 py-1 text-xs ${
                            codefAuthMode === m.key
                              ? "bg-accent/20 text-accent"
                              : "bg-transparent text-muted-foreground hover:bg-secondary/50"
                          }`}
                        >
                          {m.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {codefConnectOrg && CODEF_BANK_ORGS.has(codefConnectOrg) && codefAuthMode === "idpw" && (
                    <p className="text-xs text-yellow-500">
                      ⚠️ {CODEF_ORG_LABELS[codefConnectOrg]} 기업뱅킹은 Codef에서 공동인증서 필수입니다. ID/PW로는 실패합니다.
                    </p>
                  )}

                  {codefAuthMode === "idpw" ? (
                    <>
                      <Input
                        placeholder="기관 사이트 login id"
                        value={codefLoginId}
                        onChange={(e) => setCodefLoginId(e.target.value)}
                        className="h-8 text-sm"
                      />
                      <Input
                        type="password"
                        placeholder="기관 사이트 login password"
                        value={codefLoginPw}
                        onChange={(e) => setCodefLoginPw(e.target.value)}
                        className="h-8 text-sm"
                      />
                      {/* 카드 등 일부 기관 추가 필드 — 접기/펼치기 */}
                      {codefConnectOrg && !CODEF_BANK_ORGS.has(codefConnectOrg) && (
                        <div className="space-y-2">
                          <button
                            type="button"
                            onClick={() => setCodefAdvancedOpen((v) => !v)}
                            className="text-xs text-muted-foreground hover:text-foreground"
                          >
                            {codefAdvancedOpen ? "▼" : "▶"} 추가 정보 (CF-12803·12407 등 에러 시)
                          </button>
                          {codefAdvancedOpen && (
                            <>
                              <Input
                                type="password"
                                placeholder="카드 비밀번호 4자리 (선택)"
                                value={codefCardPw}
                                onChange={(e) => setCodefCardPw(e.target.value)}
                                maxLength={4}
                                className="h-8 text-sm"
                              />
                              <Input
                                placeholder="사업자번호 10자리 (선택, 하이픈 없이)"
                                value={codefBusinessNo}
                                onChange={(e) =>
                                  setCodefBusinessNo(e.target.value.replace(/[^0-9]/g, ""))
                                }
                                maxLength={10}
                                className="h-8 text-sm"
                              />
                            </>
                          )}
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      <div className="flex gap-2 items-center">
                        <div className="flex rounded-md overflow-hidden border border-border text-xs">
                          {[
                            { key: "npki" as const, label: "설치된 인증서" },
                            { key: "upload" as const, label: "파일 직접 업로드" },
                          ].map((s) => (
                            <button
                              key={s.key}
                              onClick={() => setCodefCertSource(s.key)}
                              className={`px-2 py-1 ${
                                codefCertSource === s.key
                                  ? "bg-accent/20 text-accent"
                                  : "bg-transparent text-muted-foreground hover:bg-secondary/50"
                              }`}
                            >
                              {s.label}
                            </button>
                          ))}
                        </div>
                        <span className="text-xs text-muted-foreground/70">
                          {codefNpkiCerts.length}개 인증서 발견
                        </span>
                      </div>

                      {codefCertSource === "npki" ? (
                        codefNpkiCerts.length > 0 ? (
                          <select
                            value={codefNpkiCertPath}
                            onChange={(e) => setCodefNpkiCertPath(e.target.value)}
                            className="h-8 w-full rounded-md border border-border bg-background text-sm px-2"
                          >
                            <option value="">인증서 선택...</option>
                            {codefNpkiCerts.map((c) => (
                              <option key={c.path} value={c.path}>
                                {c.label}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <p className="text-xs text-muted-foreground">
                            ~/Library/Preferences/NPKI 또는 ~/NPKI 에서 인증서를 찾지 못함. 파일 업로드 사용.
                          </p>
                        )
                      ) : (
                        <>
                          <p className="text-xs text-muted-foreground">
                            signCert.der + signPri.key 두 파일 업로드
                          </p>
                          <div>
                            <label className="text-xs text-muted-foreground block mb-1">
                              signCert.der
                            </label>
                            <input
                              type="file"
                              accept=".der,application/octet-stream"
                              onChange={(e) => {
                                const f = e.target.files?.[0]
                                if (f) handleCertFile(f, "der")
                              }}
                              className="text-xs"
                            />
                          </div>
                          <div>
                            <label className="text-xs text-muted-foreground block mb-1">
                              signPri.key
                            </label>
                            <input
                              type="file"
                              accept=".key,application/octet-stream"
                              onChange={(e) => {
                                const f = e.target.files?.[0]
                                if (f) handleCertFile(f, "key")
                              }}
                              className="text-xs"
                            />
                          </div>
                          {codefCertFileName && (
                            <p className="text-xs text-muted-foreground/70">
                              선택됨: {codefCertFileName}
                            </p>
                          )}
                        </>
                      )}

                      <Input
                        type="password"
                        placeholder="공동인증서 비밀번호"
                        value={codefCertPw}
                        onChange={(e) => setCodefCertPw(e.target.value)}
                        className="h-8 text-sm"
                      />
                    </>
                  )}

                  <div className="flex gap-2">
                    <Button
                      variant="default"
                      size="sm"
                      onClick={connectCodefOrg}
                      disabled={
                        testing === "codef-connect" ||
                        (codefAuthMode === "idpw"
                          ? !codefLoginId || !codefLoginPw
                          : !codefCertPw ||
                            (codefCertSource === "npki"
                              ? !codefNpkiCertPath
                              : !codefDerFileB64 || !codefKeyFileB64))
                      }
                    >
                      {testing === "codef-connect" ? (
                        <RefreshCw className="h-3 w-3 animate-spin mr-1" />
                      ) : null}
                      연결 요청
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={resetCodefForm}
                    >
                      취소
                    </Button>
                  </div>
                </div>
              )}

              {codefError && (
                <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm space-y-2">
                  <div className="flex items-start gap-2 text-red-400">
                    <XCircle className="h-4 w-4 shrink-0 mt-0.5" />
                    <span className="break-all">{codefError}</span>
                  </div>
                  {codefErrorDetail && (
                    <div className="pl-6 space-y-1.5 text-xs">
                      {codefErrorDetail.code && (
                        <div className="flex items-center gap-2">
                          <span className="text-muted-foreground w-24 shrink-0">코드</span>
                          <span className="font-mono text-red-300">{codefErrorDetail.code}</span>
                        </div>
                      )}
                      {codefErrorDetail.transaction_id && (
                        <div className="flex items-center gap-2">
                          <span className="text-muted-foreground w-24 shrink-0">transactionId</span>
                          <span className="font-mono text-amber-300 break-all">
                            {codefErrorDetail.transaction_id}
                          </span>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-6 px-2 text-[10px]"
                            onClick={() =>
                              copyToClipboard(
                                codefErrorDetail.transaction_id!,
                                "transactionId",
                              )
                            }
                          >
                            <Copy className="h-3 w-3 mr-1" />
                            복사
                          </Button>
                        </div>
                      )}
                      {codefErrorDetail.endpoint && (
                        <div className="flex items-center gap-2">
                          <span className="text-muted-foreground w-24 shrink-0">endpoint</span>
                          <span className="font-mono text-muted-foreground break-all">
                            {codefErrorDetail.endpoint}
                          </span>
                        </div>
                      )}
                      {codefErrorDetail.extra_message && (
                        <div className="flex items-start gap-2">
                          <span className="text-muted-foreground w-24 shrink-0">extraMessage</span>
                          <span className="text-muted-foreground break-all">
                            {codefErrorDetail.extra_message}
                          </span>
                        </div>
                      )}
                      <div className="pt-1 text-[11px] text-muted-foreground/80">
                        위 transactionId를 Codef 기술 문의에 전달하세요.
                      </div>
                    </div>
                  )}
                </div>
              )}

              {codefSyncResult && (
                <div className="text-sm text-green-500 rounded-md border border-green-500/30 bg-green-500/5 p-2">
                  <CheckCircle2 className="inline h-4 w-4 mr-1" />
                  {codefSyncResult}
                </div>
              )}

              {/* 자동 sync 스케줄러 상태 */}
              <div className="rounded-md border border-white/[0.05] p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <RefreshCw className="h-4 w-4 text-blue-400" />
                    자동 sync 스케줄러
                    {schedulerStatus?.running ? (
                      <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] text-emerald-300 ring-1 ring-emerald-500/30">
                        running
                      </span>
                    ) : (
                      <span className="rounded-full bg-white/[0.08] px-2 py-0.5 text-[10px] text-muted-foreground">
                        stopped
                      </span>
                    )}
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={runSchedulerNow}
                    disabled={schedulerRunning || !schedulerStatus?.running}
                    className="h-7 text-xs"
                  >
                    <RefreshCw
                      className={`h-3 w-3 mr-1 ${schedulerRunning ? "animate-spin" : ""}`}
                    />
                    지금 실행
                  </Button>
                </div>
                {schedulerStatus && (
                  <div className="text-xs text-muted-foreground space-y-1">
                    <div>
                      주기 <span className="text-foreground">{schedulerStatus.interval_min}분</span>
                      {schedulerStatus.jobs?.[0]?.next_run_time && (
                        <>
                          {" · 다음 실행 "}
                          <span className="text-foreground">
                            {new Date(schedulerStatus.jobs[0].next_run_time).toLocaleString("ko-KR")}
                          </span>
                        </>
                      )}
                    </div>
                    <div className="text-[11px] text-muted-foreground/70">
                      안전장치: 최초 sync를 수동으로 실행한 org만 자동 sync 대상 (신규 연결 즉시 대량 INSERT 방지)
                    </div>
                    {schedulerStatus.last_run?.started_at && (
                      <div className="pt-1 border-t border-white/[0.03] space-y-0.5">
                        <div>
                          마지막 실행{" "}
                          <span className="text-foreground">
                            {new Date(schedulerStatus.last_run.started_at).toLocaleString("ko-KR")}
                          </span>
                          {" — ok "}
                          <span className="text-emerald-300">{schedulerStatus.last_run.ok_count}</span>
                          {" / err "}
                          <span className="text-red-300">{schedulerStatus.last_run.error_count}</span>
                        </div>
                        {schedulerStatus.last_run.results.map((r, i) => {
                          const d = r.detail as Record<string, unknown> | string | undefined
                          const isObj = d && typeof d === "object"
                          const synced = isObj ? (d as Record<string, unknown>).synced : undefined
                          const duplicates = isObj ? (d as Record<string, unknown>).duplicates : undefined
                          const totalFetched = isObj ? (d as Record<string, unknown>).total_fetched : undefined
                          const txId = isObj ? (d as Record<string, unknown>).transaction_id : undefined
                          return (
                          <div key={i} className="pl-2 text-[11px]">
                            <span className={r.ok ? "text-emerald-300" : "text-red-300"}>
                              {r.ok ? "✓" : "✗"}
                            </span>{" "}
                            entity={r.entity_id} {r.org}
                            {r.range && <span className="text-muted-foreground/70"> · {r.range}</span>}
                            {synced !== undefined && (
                              <span className="text-muted-foreground/70">
                                {` · synced ${synced} / dup ${duplicates}`}
                                {totalFetched !== undefined && ` / fetched ${totalFetched}`}
                              </span>
                            )}
                            {txId !== undefined && txId !== null && (
                              <span className="text-amber-300/80">{` · tx=${String(txId)}`}</span>
                            )}
                            {typeof d === "string" && (
                              <span className="text-muted-foreground/70"> · {d}</span>
                            )}
                          </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* 최근 Codef 오류 로그 — 기술 문의용 transactionId 보존 */}
              <div className="rounded-md border border-white/[0.05] p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <AlertCircle className="h-4 w-4 text-amber-400" />
                    Codef 오류 로그 (최근 20건)
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={loadCodefErrorLog}
                    disabled={codefErrorLogLoading}
                    className="h-7 text-xs"
                  >
                    <RefreshCw
                      className={`h-3 w-3 mr-1 ${codefErrorLogLoading ? "animate-spin" : ""}`}
                    />
                    새로고침
                  </Button>
                </div>
                {codefErrorLog.length === 0 ? (
                  <div className="text-xs text-muted-foreground py-2">
                    기록된 오류가 없습니다.
                  </div>
                ) : (
                  <div className="max-h-[320px] overflow-y-auto divide-y divide-white/[0.05]">
                    {codefErrorLog.map((log) => (
                      <div key={log.id} className="py-2 text-xs space-y-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          {log.result_code && (
                            <span className="font-mono text-red-300">{log.result_code}</span>
                          )}
                          {log.organization && (
                            <span className="rounded bg-white/[0.05] px-1.5 py-0.5 text-muted-foreground">
                              {log.organization}
                            </span>
                          )}
                          {log.created_at && (
                            <span className="text-muted-foreground/70">
                              {new Date(log.created_at).toLocaleString("ko-KR")}
                            </span>
                          )}
                          {log.entity_id !== null && (
                            <span className="text-muted-foreground/70">
                              entity={log.entity_id}
                            </span>
                          )}
                        </div>
                        {log.message && (
                          <div className="text-muted-foreground break-all">{log.message}</div>
                        )}
                        {log.transaction_id && (
                          <div className="flex items-center gap-2">
                            <span className="text-muted-foreground shrink-0">transactionId</span>
                            <span className="font-mono text-amber-300 break-all">
                              {log.transaction_id}
                            </span>
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-6 px-2 text-[10px]"
                              onClick={() =>
                                copyToClipboard(log.transaction_id!, "transactionId")
                              }
                            >
                              <Copy className="h-3 w-3 mr-1" />
                              복사
                            </Button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* QuickBooks Online */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Link className="h-5 w-5" />
            QuickBooks Online (HOI)
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            HOI Inc.의 US GAAP 계정 매핑을 QuickBooks에서 가져옵니다.
            Read-only 연동으로 매핑 규칙을 자동 학습합니다.
          </p>

          {!qboStatus?.connected ? (
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={connectQBO}
                disabled={testing === "qbo-connect"}
              >
                {testing === "qbo-connect" ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  "QBO 연결"
                )}
              </Button>
              <Button
                variant="ghost"
                onClick={testQBO}
                disabled={testing === "qbo"}
              >
                {testing === "qbo" ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  "상태 확인"
                )}
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              <StatusBadge status={qboStatus} />
              {qboStatus.last_sync && (
                <p className="text-xs text-muted-foreground">
                  마지막 동기화: {new Date(qboStatus.last_sync).toLocaleString("ko-KR")}
                </p>
              )}
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={syncQBO}
                  disabled={testing === "qbo-sync"}
                >
                  {testing === "qbo-sync" ? (
                    <RefreshCw className="h-4 w-4 animate-spin mr-1" />
                  ) : null}
                  동기화
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={seedQBORules}
                  disabled={testing === "qbo-seed"}
                >
                  {testing === "qbo-seed" ? (
                    <RefreshCw className="h-4 w-4 animate-spin mr-1" />
                  ) : null}
                  매핑 규칙 생성
                </Button>
              </div>
            </div>
          )}

          {qboStatus && !qboStatus.connected && (
            <StatusBadge status={qboStatus} />
          )}

          {qboSyncResult && (
            <div className="text-sm text-muted-foreground space-y-1">
              <p>계정: {qboSyncResult.accounts?.synced ?? 0}개 동기화</p>
              <p>거래: {qboSyncResult.transactions?.synced ?? 0}건 동기화 (총 {qboSyncResult.transactions?.total_fetched ?? 0}건)</p>
            </div>
          )}

          {qboSeedResult && (
            <div className="text-sm space-y-1">
              <p className="text-green-500">매핑 규칙 {qboSeedResult.seeded}개 생성</p>
              {qboSeedResult.skipped > 0 && (
                <p className="text-muted-foreground">{qboSeedResult.skipped}개 스킵</p>
              )}
              {qboSeedResult.unmapped.length > 0 && (
                <p className="text-yellow-500">{qboSeedResult.unmapped.length}개 매핑 불가</p>
              )}
              {qboSeedResult.validation.match_rate < 70 && (
                <p className="text-yellow-500">
                  gaap_mapping 매칭률 {qboSeedResult.validation.match_rate}% — 추가 매핑 필요
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Gowid (법인카드 차선책) */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Wifi className="h-5 w-5" />
            Gowid 법인카드 (차선책)
            {gowidStatus?.connected && (
              <span className="text-xs rounded px-2 py-0.5 ml-2 bg-emerald-500/20 text-emerald-400">
                connected
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Codef 롯데카드 직접 연결이 차단된 동안 우회 경로. 고위드 OpenAPI로 법인카드 거래(롯데/우리/신한 등) 통합 sync.
            Codef 정상화되면 끊을 수 있음.
          </p>

          {/* 법인 선택 */}
          <div className="flex gap-2 items-center">
            <label className="text-xs text-muted-foreground">법인</label>
            <div className="flex rounded-md overflow-hidden border border-border">
              {[
                { id: 2, name: "한아원코리아" },
                { id: 3, name: "한아원리테일" },
              ].map((e) => (
                <button
                  key={e.id}
                  onClick={() => setGowidEntityId(e.id)}
                  className={`px-3 py-1 text-xs transition-colors ${
                    gowidEntityId === e.id
                      ? "bg-accent/20 text-accent"
                      : "bg-transparent text-muted-foreground hover:bg-secondary/50"
                  }`}
                >
                  {e.name}
                </button>
              ))}
            </div>
            {gowidStatus?.key_source && (
              <span className="text-xs text-muted-foreground/70">
                key: {gowidStatus.key_source === "settings" ? "법인 등록" : "환경변수 (전역)"}
              </span>
            )}
          </div>

          {!gowidStatus?.configured && (
            <div className="space-y-2 rounded-md border border-yellow-500/30 bg-yellow-500/5 p-3">
              <p className="text-xs text-yellow-500">
                {gowidEntityId === 2 ? "한아원코리아" : "한아원리테일"} Gowid API key 미등록
              </p>
              <Input
                type="password"
                placeholder="Gowid API key 입력"
                value={gowidApiKeyInput}
                onChange={(e) => setGowidApiKeyInput(e.target.value)}
                className="h-8 text-sm font-mono"
              />
              <Button
                variant="default"
                size="sm"
                onClick={saveGowidApiKey}
                disabled={testing === "gowid-key-save" || !gowidApiKeyInput.trim()}
              >
                {testing === "gowid-key-save" ? (
                  <RefreshCw className="h-3 w-3 animate-spin mr-1" />
                ) : null}
                연결
              </Button>
            </div>
          )}

          {gowidStatus?.configured && (
            <>
              <div className="grid grid-cols-2 gap-3 text-xs text-muted-foreground">
                <div>
                  <span className="text-muted-foreground/70">동기화된 거래</span>
                  <p className="font-mono text-sm text-foreground tabular-nums">
                    {gowidStatus.synced_count ?? 0}건
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground/70">마지막 동기화</span>
                  <p className="text-sm text-foreground">
                    {gowidStatus.last_sync
                      ? new Date(gowidStatus.last_sync).toLocaleString("ko-KR")
                      : "—"}
                  </p>
                </div>
              </div>
              <div className="flex gap-2 items-center flex-wrap">
                <Input
                  value={gowidStart}
                  onChange={(e) => setGowidStart(e.target.value)}
                  className="w-32 h-8 text-xs font-mono"
                  placeholder="2026-04-01"
                />
                <span className="text-xs text-muted-foreground">~</span>
                <Input
                  value={gowidEnd}
                  onChange={(e) => setGowidEnd(e.target.value)}
                  className="w-32 h-8 text-xs font-mono"
                  placeholder="2026-04-20"
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={syncGowid}
                  disabled={testing === "gowid-sync"}
                >
                  {testing === "gowid-sync" ? (
                    <RefreshCw className="h-4 w-4 animate-spin mr-1" />
                  ) : null}
                  동기화
                </Button>
                {gowidStatus.key_source === "settings" && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={deleteGowidApiKey}
                    disabled={testing === "gowid-key-delete"}
                  >
                    연결 해제
                  </Button>
                )}
              </div>
              {gowidError && (
                <div className="text-sm text-red-500">
                  <XCircle className="inline h-4 w-4 mr-1" />
                  {gowidError}
                </div>
              )}
              {gowidSyncResult && (
                <div className="text-sm space-y-1 rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3">
                  <p className="text-foreground">
                    신규 <span className="text-green-400">{gowidSyncResult.synced}</span>건,
                    자동매핑 <span className="text-green-400">{gowidSyncResult.auto_mapped}</span>건,
                    중복 <span className="text-muted-foreground">{gowidSyncResult.duplicates}</span>건
                  </p>
                  {Object.entries(gowidSyncResult.by_issuer || {}).length > 0 && (
                    <p className="text-xs text-muted-foreground">
                      카드사별: {Object.entries(gowidSyncResult.by_issuer).map(([k, v]) => `${k} ${v}`).join(" · ")}
                    </p>
                  )}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* ExpenseOne */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Receipt className="h-5 w-5" />
            ExpenseOne (한아원코리아)
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            ExpenseOne 앱에서 승인된 경비를 FinanceOne 거래내역으로 자동 가져옵니다.
            제출자·제목·카테고리 컨텍스트가 함께 저장되어 매핑 정확도가 올라갑니다.
          </p>

          {expenseoneStatus && (
            <div className="space-y-3">
              <StatusBadge
                status={{
                  connected: expenseoneStatus.connected,
                  error: expenseoneStatus.error ?? undefined,
                }}
              />

              <div className="grid grid-cols-2 gap-3 text-xs text-muted-foreground">
                <div>
                  <span className="text-muted-foreground/70">동기화된 거래</span>
                  <p className="font-mono text-sm text-foreground tabular-nums">
                    {expenseoneStatus.synced_count ?? 0}건
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground/70">마지막 동기화</span>
                  <p className="text-sm text-foreground">
                    {expenseoneStatus.last_sync
                      ? new Date(expenseoneStatus.last_sync).toLocaleString("ko-KR")
                      : "—"}
                  </p>
                </div>
              </div>

              <Button
                variant="outline"
                size="sm"
                onClick={syncExpenseOne}
                disabled={testing === "expenseone-sync" || !expenseoneStatus.connected}
              >
                {testing === "expenseone-sync" ? (
                  <RefreshCw className="h-4 w-4 animate-spin mr-1" />
                ) : null}
                승인 경비 동기화
              </Button>
            </div>
          )}

          {expenseoneError && (
            <div className="text-sm text-red-500">
              <XCircle className="inline h-4 w-4 mr-1" />
              {expenseoneError}
            </div>
          )}

          {expenseoneSyncResult && (
            <div className="text-sm space-y-1 rounded-md border border-border bg-secondary/30 p-3">
              <p className="text-foreground">
                총 {expenseoneSyncResult.total_fetched}건 조회 — 신규{" "}
                <span className="text-green-500">{expenseoneSyncResult.inserted}</span>건,
                기존 보강{" "}
                <span className="text-blue-400">{expenseoneSyncResult.enriched}</span>건,
                중복{" "}
                <span className="text-muted-foreground">{expenseoneSyncResult.duplicates}</span>건
              </p>
              {expenseoneSyncResult.unmapped > 0 && (
                <p className="text-yellow-500">
                  미매핑 {expenseoneSyncResult.unmapped}건 — 거래내역에서 수동 매핑 필요
                </p>
              )}
              {expenseoneSyncResult.errors.length > 0 && (
                <p className="text-red-500">
                  에러 {expenseoneSyncResult.errors.length}건 — 로그 확인 필요
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function StatusBadge({ status }: { status: ConnectionStatus }) {
  if (status.connected) {
    return (
      <div className="flex items-center gap-2 text-sm text-green-500">
        <CheckCircle2 className="h-4 w-4" />
        <span>연결됨</span>
        {status.accounts !== undefined && (
          <span className="text-muted-foreground">
            ({status.accounts}개 계좌)
          </span>
        )}
        {status.environment && (
          <span className="text-muted-foreground">
            [{status.environment}]
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2 text-sm text-red-500">
      <XCircle className="h-4 w-4" />
      <span>연결 실패</span>
      {status.error && (
        <span className="text-muted-foreground">— {status.error}</span>
      )}
    </div>
  )
}

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <Suspense fallback={<Skeleton className="h-10 w-full border-b" />}>
        <EntityTabs />
      </Suspense>

      <div className="flex items-center gap-2">
        <Settings className="h-6 w-6 text-muted-foreground" />
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">설정</h1>
      </div>

      <Suspense fallback={<Skeleton className="h-40 w-full" />}>
        <SettingsContent />
      </Suspense>
    </div>
  )
}
