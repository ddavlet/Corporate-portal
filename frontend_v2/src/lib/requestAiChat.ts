import { readTgTokens } from './api'

/**
 * n8n Chat Trigger production path (UUID + /chat).
 * На хосте тенанта: https://<tenant>.kolberg.uz/webhook/<id>/chat → n8n /webhook/<tenant>/<id>/chat
 */
export const REQUEST_AI_CHAT_WEBHOOK_PATH = 'd9f95bda-910e-4118-a6a9-08a86124d96c/chat'

export function getRequestAiChatWebhookUrl(origin = typeof window !== 'undefined' ? window.location.origin : ''): string {
  const base = origin.replace(/\/$/, '')
  return `${base}/webhook/${REQUEST_AI_CHAT_WEBHOOK_PATH}`
}

export function getAuthAccessToken(): string | null {
  if (typeof window === 'undefined') return null
  if (window.location.pathname.includes('/tg/')) {
    return readTgTokens()?.access ?? null
  }
  try {
    const raw = localStorage.getItem('kolberg_v2_tokens')
    if (!raw) return null
    const parsed = JSON.parse(raw) as { access?: string }
    return parsed.access?.trim() || null
  } catch {
    return null
  }
}
