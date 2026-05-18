import { getAccessToken } from './api'

/** Same-origin proxy → tenant n8n Chat Trigger (see RequestAiChatProxyView). */
export const REQUEST_AI_CHAT_API_PATH = '/api/requests/ai-chat/'

/** Mutable: @n8n/chat reads this object on each request (spread at fetch time). */
export const requestAiChatProxyHeaders: Record<string, string> = {}

export function getRequestAiChatWebhookUrl(origin = typeof window !== 'undefined' ? window.location.origin : ''): string {
  const base = origin.replace(/\/$/, '')
  return `${base}${REQUEST_AI_CHAT_API_PATH}`
}

/** Refresh JWT on the shared headers object (Django proxy only, not forwarded to n8n). */
export function syncRequestAiChatProxyHeaders(): void {
  for (const key of Object.keys(requestAiChatProxyHeaders)) {
    delete requestAiChatProxyHeaders[key]
  }
  const access = getAccessToken()
  if (access) {
    requestAiChatProxyHeaders.Authorization = `Bearer ${access}`
  }
}

let fetchAuthInstalled = false

/** Ensure @n8n/chat requests to our proxy always carry the current portal JWT. */
export function installRequestAiChatFetchAuth(): void {
  if (fetchAuthInstalled || typeof window === 'undefined') return
  fetchAuthInstalled = true
  const nativeFetch = window.fetch.bind(window)
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    if (url.includes(REQUEST_AI_CHAT_API_PATH)) {
      const headers = new Headers(init?.headers)
      const access = getAccessToken()
      if (access) headers.set('Authorization', `Bearer ${access}`)
      return nativeFetch(input, { ...init, headers })
    }
    return nativeFetch(input, init)
  }
}
