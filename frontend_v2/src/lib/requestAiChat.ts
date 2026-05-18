import { readTgTokens } from './api'

/** Same-origin proxy → tenant n8n Chat Trigger (see RequestAiChatProxyView). */
export const REQUEST_AI_CHAT_API_PATH = '/api/requests/ai-chat/'

export function getRequestAiChatWebhookUrl(origin = typeof window !== 'undefined' ? window.location.origin : ''): string {
  const base = origin.replace(/\/$/, '')
  return `${base}${REQUEST_AI_CHAT_API_PATH}`
}

/** JWT for Django proxy only (not sent to n8n). */
export function getRequestAiChatProxyHeaders(): Record<string, string> {
  if (typeof window === 'undefined') return {}
  let access: string | null = null
  if (window.location.pathname.includes('/tg/')) {
    access = readTgTokens()?.access ?? null
  } else {
    try {
      const raw = localStorage.getItem('kolberg_v2_tokens')
      if (raw) {
        const parsed = JSON.parse(raw) as { access?: string }
        access = parsed.access?.trim() || null
      }
    } catch {
      access = null
    }
    if (!access) access = readTgTokens()?.access ?? null
  }
  if (!access) return {}
  return { Authorization: `Bearer ${access}` }
}
