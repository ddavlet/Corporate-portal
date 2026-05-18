import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  REQUEST_AI_CHAT_API_PATH,
  getRequestAiChatWebhookUrl,
  requestAiChatProxyHeaders,
  syncRequestAiChatProxyHeaders,
} from './requestAiChat'

vi.mock('./api', () => ({
  getAccessToken: vi.fn(),
}))

import { getAccessToken } from './api'

describe('getRequestAiChatWebhookUrl', () => {
  it('builds same-origin ai-chat proxy URL', () => {
    expect(getRequestAiChatWebhookUrl('https://lemonfit.kolberg.uz')).toBe(
      `https://lemonfit.kolberg.uz${REQUEST_AI_CHAT_API_PATH}`,
    )
  })
})

describe('syncRequestAiChatProxyHeaders', () => {
  afterEach(() => {
    vi.mocked(getAccessToken).mockReset()
    for (const key of Object.keys(requestAiChatProxyHeaders)) {
      delete requestAiChatProxyHeaders[key]
    }
  })

  it('writes Bearer token into shared headers object', () => {
    vi.mocked(getAccessToken).mockReturnValue('portal-jwt')
    syncRequestAiChatProxyHeaders()
    expect(requestAiChatProxyHeaders.Authorization).toBe('Bearer portal-jwt')
  })

  it('clears Authorization when logged out', () => {
    requestAiChatProxyHeaders.Authorization = 'Bearer stale'
    vi.mocked(getAccessToken).mockReturnValue(null)
    syncRequestAiChatProxyHeaders()
    expect(requestAiChatProxyHeaders.Authorization).toBeUndefined()
  })
})
