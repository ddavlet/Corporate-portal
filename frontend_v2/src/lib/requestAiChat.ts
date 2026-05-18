import { apiFetch, parseErrorBody, readTgTokens } from './api'

let cachedWebhookUrl: string | null = null

export async function getRequestAiChatWebhookUrl(): Promise<string> {
  if (cachedWebhookUrl) return cachedWebhookUrl
  const res = await apiFetch('/api/requests/ai-chat-config/')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as { webhook_url?: string } | null
  const url = json?.webhook_url?.trim()
  if (!url) throw new Error('URL чата не настроен для этого тенанта')
  cachedWebhookUrl = url
  return url
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
