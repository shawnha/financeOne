const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api"

export class APIError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
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
    throw new APIError(res.status, body.detail || res.statusText)
  }

  return res.json()
}
