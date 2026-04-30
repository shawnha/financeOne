"use client"

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import { fetchAPI } from "@/lib/api"
import type {
  Currency,
  DashboardFullResponse,
  Gaap,
  Scope,
} from "@/lib/dashboard-types"

type LoadState = "loading" | "success" | "error"

interface DashboardContextValue {
  // Filters
  scope: Scope
  currency: Currency
  gaap: Gaap
  setScope: (s: Scope) => void
  setCurrency: (c: Currency) => void
  setGaap: (g: Gaap) => void

  // Data
  data: DashboardFullResponse | null
  state: LoadState
  errorMessage: string

  // Actions
  refresh: () => void
}

const DashboardContext = createContext<DashboardContextValue | null>(null)

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [scope, setScope] = useState<Scope>("group")
  const [currency, setCurrency] = useState<Currency>("USD")
  const [gaap, setGaap] = useState<Gaap>("K")

  const [data, setData] = useState<DashboardFullResponse | null>(null)
  const [state, setState] = useState<LoadState>("loading")
  const [errorMessage, setErrorMessage] = useState("")

  const fetchFull = useCallback(async () => {
    setState("loading")
    setErrorMessage("")

    try {
      const params = new URLSearchParams()
      if (scope !== "group") params.set("entity_id", String(scope))
      params.set("currency", currency)
      params.set("gaap", gaap)

      const result = await fetchAPI<DashboardFullResponse>(
        `/dashboard/full?${params.toString()}`,
        { cache: "no-store" },
      )
      setData(result)
      setState("success")
    } catch (err) {
      setErrorMessage(
        err instanceof Error ? err.message : "데이터를 불러올 수 없습니다.",
      )
      setState("error")
    }
  }, [scope, currency, gaap])

  // Initial + filter change
  useEffect(() => {
    fetchFull()
  }, [fetchFull])

  // Tab focus refetch (no polling, per plan-eng-review decision)
  useEffect(() => {
    const onFocus = () => {
      if (document.visibilityState === "visible") fetchFull()
    }
    document.addEventListener("visibilitychange", onFocus)
    return () => document.removeEventListener("visibilitychange", onFocus)
  }, [fetchFull])

  const value = useMemo<DashboardContextValue>(
    () => ({
      scope,
      currency,
      gaap,
      setScope,
      setCurrency,
      setGaap,
      data,
      state,
      errorMessage,
      refresh: fetchFull,
    }),
    [scope, currency, gaap, data, state, errorMessage, fetchFull],
  )

  return (
    <DashboardContext.Provider value={value}>
      {children}
    </DashboardContext.Provider>
  )
}

export function useDashboard() {
  const ctx = useContext(DashboardContext)
  if (!ctx) {
    throw new Error("useDashboard must be used within <DashboardProvider>")
  }
  return ctx
}
