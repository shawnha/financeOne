"use client"

// 사장님 경영 코쿼핏 — 그룹/법인별 현금 신호등 + 통화·기준 토글 + 순현금 추세 (v4 mockup 실데이터 포팅)

import { useCallback, useEffect, useMemo, useState } from "react"
import { AlertCircle, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { MonthPicker } from "@/components/month-picker"
import { fetchAPI, APIError } from "@/lib/api"
import { cn } from "@/lib/utils"

// ── 타입 (백엔드 CockpitCeoResponse 대응) ──
type CockpitEntity = {
  id: number
  code: string
  name: string
  currency: string
  income: number | string
  expense: number | string
  net: number | string
  balance: number | string
}
type CockpitData = {
  year_month: string
  display_currency: "USD" | "KRW"
  fx: { usd_krw: number | string; as_of: string }
  entities: CockpitEntity[]
  group: {
    income: number | string
    expense: number | string
    net: number | string
    balance: number | string
    runway_months: number | string | null
    nonop_income: number | string
    nonop_expense: number | string
  }
  trend: { month: string; net: number | string }[]
}

// 법인 표시 메타 (국기·꼬리표) — id 기반
const ENTITY_META: Record<number, { flag: string; tail: string }> = {
  1: { flag: "🇺🇸", tail: "미국·USD" },
  2: { flag: "🇰🇷", tail: "KRW" },
  3: { flag: "🇰🇷", tail: "KRW" },
  13: { flag: "🇰🇷", tail: "KRW·도매" },
}

// ── 포맷 ──
const n = (v: number | string | null | undefined) => Number(v ?? 0)

function fmt(v: number, cur: string): string {
  const r = Math.round(v)
  const s = Math.abs(r).toLocaleString("en-US")
  const sg = r < 0 ? "−" : ""
  return cur === "USD" ? `${sg}$${s}` : `${sg}₩${s}`
}
function fmtK(v: number, cur: string): string {
  const r = Math.round(v)
  const a = Math.abs(r)
  const sg = r < 0 ? "−" : ""
  const sym = cur === "USD" ? "$" : "₩"
  if (a >= 1e9) return `${sg}${sym}${(a / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `${sg}${sym}${(a / 1e6).toFixed(2)}M`
  if (a >= 1e3) return `${sg}${sym}${(a / 1e3).toFixed(0)}K`
  return `${sg}${sym}${a}`
}
// 자국통화 ↔ 표시통화 환산 (배지 usd_krw 단일 환율 사용 — 괄호 보조표시용)
function conv(amt: number, from: string, to: string, usdKrw: number): number {
  if (from === to) return amt
  return from === "KRW" ? amt / usdKrw : amt * usdKrw
}

// 기준별 용어 (현금=수입/지출, 발생=매출/비용)
function term(basis: "cash" | "accr") {
  return basis === "cash"
    ? { inc: "수입", out: "지출", net: "순현금", runway: "현금 런웨이" }
    : { inc: "매출", out: "비용", net: "영업손익", runway: "이익 추세" }
}

function defaultMonth(): string {
  // 직전 완료월 (당월은 데이터 거의 없음)
  const now = new Date()
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
}

export default function CockpitPage() {
  const [yearMonth, setYearMonth] = useState<string>(defaultMonth)
  const [currency, setCurrency] = useState<"USD" | "KRW">("USD")
  const [basis, setBasis] = useState<"cash" | "accr">("cash")
  const [data, setData] = useState<CockpitData | null>(null)
  const [loading, setLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const months = useMemo(() => {
    const now = new Date()
    const arr: string[] = []
    for (let i = 11; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
      arr.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`)
    }
    return arr
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setErrorMessage(null)
    // 백엔드 hang/재시작(서버리스 cold start, dev --reload) 시 무한 스켈레톤 방지 — 15초 타임아웃 → ERROR 상태
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 15000)
    try {
      const d = await fetchAPI<CockpitData>(
        `/cockpit/ceo?currency=${currency}&year_month=${yearMonth}`,
        { signal: controller.signal },
      )
      setData(d)
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        setErrorMessage("서버 응답이 지연됩니다. 잠시 후 다시 시도해주세요.")
      } else {
        setErrorMessage(
          e instanceof APIError ? e.message : "코쿼핏 데이터를 불러오지 못했습니다.",
        )
      }
    } finally {
      clearTimeout(timer)
      setLoading(false)
    }
  }, [currency, yearMonth])

  useEffect(() => {
    load()
  }, [load])

  // ── ERROR ──
  if (errorMessage && !data) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-semibold tracking-tight mb-6">👔 사장님 코쿼핏</h1>
        <Card className="p-8 flex flex-col items-center justify-center text-center gap-4">
          <AlertCircle className="h-12 w-12 text-[hsl(var(--loss))]" aria-hidden />
          <p className="text-lg font-medium">데이터를 불러올 수 없습니다.</p>
          <p className="text-sm text-muted-foreground">{errorMessage}</p>
          <Button onClick={load} variant="secondary" className="gap-2">
            <RefreshCw className="h-4 w-4" aria-hidden />
            다시 시도
          </Button>
        </Card>
      </div>
    )
  }

  // ── LOADING (최초) ──
  if (loading && !data) {
    return (
      <div className="p-4 lg:p-6 space-y-3">
        <Skeleton className="h-8 w-48 mb-2" />
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-[1.45fr_1fr] gap-4">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      </div>
    )
  }

  if (!data) return null

  const T = term(basis)
  const usdKrw = n(data.fx.usd_krw)
  const asOfMonth = data.fx.as_of.slice(5, 7).replace(/^0/, "")
  const gInc = n(data.group.income)
  const gExp = n(data.group.expense)
  const gNet = n(data.group.net)
  const gBal = n(data.group.balance)
  const runway = data.group.runway_months != null ? n(data.group.runway_months) : null
  const nopIn = n(data.group.nonop_income)   // 제외한 비영업 유입 (display 통화)
  const nopOut = n(data.group.nonop_expense) // 제외한 비영업 유출
  const hasNonOp = nopIn !== 0 || nopOut !== 0

  // 최대 출혈 법인
  const worst = [...data.entities]
    .map((e) => ({ e, netUSD: conv(n(e.net), e.currency, "USD", usdKrw) }))
    .filter((o) => o.netUSD < 0)
    .sort((a, b) => a.netUSD - b.netUSD)[0]

  // EMPTY: 선택월 입출금이 0 (잔고는 월 독립 최신값이라 판정에서 제외)
  const isEmpty = gInc === 0 && gExp === 0

  return (
    <div className="p-4 lg:p-6 space-y-4">
      {/* 헤더 + 컨트롤 */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            👔 사장님 코쿼핏
          </h1>
          <p className="text-xs text-muted-foreground mt-1">
            한아원 4법인 · 법인 행은 자국통화 기본(괄호 환산) · 현금기준 <b className="text-foreground/80">영업 현금흐름</b>
            (차입·대여 등 비영업 제외 · 회계상 비용·매출과는 다름)
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <MonthPicker months={months} selected={yearMonth} onSelect={setYearMonth} />
          <Segmented
            value={basis}
            onChange={(v) => setBasis(v as "cash" | "accr")}
            options={[
              { value: "cash", label: "💵 현금기준" },
              { value: "accr", label: "📒 발생기준" },
            ]}
          />
          <Segmented
            value={currency}
            onChange={(v) => setCurrency(v as "USD" | "KRW")}
            options={[
              { value: "USD", label: "$ USD" },
              { value: "KRW", label: "₩ KRW" },
            ]}
          />
          <span className="text-[11px] text-muted-foreground bg-card border border-border rounded-md px-2.5 py-1.5">
            환율{" "}
            <b className="text-foreground">
              1 USD = ₩{usdKrw.toLocaleString("en-US", { minimumFractionDigits: 2 })}
            </b>{" "}
            <span className="text-muted-foreground/60">({asOfMonth}월말 기준)</span>
          </span>
        </div>
      </div>

      {/* EMPTY: 데이터 없는 달 안내 */}
      {isEmpty && (
        <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
          {yearMonth.slice(5)}월에는 입출금 데이터가 없습니다 (통장잔고만 표시). 다른 달을
          선택하거나 거래내역을 업로드해보세요.
        </div>
      )}

      {/* 발생기준 disclaimer (v1: 데이터 미연동) */}
      {basis === "accr" && (
        <div className="rounded-lg border border-[hsl(var(--accent))]/30 bg-[hsl(var(--accent))]/10 px-4 py-3 text-sm">
          <b className="text-foreground">발생기준 데이터 연동 준비 중입니다.</b>{" "}
          <span className="text-muted-foreground">
            현재 표시되는 숫자는 모두 현금기준(통장 입출금)이며, 용어만 매출/비용으로
            바뀌어 있습니다. 결산자료·원장 연동이 완료되면 실제 발생 매출·비용으로
            전환됩니다.
          </span>
        </div>
      )}

      {/* KPI 카드 */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        <KpiCard label="그룹 총잔고" value={fmt(gBal, currency)} sub="4법인 통장 합산 · 현재" />
        <KpiCard
          label={`그룹 ${T.inc}`}
          value={fmt(gInc, currency)}
          valueClass="text-[hsl(var(--profit))]"
          sub={basis === "cash" ? `${yearMonth.slice(5)}월 · 영업 유입` : `${yearMonth.slice(5)}월`}
        />
        <KpiCard
          label={`그룹 ${T.out}`}
          value={fmt(gExp, currency)}
          valueClass="text-[hsl(var(--loss))]"
          sub={basis === "cash" ? `${yearMonth.slice(5)}월 · 영업 출금` : `${yearMonth.slice(5)}월`}
        />
        <KpiCard
          label={`그룹 ${T.net}`}
          value={fmt(gNet, currency)}
          valueClass={gNet < 0 ? "text-[hsl(var(--loss))]" : "text-[hsl(var(--profit))]"}
          sub={gNet < 0 ? "매월 빠지는 중" : "흑자"}
          subClass={gNet < 0 ? "text-[hsl(var(--loss))]" : "text-[hsl(var(--profit))]"}
        />
        {/* 런웨이는 항상 현금 지표 — 발생토글에서도 라벨 고정. runway=null 사유 분기(흑자 vs 잔고소진) */}
        <KpiCard
          label="현금 런웨이"
          value={runway != null ? `~${runway.toFixed(1)}개월` : gNet < 0 ? "잔고 소진" : "흑자"}
          valueClass={
            runway != null
              ? "text-amber-400"
              : gNet < 0
                ? "text-[hsl(var(--loss))]"
                : "text-[hsl(var(--profit))]"
          }
          sub={runway != null ? `${yearMonth.slice(5)}월 소진율 기준` : gNet < 0 ? "잔고 0 · 적자" : "현금 순증"}
          subClass={runway != null ? "text-amber-400/80" : undefined}
        />
      </div>

      {/* 투명표기: 영업기준에서 제외한 비영업(재무·투자) 현금흐름 + 검토예정 안내 */}
      <div className="rounded-lg border border-border bg-card/60 px-4 py-2.5 text-[11.5px] text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1">
        <span>💡 <b className="text-foreground/80">영업 현금흐름만</b> 표시.</span>
        {hasNonOp ? (
          <span>
            제외한 비영업(차입·대여·가지급·증자): 유입{" "}
            <b className="text-foreground/80">{fmt(nopIn, currency)}</b> · 유출{" "}
            <b className="text-foreground/80">{fmt(nopOut, currency)}</b>.
          </span>
        ) : (
          <span>이 달엔 제외할 비영업 항목이 없습니다.</span>
        )}
        <span className="text-muted-foreground/60">
          ※ 미매핑·외상매출입금(운전자본)·법인간 운영거래·일부 방향오분류는 아직 영업에 포함 — 정밀 분류는 검토 예정.
        </span>
      </div>

      {/* 시급 액션 배너 */}
      <div
        className={cn(
          "rounded-lg border-l-[3px] bg-card px-4 py-3 text-sm",
          gNet < 0 ? "border-[hsl(var(--loss))]" : "border-[hsl(var(--profit))]",
        )}
      >
        {gNet < 0 ? (
          <>
            🔴 <b className="text-foreground">가장 시급</b> ({yearMonth.slice(5)}월·
            {basis === "cash" ? "현금" : "발생"}): 그룹 {T.net}{" "}
            <b className="text-[hsl(var(--loss))]">{fmt(gNet, currency)}</b>
            {runway != null && (
              <>
                , 런웨이 <b className="text-amber-400">~{runway.toFixed(1)}개월</b>
              </>
            )}
            {worst && (
              <>
                . 최대 출혈{" "}
                <b className="text-foreground">
                  {worst.e.name}{" "}
                  {fmt(conv(n(worst.e.net), worst.e.currency, currency, usdKrw), currency)}
                </b>{" "}
                <span className="text-muted-foreground">({yearMonth.slice(5)}월 순현금)</span>
              </>
            )}
            .
          </>
        ) : (
          <>🟢 {yearMonth.slice(5)}월 그룹 {T.net} 흑자.</>
        )}
      </div>

      {/* 본문: 법인 신호등 표 + 추세 차트 */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.45fr_1fr] gap-4 items-start">
        <EntityTable data={data} currency={currency} usdKrw={usdKrw} term={T} basis={basis} />
        <TrendChart data={data} currency={currency} selected={yearMonth} term={T} />
      </div>
    </div>
  )
}

// ── 세그먼트 토글 ──
function Segmented({
  value,
  onChange,
  options,
}: {
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
}) {
  return (
    <div className="inline-flex bg-card border border-border rounded-lg p-0.5 gap-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "px-3 py-1.5 rounded-md text-xs font-semibold transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            value === o.value
              ? "bg-[hsl(var(--color-cta))] text-white"
              : "text-muted-foreground hover:text-foreground",
          )}
          aria-pressed={value === o.value}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

// ── KPI 카드 ──
function KpiCard({
  label,
  value,
  sub,
  valueClass,
  subClass,
}: {
  label: string
  value: string
  sub?: string
  valueClass?: string
  subClass?: string
}) {
  return (
    <Card className="p-3.5">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn("text-xl font-bold mt-1.5 tabular-nums", valueClass)}>{value}</div>
      {sub && (
        <div className={cn("text-[11px] mt-1 text-muted-foreground", subClass)}>{sub}</div>
      )}
    </Card>
  )
}

