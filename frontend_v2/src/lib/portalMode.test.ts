import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createStorageMock } from '../test/helpers'
import {
  PORTAL_CONFIG_CACHE_KEY,
  PORTAL_CONFIG_URL,
  PORTAL_CONFIG_WAIT_MS,
  getSharedHost,
  initPortalMode,
  isSharedAppMode,
  resetPortalModeForTests,
} from './portalMode'

const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
const fetchMock = vi.fn()
const reloadMock = vi.fn()
const localStorageMock = createStorageMock()

function setLocation(hostname: string, pathname = '/app/requests') {
  Object.defineProperty(globalThis, 'window', {
    value: { location: { hostname, pathname, reload: reloadMock } },
    configurable: true,
  })
}

function configResponse(sharedHost: string | null, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => ({ shared_host: sharedHost }) } as Response
}

function cache(sharedHost: string | null) {
  localStorageMock.setItem(PORTAL_CONFIG_CACHE_KEY, JSON.stringify({ shared_host: sharedHost }))
}

function cachedValue() {
  const raw = localStorageMock.getItem(PORTAL_CONFIG_CACHE_KEY)
  return raw ? JSON.parse(raw) : null
}

/** A promise that settles only when the test says so (the server is slow). */
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

describe('portalMode', () => {
  beforeEach(() => {
    resetPortalModeForTests()
    localStorageMock.clear()
    fetchMock.mockReset()
    reloadMock.mockReset()
    Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock, configurable: true })
    Object.defineProperty(globalThis, 'fetch', { value: fetchMock, configurable: true })
    setLocation('app.example.com')
  })

  afterEach(() => {
    vi.useRealTimers()
    if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow)
  })

  it('does not ask the server in the Telegram Mini App and stays in subdomain mode', async () => {
    setLocation('app.example.com', '/app/tg/requests')
    cache('app.example.com')
    await initPortalMode()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(isSharedAppMode()).toBe(false)
  })

  it('renders at once from the cache and asks again in the background without a token', async () => {
    cache('app.example.com')
    const slow = deferred<Response>()
    fetchMock.mockReturnValue(slow.promise)

    await initPortalMode()

    expect(isSharedAppMode()).toBe(true)
    expect(getSharedHost()).toBe('app.example.com')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe(PORTAL_CONFIG_URL)
    expect(new Headers(init.headers).has('Authorization')).toBe(false)
    expect(new Headers(init.headers).has('X-Tenant')).toBe(false)

    slow.resolve(configResponse('app.example.com'))
    await vi.waitFor(() => expect(cachedValue()).toEqual({ shared_host: 'app.example.com' }))
    expect(reloadMock).not.toHaveBeenCalled()
  })

  it('does not wait on a subdomain with a cached answer', async () => {
    setLocation('acme.example.com')
    cache('app.example.com')
    fetchMock.mockReturnValue(new Promise(() => undefined))
    await initPortalMode()
    expect(isSharedAppMode()).toBe(false)
    expect(getSharedHost()).toBe('app.example.com')
  })

  it('reloads when the background answer changes the mode on this host', async () => {
    cache(null)
    fetchMock.mockResolvedValue(configResponse('app.example.com'))
    await initPortalMode()
    expect(isSharedAppMode()).toBe(false)
    await vi.waitFor(() => expect(reloadMock).toHaveBeenCalledTimes(1))
    expect(cachedValue()).toEqual({ shared_host: 'app.example.com' })
  })

  it('reloads when the mode is switched off on the server', async () => {
    cache('app.example.com')
    fetchMock.mockResolvedValue(configResponse(null))
    await initPortalMode()
    await vi.waitFor(() => expect(reloadMock).toHaveBeenCalledTimes(1))
    expect(cachedValue()).toEqual({ shared_host: null })
  })

  it('keeps a background failure silent and the cached mode in place', async () => {
    cache('app.example.com')
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    await initPortalMode()
    await Promise.resolve()
    expect(isSharedAppMode()).toBe(true)
    expect(reloadMock).not.toHaveBeenCalled()
  })

  it('waits for the first answer when nothing is cached', async () => {
    fetchMock.mockResolvedValue(configResponse('APP.example.com'))
    await initPortalMode()
    expect(isSharedAppMode()).toBe(true)
    expect(cachedValue()).toEqual({ shared_host: 'app.example.com' })
    expect(reloadMock).not.toHaveBeenCalled()
  })

  it('falls back to subdomain mode after the wait limit, and a late answer switches on with a reload', async () => {
    vi.useFakeTimers()
    const slow = deferred<Response>()
    fetchMock.mockReturnValue(slow.promise)

    let ready = false
    void initPortalMode().then(() => {
      ready = true
    })
    await vi.advanceTimersByTimeAsync(PORTAL_CONFIG_WAIT_MS - 1)
    expect(ready).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect(ready).toBe(true)
    expect(isSharedAppMode()).toBe(false)

    slow.resolve(configResponse('app.example.com'))
    await vi.waitFor(() => expect(reloadMock).toHaveBeenCalledTimes(1))
    expect(cachedValue()).toEqual({ shared_host: 'app.example.com' })
  })

  it('does not reload in a loop when storage is unavailable and the answer comes late', async () => {
    const blocked = {
      getItem: () => {
        throw new Error('SecurityError')
      },
      setItem: () => {
        throw new Error('SecurityError')
      },
    }
    Object.defineProperty(globalThis, 'localStorage', { value: blocked, configurable: true })
    vi.useFakeTimers()
    const slow = deferred<Response>()
    fetchMock.mockReturnValue(slow.promise)

    void initPortalMode()
    await vi.advanceTimersByTimeAsync(PORTAL_CONFIG_WAIT_MS)
    expect(isSharedAppMode()).toBe(false)

    slow.resolve(configResponse('app.example.com'))
    await vi.waitFor(() => expect(isSharedAppMode()).toBe(true))
    expect(reloadMock).not.toHaveBeenCalled()
  })

  it('treats an error without a cache as subdomain mode and caches nothing', async () => {
    fetchMock.mockResolvedValue(configResponse(null, 404))
    await initPortalMode()
    expect(isSharedAppMode()).toBe(false)
    expect(cachedValue()).toBeNull()
  })

  it('is off when the server has no shared host', async () => {
    fetchMock.mockResolvedValue(configResponse(null))
    await initPortalMode()
    expect(isSharedAppMode()).toBe(false)
    expect(getSharedHost()).toBeNull()
  })
})
