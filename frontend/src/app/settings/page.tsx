"use client"

import { useState, Suspense } from "react"
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
} from "lucide-react"

interface ConnectionStatus {
  connected: boolean
  error?: string
  accounts?: number
  account_names?: string[]
  environment?: string
}

function SettingsContent() {
  const [mercuryToken, setMercuryToken] = useState("")
  const [mercuryStatus, setMercuryStatus] = useState<ConnectionStatus | null>(null)
  const [codefStatus, setCodefStatus] = useState<ConnectionStatus | null>(null)
  const [testing, setTesting] = useState<string | null>(null)

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
