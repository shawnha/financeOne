"use client"

import { useState, useCallback, useEffect } from "react"

const STORAGE_KEY = "financeone-selected-month"

function getDefault(): string {
  if (typeof window !== "undefined") {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) return saved
  }
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
}

/**
 * 글로벌 월 선택 상태. localStorage에 저장되어 페이지 간 공유.
 * 다른 탭/페이지에서 변경해도 storage 이벤트로 동기화.
 */
export function useGlobalMonth() {
  const [month, setMonthState] = useState<string>(getDefault)

  const setMonth = useCallback((m: string) => {
    setMonthState(m)
    if (typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, m)
      // 같은 탭의 다른 컴포넌트에도 알림
      window.dispatchEvent(new StorageEvent("storage", { key: STORAGE_KEY, newValue: m }))
    }
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

  return [month, setMonth] as const
}
