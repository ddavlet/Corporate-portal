import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  isPwaUpdateReady,
  registerPortalServiceWorker,
  resetPwaStateForTests,
  subscribePwaUpdate,
} from './pwa'

type FakeContainer = {
  controller: object | null
  register: ReturnType<typeof vi.fn>
  addEventListener: (type: string, listener: () => void) => void
  fire: (type: string) => void
}

function makeContainer(controller: object | null, update = vi.fn().mockResolvedValue(undefined)): FakeContainer {
  const listeners = new Map<string, Array<() => void>>()
  return {
    controller,
    register: vi.fn().mockResolvedValue({ update }),
    addEventListener: (type, listener) => {
      listeners.set(type, [...(listeners.get(type) ?? []), listener])
    },
    fire: (type) => (listeners.get(type) ?? []).forEach((l) => l()),
  }
}

function installServiceWorker(container: FakeContainer | undefined) {
  Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: container })
}

function removeServiceWorker() {
  delete (navigator as unknown as Record<string, unknown>).serviceWorker
}

describe('registerPortalServiceWorker', () => {
  beforeEach(() => {
    resetPwaStateForTests()
    window.history.replaceState(null, '', '/app/requests')
    delete window.Telegram
  })

  afterEach(() => {
    removeServiceWorker()
    delete window.Telegram
  })

  it('registers /app/sw.js with the /app/ scope in a normal browser tab', async () => {
    const container = makeContainer(null)
    installServiceWorker(container)
    const reg = await registerPortalServiceWorker({ isDev: false })
    expect(reg).not.toBeNull()
    expect(container.register).toHaveBeenCalledWith('/app/sw.js', { scope: '/app/' })
  })

  it('does not register inside the Telegram Mini App route', async () => {
    window.history.replaceState(null, '', '/app/tg/requests')
    const container = makeContainer(null)
    installServiceWorker(container)
    expect(await registerPortalServiceWorker({ isDev: false })).toBeNull()
    expect(container.register).not.toHaveBeenCalled()
  })

  it('does not register when Telegram passes initData', async () => {
    window.Telegram = { WebApp: { initData: 'query_id=1', initDataUnsafe: {}, ready: () => undefined } }
    const container = makeContainer(null)
    installServiceWorker(container)
    expect(await registerPortalServiceWorker({ isDev: false })).toBeNull()
    expect(container.register).not.toHaveBeenCalled()
  })

  it('registers when the Telegram script is loaded but there is no initData (plain browser)', async () => {
    window.Telegram = { WebApp: { initData: '', initDataUnsafe: {}, ready: () => undefined } }
    const container = makeContainer(null)
    installServiceWorker(container)
    await registerPortalServiceWorker({ isDev: false })
    expect(container.register).toHaveBeenCalledTimes(1)
  })

  it('does nothing and throws nothing without service worker support', async () => {
    removeServiceWorker()
    await expect(registerPortalServiceWorker({ isDev: false })).resolves.toBeNull()
  })

  it('does not register on the dev server', async () => {
    const container = makeContainer(null)
    installServiceWorker(container)
    expect(await registerPortalServiceWorker({ isDev: true })).toBeNull()
    expect(container.register).not.toHaveBeenCalled()
  })

  it('swallows a failed registration', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const container = makeContainer(null)
    container.register.mockRejectedValue(new Error('blocked'))
    installServiceWorker(container)
    await expect(registerPortalServiceWorker({ isDev: false })).resolves.toBeNull()
  })

  it('asks for a fresh worker on focus and when the tab becomes visible', async () => {
    const update = vi.fn().mockResolvedValue(undefined)
    installServiceWorker(makeContainer(null, update))
    await registerPortalServiceWorker({ isDev: false })

    window.dispatchEvent(new Event('focus'))
    expect(update).toHaveBeenCalledTimes(1)

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    document.dispatchEvent(new Event('visibilitychange'))
    expect(update).toHaveBeenCalledTimes(2)

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
    expect(update).toHaveBeenCalledTimes(2)
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
  })

  it('does not flag an update on the very first install', async () => {
    const container = makeContainer(null)
    installServiceWorker(container)
    await registerPortalServiceWorker({ isDev: false })
    container.fire('controllerchange')
    expect(isPwaUpdateReady()).toBe(false)
  })

  it('flags an update when a new worker replaces the one controlling the page', async () => {
    const listener = vi.fn()
    subscribePwaUpdate(listener)
    const container = makeContainer({})
    installServiceWorker(container)
    await registerPortalServiceWorker({ isDev: false })
    container.fire('controllerchange')
    expect(isPwaUpdateReady()).toBe(true)
    expect(listener).toHaveBeenCalledTimes(1)
  })
})
