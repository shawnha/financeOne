"use client"

import { useState, useCallback, useEffect, useRef } from "react"

const STORAGE_KEY = "financeone-selected-month"

function currentMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
}

/**
 * 글로벌 월 선택 상태. localStorage에 저장되어 페이지 간 공유.
 * SSR: 현재 월로 초기화 → 마운트 후 localStorage 복원.
 * ready=false 동안 소비자가 fetch를 막을 수 있도록 ready 플래그 제공.
 */
export function useGlobalMonth() {
  const [month, setMonthState] = useState<string>(() => {
    // SSR 안전: window 존재 시 localStorage에서 즉시 읽기
    if (typeof window !== "undefined") {
      return localStorage.getItem(STORAGE_KEY) || currentMonth()
    }
    return currentMonth()
  })
  const [ready, setReady] = useState(() => typeof window !== "undefined")
  const initialized = useRef(typeof window !== "undefined")

  // SSR fallback: 서버에서 렌더된 경우 마운트 시 복원
  useEffect(() => {
    if (initialized.current) return
    initialized.current = true
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      setMonthState(saved)
    }
    setReady(true)
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
