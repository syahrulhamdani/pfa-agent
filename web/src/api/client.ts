// All requests go through /api, which the Vite dev server proxies to FastAPI.
export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') {
        detail = body.detail
      } else if (Array.isArray(body.detail)) {
        // FastAPI's raw validation shape: a list of { msg } entries.
        const messages = body.detail
          .map((entry: { msg?: string }) => entry.msg)
          .filter(Boolean)
        if (messages.length > 0) detail = messages.join('; ')
      }
    } catch {
      // Keep the status text when the body is not JSON.
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}
