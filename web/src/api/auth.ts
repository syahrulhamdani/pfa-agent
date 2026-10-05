import { api } from './client'

// React StrictMode runs effects twice in development. A login link works only once,
// so every caller with the same token must share one request.
const inflight = new Map<string, Promise<void>>()

export function exchangeToken(token: string): Promise<void> {
  let request = inflight.get(token)
  if (!request) {
    request = api<unknown>('/auth/exchange', {
      method: 'POST',
      body: JSON.stringify({ token }),
    }).then(() => undefined)
    inflight.set(token, request)
  }
  return request
}

// Only follow redirects to pages inside this app, never to another site.
export function safeNextPath(next: string | null): string {
  if (next && next.startsWith('/') && !next.startsWith('//') && !next.includes('\\')) {
    return next
  }
  return '/transactions'
}
