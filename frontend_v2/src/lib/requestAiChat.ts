/** Same-origin proxy → tenant n8n Chat Trigger (see RequestAiChatProxyView). */
export const REQUEST_AI_CHAT_API_PATH = '/api/requests/ai-chat/'

export function getRequestAiChatWebhookUrl(origin = typeof window !== 'undefined' ? window.location.origin : ''): string {
  const base = origin.replace(/\/$/, '')
  return `${base}${REQUEST_AI_CHAT_API_PATH}`
}
