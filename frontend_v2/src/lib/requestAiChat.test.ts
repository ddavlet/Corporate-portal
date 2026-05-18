import { afterEach, describe, expect, it, vi } from 'vitest'
import { getRequestAiChatWebhookUrl } from './requestAiChat'

vi.mock('./api', () => ({
  apiFetch: vi.fn(),
  parseErrorBody: vi.fn(async () => 'error'),
  readTgTokens: vi.fn(),
}))

import { apiFetch } from './api'

describe('getRequestAiChatWebhookUrl', () => {
  afterEach(() => {
    vi.mocked(apiFetch).mockReset()
  })

  it('loads webhook_url from tenant config API', async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      new Response(JSON.stringify({ webhook_url: 'https://dev.kolberg.uz/webhook/uuid/chat' }), { status: 200 }),
    )
    await expect(getRequestAiChatWebhookUrl()).resolves.toBe('https://dev.kolberg.uz/webhook/uuid/chat')
    expect(apiFetch).toHaveBeenCalledWith('/api/requests/ai-chat-config/')
  })
})
