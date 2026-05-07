"use client"

import { useState, useCallback, useEffect } from "react"

const STORAGE_KEY = "financeone-selected-month"

function currentMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
}

/**
 * 글로벌 월 선택 상태. localStorage 에 저장되어 페이지 간 공유.
 *
 * Hydration safety: SSR 과 CSR 의 initial state 가 항상 `currentMonth()` 로
 * 동일해야 함. 이전 구현은 useState initializer 에서 `typeof window` 분기로
 * localStorage 를 즉시 읽어 SSR("2026-05") vs CSR(localStorage="2026-04")
 * mismatch 가 발생함. 마운트 후 useEffect 에서만 localStorage 복원.
 *
 * ready=false 동안 소비자가 fetch 를 막을 수 있도록 ready 플래그 제공.
 */
export function useGlobalMonth() {
  const [month, setMonthState] = useState<string>(currentMonth)
  const [ready, setReady] = useState(false)

  // 마운트 후 localStorage 복원 (CSR 전용)
  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && saved !== month) {
      setMonthState(saved)
    }
    setReady(true)
    // month 비교는 mount 시점 기준만 — deps 비움
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const setMonth = useCallback((m: string) => {
    setMonthState(m)
    localStorage.setItem(STORAGE_KEY, m)
    window.dispatchEvent(new StorageEvent("storage", { key: STORAGE_KEY, newValue: m }))
  }, [])

  // 다른 컴포넌트에서 변경 시 동기화
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY && e.newValue) {
        setMonthState(e.newValue)
      }
    }
    window.addEventListener("storage", handler)
    return () => window.removeEventListener("storage", handler)
  }, [])

  return [month, setMonth, ready] as const
}
