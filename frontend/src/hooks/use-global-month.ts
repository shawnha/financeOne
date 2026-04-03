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
  const [month, setMonthState] = useState<string>(currentMonth)
  const [ready, setReady] = useState(false)
  const initialized = useRef(false)

  // 클라이언트 마운트 시 localStorage에서 읽어서 보정 (hydration 안전)
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
