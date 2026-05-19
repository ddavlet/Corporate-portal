import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  REQUEST_AI_CHAT_PATH,
  getRequestAiChatWebhookUrl,
  hookRequestAiChatFetch,
} from './requestAiChat'

vi.mock('./api', () => ({
  getAccessToken: vi.fn(),
}))

import { getAccessToken } from './api'

describe('getRequestAiChatWebhookUrl', () => {
  it('builds same-origin ai-chat proxy URL', () => {
    vi.stubGlobal('window', { location: { origin: 'https://lemonfit.kolberg.uz' } })
    expect(getRequestAiChatWebhookUrl()).toBe(`https://lemonfit.kolberg.uz${REQUEST_AI_CHAT_PATH}`)
    vi.unstubAllGlobals()
  })
})

describe('hookRequestAiChatFetch', () => {
  const nativeFetch = vi.fn().mockResolvedValue(new Response('{}'))

  afterEach(() => {
    vi.mocked(getAccessToken).mockReset()
    vi.unstubAllGlobals()
  })

  it('adds portal JWT only for ai-chat proxy requests', async () => {
    vi.mocked(getAccessToken).mockReturnValue('portal-jwt')
    vi.stubGlobal('fetch', nativeFetch)
    hookRequestAiChatFetch()

    const hooked = globalThis.fetch as typeof fetch
    await hooked('https://lemonfit.kolberg.uz/api/requests/ai-chat/', { method: 'POST' })
    await hooked('https://example.com/other', { method: 'GET' })

    expect(nativeFetch).toHaveBeenCalledTimes(2)
    const proxyHeaders = nativeFetch.mock.calls[0][1]?.headers as Headers
    expect(proxyHeaders.get('Authorization')).toBe('Bearer portal-jwt')
    const otherHeaders = nativeFetch.mock.calls[1][1]?.headers as Headers | undefined
    expect(otherHeaders?.get?.('Authorization') ?? null).toBeNull()
  })
})
