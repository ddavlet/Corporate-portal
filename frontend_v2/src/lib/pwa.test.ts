import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  INSTALL_PROMPT_DISMISSED_KEY,
  canPromptInstall,
  captureInstallPrompt,
  dismissInstallPrompt,
  isInstallPromptDismissed,
  isIosSafari,
  isPwaUpdateReady,
  isStandaloneDisplay,
  promptInstall,
  registerPortalServiceWorker,
  resetPwaStateForTests,
  subscribeInstallPrompt,
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

/** A `beforeinstallprompt` as Chrome sends it: cancelable, with prompt() and the viewer's choice. */
function makeInstallEvent(outcome: 'accepted' | 'dismissed' = 'accepted') {
  const event = new Event('beforeinstallprompt', { cancelable: true }) as Event & {
    prompt: ReturnType<typeof vi.fn>
    userChoice: Promise<{ outcome: string }>
  }
  event.prompt = vi.fn().mockResolvedValue(undefined)
  event.userChoice = Promise.resolve({ outcome })
  return event
}

describe('install prompt', () => {
  beforeEach(() => {
    resetPwaStateForTests()
    window.history.replaceState(null, '', '/app/requests')
    delete window.Telegram
  })

  afterEach(() => {
    resetPwaStateForTests()
    window.history.replaceState(null, '', '/')
    delete window.Telegram
    vi.restoreAllMocks()
  })

  it('keeps the browser prompt and shows it on demand', async () => {
    captureInstallPrompt()
    const listener = vi.fn()
    subscribeInstallPrompt(listener)
    const event = makeInstallEvent('accepted')
    window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    expect(canPromptInstall()).toBe(true)
    expect(listener).toHaveBeenCalledTimes(1)

    await expect(promptInstall()).resolves.toBe('accepted')
    expect(event.prompt).toHaveBeenCalledTimes(1)
    // A prompt works once.
    expect(canPromptInstall()).toBe(false)
  })

  it('reports a declined install', async () => {
    captureInstallPrompt()
    window.dispatchEvent(makeInstallEvent('dismissed'))
    await expect(promptInstall()).resolves.toBe('dismissed')
  })

  it('answers «unavailable» without a prompt from the browser', async () => {
    captureInstallPrompt()
    await expect(promptInstall()).resolves.toBe('unavailable')
  })

  it('attaches its listener once', () => {
    const spy = vi.spyOn(window, 'addEventListener')
    captureInstallPrompt()
    captureInstallPrompt()
    expect(spy.mock.calls.filter(([type]) => type === 'beforeinstallprompt')).toHaveLength(1)
  })

  it('listens to nothing inside the Telegram Mini App', () => {
    window.history.replaceState(null, '', '/app/tg/requests')
    const spy = vi.spyOn(window, 'addEventListener')
    captureInstallPrompt()
    expect(spy.mock.calls.filter(([type]) => type === 'beforeinstallprompt')).toHaveLength(0)
    const event = makeInstallEvent()
    window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(false)
    expect(canPromptInstall()).toBe(false)
  })

  it('forgets the prompt once the app is installed', () => {
    captureInstallPrompt()
    window.dispatchEvent(makeInstallEvent())
    window.dispatchEvent(new Event('appinstalled'))
    expect(canPromptInstall()).toBe(false)
  })
})

describe('isStandaloneDisplay', () => {
  const originalMatchMedia = window.matchMedia

  afterEach(() => {
    Object.defineProperty(window, 'matchMedia', { configurable: true, writable: true, value: originalMatchMedia })
    delete (navigator as unknown as Record<string, unknown>).standalone
  })

  function stubDisplayMode(standalone: boolean) {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: (query: string) => ({
        matches: query === '(display-mode: standalone)' ? standalone : false,
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      }),
    })
  }

  it('is true when the display-mode query matches', () => {
    stubDisplayMode(true)
    expect(isStandaloneDisplay()).toBe(true)
  })

  it('is true on iOS when navigator.standalone is set', () => {
    stubDisplayMode(false)
    Object.defineProperty(navigator, 'standalone', { configurable: true, value: true })
    expect(isStandaloneDisplay()).toBe(true)
  })

  it('is false in a browser tab', () => {
    stubDisplayMode(false)
    expect(isStandaloneDisplay()).toBe(false)
  })
})

describe('install prompt dismissal', () => {
  beforeEach(() => {
    resetPwaStateForTests()
    window.localStorage.removeItem(INSTALL_PROMPT_DISMISSED_KEY)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    window.localStorage.removeItem(INSTALL_PROMPT_DISMISSED_KEY)
    resetPwaStateForTests()
  })

  it('reads and writes the flag on the device', () => {
    expect(isInstallPromptDismissed()).toBe(false)
    dismissInstallPrompt()
    expect(window.localStorage.getItem(INSTALL_PROMPT_DISMISSED_KEY)).toBe('1')
    resetPwaStateForTests()
    expect(isInstallPromptDismissed()).toBe(true)
  })

  it('warns and keeps the hint closed for this page when storage is refused', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    expect(isInstallPromptDismissed()).toBe(false)
    dismissInstallPrompt()
    expect(warn).toHaveBeenCalled()
    expect(isInstallPromptDismissed()).toBe(true)
  })
})

describe('isIosSafari', () => {
  it('recognises iPhone and iPad', () => {
    expect(
      isIosSafari('Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Version/17.5 Mobile/15E148 Safari/604.1'),
    ).toBe(true)
    expect(isIosSafari('Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148', 5)).toBe(true)
  })

  it('recognises iPadOS, which reports a Mac with touch', () => {
    expect(isIosSafari('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15', 5)).toBe(true)
  })

  it('is false on Android and on a desktop Mac', () => {
    expect(isIosSafari('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36', 5)).toBe(false)
    expect(isIosSafari('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15', 0)).toBe(false)
  })
})
