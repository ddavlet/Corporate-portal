import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  REQUEST_AI_CHAT_API_PATH,
  getRequestAiChatProxyHeaders,
  getRequestAiChatWebhookUrl,
} from './requestAiChat'

vi.mock('./api', () => ({
  readTgTokens: vi.fn(),
}))

import { readTgTokens } from './api'

describe('getRequestAiChatWebhookUrl', () => {
  it('builds same-origin ai-chat proxy URL', () => {
    expect(getRequestAiChatWebhookUrl('https://lemonfit.kolberg.uz')).toBe(
      `https://lemonfit.kolberg.uz${REQUEST_AI_CHAT_API_PATH}`,
    )
  })
})

describe('getRequestAiChatProxyHeaders', () => {
  afterEach(() => {
    vi.mocked(readTgTokens).mockReset()
    localStorage.clear()
  })

  it('adds Bearer for portal tokens', () => {
    localStorage.setItem('kolberg_v2_tokens', JSON.stringify({ access: 'portal-jwt', refresh: 'r' }))
    expect(getRequestAiChatProxyHeaders()).toEqual({ Authorization: 'Bearer portal-jwt' })
  })

  it('returns empty object when not logged in', () => {
    expect(getRequestAiChatProxyHeaders()).toEqual({})
  })
})
