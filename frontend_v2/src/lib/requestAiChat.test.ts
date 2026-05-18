import { describe, expect, it } from 'vitest'
import { REQUEST_AI_CHAT_WEBHOOK_PATH, getRequestAiChatWebhookUrl } from './requestAiChat'

describe('getRequestAiChatWebhookUrl', () => {
  it('builds tenant-scoped n8n chat webhook URL', () => {
    expect(getRequestAiChatWebhookUrl('https://dev.kolberg.uz')).toBe(
      'https://dev.kolberg.uz/webhook/d9f95bda-910e-4118-a6a9-08a86124d96c/chat',
    )
    expect(getRequestAiChatWebhookUrl('https://acme.kolberg.uz')).toBe(
      `https://acme.kolberg.uz/webhook/${REQUEST_AI_CHAT_WEBHOOK_PATH}`,
    )
  })

  it('strips trailing slash from origin', () => {
    expect(getRequestAiChatWebhookUrl('https://dev.kolberg.uz/')).toBe(
      'https://dev.kolberg.uz/webhook/d9f95bda-910e-4118-a6a9-08a86124d96c/chat',
    )
  })
})