// ── 법인별 신호등 표 ──
function EntityTable({
  data,
  currency,
  usdKrw,
  term,
  basis,
}: {
  data: CockpitData
  currency: "USD" | "KRW"
  usdKrw: number
  term: ReturnType<typeof termType>
  basis: "cash" | "accr"
}) {
  const other = (c: string) => (c === "KRW" ? "USD" : "KRW")
  const cell = (v: number, ecur: string) => {
    const o = other(ecur)
    return (
      <>
        {fmt(v, ecur)}{" "}
        <span className="text-[10.5px] text-muted-foreground/70">
          ({fmt(conv(v, ecur, o, usdKrw), o)})
        </span>
      </>
    )
  }

  const gInc = n(data.group.income)
  const gExp = n(data.group.expense)
  const gNet = n(data.group.net)
  const gBal = n(data.group.balance)

  return (
    <div>
      <h2 className="text-sm font-medium text-[hsl(var(--accent))] mb-3 pb-1.5 border-b border-border">
        법인별 신호등 ({data.year_month.slice(5)}월·{basis === "cash" ? "현금기준" : "발생기준"}) —
        자국통화 기본 (괄호: 환산)
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="text-[10.5px] uppercase text-muted-foreground">
              <th className="text-left font-semibold py-2 px-2.5 border-b border-border">법인</th>
              <th className="text-right font-semibold py-2 px-2.5 border-b border-border">월 {term.inc}</th>
              <th className="text-right font-semibold py-2 px-2.5 border-b border-border">월 {term.out}</th>
              <th className="text-right font-semibold py-2 px-2.5 border-b border-border">월 {term.net}</th>
              <th className="text-right font-semibold py-2 px-2.5 border-b border-border">통장잔고</th>
              <th className="text-left font-semibold py-2 px-2.5 border-b border-border">상태</th>
            </tr>
          </thead>
          <tbody>
            {data.entities.map((e) => {
              const inc = n(e.income)
              const exp = n(e.expense)
              const net = n(e.net)
              const bal = n(e.balance)
              const netUSD = conv(net, e.currency, "USD", usdKrw)
              const meta = ENTITY_META[e.id] ?? { flag: "🏢", tail: e.currency }
              const sig = net >= 0 ? "🟢" : Math.abs(netUSD) > 20000 ? "🔴" : "🟡"
              return (
                <tr key={e.id} className="border-b border-border/50">
                  <td className="py-2.5 px-2.5 font-semibold tabular-nums whitespace-nowrap">
                    <span className="mr-1">{sig}</span>
                    {meta.flag} {e.name.replace(/^주식회사\s*/, "")}{" "}
                    <span className="text-[10.5px] font-normal text-muted-foreground">{meta.tail}</span>
                  </td>
                  <td className="py-2.5 px-2.5 text-right tabular-nums">{cell(inc, e.currency)}</td>
                  <td className="py-2.5 px-2.5 text-right tabular-nums">{cell(exp, e.currency)}</td>
                  <td
                    className={cn(
                      "py-2.5 px-2.5 text-right tabular-nums",
                      net < 0 ? "text-[hsl(var(--loss))]" : "text-[hsl(var(--profit))]",
                    )}
                  >
                    {cell(net, e.currency)}
                  </td>
                  <td className="py-2.5 px-2.5 text-right tabular-nums">{cell(bal, e.currency)}</td>
                  <td className="py-2.5 px-2.5">
                    <StatusPill net={net} netUSD={netUSD} />
                  </td>
                </tr>
              )
            })}
            {/* 그룹 합계 */}
            <tr className="border-t-2 border-border font-semibold">
              <td className="py-2.5 px-2.5">
                그룹 합계 <span className="text-[10.5px] font-normal text-muted-foreground">{currency} 환산</span>
              </td>
              <td className="py-2.5 px-2.5 text-right tabular-nums text-[hsl(var(--profit))]">{fmt(gInc, currency)}</td>
              <td className="py-2.5 px-2.5 text-right tabular-nums text-[hsl(var(--loss))]">{fmt(gExp, currency)}</td>
              <td
                className={cn(
                  "py-2.5 px-2.5 text-right tabular-nums",
                  gNet < 0 ? "text-[hsl(var(--loss))]" : "text-[hsl(var(--profit))]",
                )}
              >
                {fmt(gNet, currency)}
              </td>
              <td className="py-2.5 px-2.5 text-right tabular-nums">{fmt(gBal, currency)}</td>
              <td className="py-2.5 px-2.5">
                {gNet < 0 ? (
                  <span className="text-[10.5px] px-2 py-0.5 rounded-full bg-[hsl(var(--loss))]/15 text-[hsl(var(--loss))] font-semibold">
                    적자
                  </span>
                ) : (
                  <span className="text-[10.5px] px-2 py-0.5 rounded-full bg-[hsl(var(--profit))]/15 text-[hsl(var(--profit))] font-semibold">
                    흑자
                  </span>
                )}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}

// 상태 pill — 가짜 "BEP 근접" 제거, 적자 규모로만 분류 (소액적자/적자/흑자)
function StatusPill({ net, netUSD }: { net: number; netUSD: number }) {
  if (net >= 0)
    return (
      <span className="text-[10.5px] px-2 py-0.5 rounded-full bg-[hsl(var(--profit))]/15 text-[hsl(var(--profit))] font-semibold">
        흑자
      </span>
    )
  if (Math.abs(netUSD) > 20000)
    return (
      <span className="text-[10.5px] px-2 py-0.5 rounded-full bg-[hsl(var(--loss))]/15 text-[hsl(var(--loss))] font-semibold">
        적자
      </span>
    )
  return (
    <span className="text-[10.5px] px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 font-semibold">
      소액적자
    </span>
  )
}

// ── 그룹 순현금 추세 차트 ──
function TrendChart({
  data,
  currency,
  selected,
  term,
}: {
  data: CockpitData
  currency: "USD" | "KRW"
  selected: string
  term: ReturnType<typeof termType>
}) {
  const points = data.trend.map((p) => ({ month: p.month, net: n(p.net) }))
  const avg = points.length ? points.reduce((a, b) => a + b.net, 0) / points.length : 0
  const maxAbs = Math.max(...points.map((p) => Math.abs(p.net)), Math.abs(avg)) * 1.15 || 1
  const H = 180
  const zeroY = H / 2
  const scale = (v: number) => (v / maxAbs) * (H / 2)
  // 윈도우 내 최고 순현금 달 (하드코딩 대신 데이터에서 동적으로 — 흑자 달이 있으면 호명)
  const best = points.length ? points.reduce((a, b) => (b.net > a.net ? b : a)) : null

  return (
    <div>
      <h2 className="text-sm font-medium text-[hsl(var(--accent))] mb-3 pb-1.5 border-b border-border">
        그룹 {term.net} 추세 (3개월) · {currency}
      </h2>
      <Card className="p-4">
        <div
          className="relative flex items-end gap-4 border-b border-border"
          style={{ height: H + 28 }}
        >
          {/* 0 기준선 */}
          <div className="absolute left-0 right-0 border-t border-dashed border-border" style={{ top: zeroY }} />
          {/* 평균선 */}
          <div
            className="absolute left-0 right-0 border-t-2 border-dashed border-amber-400"
            style={{ top: zeroY - scale(avg) }}
          />
          <div
            className="absolute right-0 text-[10.5px] text-amber-400 bg-card px-1"
            style={{ top: zeroY - scale(avg), transform: "translateY(-50%)" }}
          >
            평균 {fmtK(avg, currency)}
          </div>
          {points.map((p) => {
            const h = Math.abs(scale(p.net))
            const up = p.net >= 0
            const top = up ? zeroY - h : zeroY
            const isSel = p.month === selected
            return (
              <div key={p.month} className="flex-1 relative h-full">
                <div
                  className={cn(
                    "absolute text-[11px] font-semibold tabular-nums left-1/2 -translate-x-1/2",
                    up ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]",
                  )}
                  style={{ top: top - 18 }}
                >
                  {fmtK(p.net, currency)}
                </div>
                <div
                  className={cn("absolute left-1/2 -translate-x-1/2 rounded-t w-[55%]", isSel && "ring-2 ring-white/30")}
                  style={{
                    height: h,
                    top,
                    backgroundColor: up ? "hsl(var(--profit))" : "hsl(var(--loss))",
                  }}
                />
                <div
                  className={cn(
                    "absolute left-1/2 -translate-x-1/2 text-[11px]",
                    isSel ? "text-foreground font-bold" : "text-muted-foreground",
                  )}
                  style={{ top: H + 6 }}
                >
                  {p.month.slice(5)}월
                </div>
              </div>
            )
          })}
        </div>
        <div className="flex gap-3.5 text-[11px] text-muted-foreground mt-3.5">
          <span>
            <span className="inline-block w-2.5 h-2.5 rounded-sm mr-1 align-middle" style={{ background: "hsl(var(--profit))" }} />
            흑자 달
          </span>
          <span>
            <span className="inline-block w-2.5 h-2.5 rounded-sm mr-1 align-middle" style={{ background: "hsl(var(--loss))" }} />
            적자 달
          </span>
          <span>
            <span className="inline-block w-2.5 h-2.5 rounded-sm mr-1 align-middle bg-amber-400" />
            3개월 평균선
          </span>
        </div>
        <p className="text-[11.5px] text-muted-foreground mt-2.5 leading-relaxed">
          한 달만 보면 착시가 생깁니다.{" "}
          {best && best.net >= 0 && (
            <>
              이 구간 중 {best.month.slice(5)}월은 흑자(
              <b className="text-[hsl(var(--profit))]">{fmtK(best.net, currency)}</b>)였습니다.{" "}
            </>
          )}
          3개월 <b className="text-amber-400">평균 {fmtK(avg, currency)}</b>
          {avg >= 0 ? "로 평균은 흑자 흐름입니다." : "로 평균도 적자라 구조적 적자 흐름입니다."}
        </p>
        <p className="text-[10.5px] text-muted-foreground/60 mt-1.5">
          ※ 과거 달은 각 월말 환율로 환산했습니다 (해당 월 환율이 없으면 직전 영업일 근사).
        </p>
      </Card>
    </div>
  )
}

// term() 반환 타입 헬퍼 (props 타입용)
function termType() {
  return { inc: "", out: "", net: "", runway: "" }
}
