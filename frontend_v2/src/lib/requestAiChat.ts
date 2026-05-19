import { getAccessToken } from './api'

/** Portal → Django proxy (JWT). Django → n8n (tenant integration token). */
export const REQUEST_AI_CHAT_PATH = '/api/requests/ai-chat/'

export function getRequestAiChatWebhookUrl(): string {
  const origin = typeof window !== 'undefined' ? window.location.origin.replace(/\/$/, '') : ''
  return `${origin}${REQUEST_AI_CHAT_PATH}`
}

let fetchHooked = false

/**
 * @n8n/chat calls fetch() itself. Hook only our proxy path and attach the portal JWT.
 */
export function hookRequestAiChatFetch(): void {
  if (fetchHooked || typeof window === 'undefined') return
  fetchHooked = true
  const nativeFetch = window.fetch.bind(window)
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    if (!url.includes(REQUEST_AI_CHAT_PATH)) {
      return nativeFetch(input, init)
    }
    const headers = new Headers(init?.headers)
    const access = getAccessToken()
    if (access) {
      headers.set('Authorization', `Bearer ${access}`)
    }
    return nativeFetch(input, { ...init, headers })
  }
}
