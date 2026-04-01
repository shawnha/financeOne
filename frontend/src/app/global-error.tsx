"use client"

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <html>
      <body>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100vh", gap: "16px" }}>
          <h2>오류가 발생했습니다</h2>
          <p>{error.message}</p>
          <button onClick={reset}>다시 시도</button>
        </div>
      </body>
    </html>
  )
}
