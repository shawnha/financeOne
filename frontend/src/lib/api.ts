const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api"

export class APIError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message)
  }
}

function extractMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail
  if (detail && typeof detail === "object" && "message" in detail) {
    const m = (detail as { message: unknown }).message
    if (typeof m === "string") return m
  }
  return fallback
}

export async function fetchAPI<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  })

  if (!res.ok) {
    const body = await res
      .json()
      .catch(() => ({ detail: res.statusText }))
    const detail = body?.detail
    throw new APIError(res.status, extractMessage(detail, res.statusText), detail)
  }

  return res.json()
}
