import { describe, expect, it } from 'vitest'
import { REQUEST_AI_CHAT_API_PATH, getRequestAiChatWebhookUrl } from './requestAiChat'

describe('getRequestAiChatWebhookUrl', () => {
  it('builds same-origin ai-chat proxy URL', () => {
    expect(getRequestAiChatWebhookUrl('https://lemonfit.kolberg.uz')).toBe(
      `https://lemonfit.kolberg.uz${REQUEST_AI_CHAT_API_PATH}`,
    )
  })

  it('strips trailing slash from origin', () => {
    expect(getRequestAiChatWebhookUrl('https://lemonfit.kolberg.uz/')).toBe(
      `https://lemonfit.kolberg.uz${REQUEST_AI_CHAT_API_PATH}`,
    )
  })
})
