"use client"

import { useState, useEffect, Suspense } from "react"
import { fetchAPI } from "@/lib/api"
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
  const [codefStatus, setCodefStatus] = useState<ConnectionStatus | null>(null)
  const [qboStatus, setQboStatus] = useState<ConnectionStatus | null>(null)
  const [qboSyncResult, setQboSyncResult] = useState<QBOSyncResult | null>(null)
  const [qboSeedResult, setQboSeedResult] = useState<QBOSeedResult | null>(null)
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

  const testCodef = async () => {
    setTesting("codef")
    try {
      const status = await fetchAPI<ConnectionStatus>("/integrations/codef/status")
      setCodefStatus(status)
    } catch (err) {
      setCodefStatus({ connected: false, error: err instanceof Error ? err.message : "Connection failed" })
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
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            우리은행, 롯데카드, 우리카드 거래를 Codef.io를 통해 자동으로 가져옵니다.
            현재 샌드박스 환경입니다.
          </p>
          <Button
            variant="outline"
            onClick={testCodef}
            disabled={testing === "codef"}
          >
            {testing === "codef" ? (
              <RefreshCw className="h-4 w-4 animate-spin" />
            ) : (
              "연결 테스트"
            )}
          </Button>
          {codefStatus && (
            <StatusBadge status={codefStatus} />
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
