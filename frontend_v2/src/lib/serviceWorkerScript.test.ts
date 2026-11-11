import { beforeEach, describe, expect, it, vi } from 'vitest'
import swSource from '../../public/sw.js?raw'
import manifestSource from '../../public/manifest.webmanifest?raw'
import viteConfigSource from '../../vite.config.ts?raw'
import { readServiceWorkerBuildId, stampServiceWorker } from './swBuildStamp'

type Handler = (event: Record<string, unknown>) => void

function loadWorker(source: string = swSource) {
  const handlers: Record<string, Handler> = {}
  const claim = vi.fn().mockResolvedValue(undefined)
  const skipWaiting = vi.fn()
  // The worker forwards navigations with the global fetch; a stub keeps the test off the real network.
  const fetchStub = vi.fn().mockResolvedValue({ ok: true })
  const fakeSelf = {
    location: { origin: 'https://acme.kolberg.uz' },
    clients: { claim },
    skipWaiting,
    addEventListener: (type: string, handler: Handler) => {
      handlers[type] = handler
    },
  }
  new Function('self', 'fetch', source)(fakeSelf, fetchStub)
  return { handlers, claim, skipWaiting, fetchStub }
}

function navigate(handlers: Record<string, Handler>, url: string, mode = 'navigate') {
  const respondWith = vi.fn()
  handlers.fetch({ request: { mode, url }, respondWith })
  return respondWith
}

describe('public/sw.js', () => {
  let worker: ReturnType<typeof loadWorker>

  beforeEach(() => {
    worker = loadWorker()
  })

  it('takes over immediately on install and activate', () => {
    worker.handlers.install({})
    expect(worker.skipWaiting).toHaveBeenCalled()
    const waitUntil = vi.fn()
    worker.handlers.activate({ waitUntil })
    expect(worker.claim).toHaveBeenCalled()
    expect(waitUntil).toHaveBeenCalled()
  })

  it('never intercepts /api/* requests', () => {
    expect(navigate(worker.handlers, 'https://acme.kolberg.uz/api/requests/')).not.toHaveBeenCalled()
    expect(navigate(worker.handlers, 'https://acme.kolberg.uz/api/requests/', 'cors')).not.toHaveBeenCalled()
  })

  it('does not intercept non-navigation requests under /app/', () => {
    expect(navigate(worker.handlers, 'https://acme.kolberg.uz/app/assets/a.js', 'no-cors')).not.toHaveBeenCalled()
  })

  it('does not intercept other origins', () => {
    expect(navigate(worker.handlers, 'https://example.org/app/')).not.toHaveBeenCalled()
  })

  it('leaves the Telegram Mini App alone', () => {
    expect(navigate(worker.handlers, 'https://acme.kolberg.uz/app/tg/requests')).not.toHaveBeenCalled()
    expect(navigate(worker.handlers, 'https://acme.kolberg.uz/app/tg')).not.toHaveBeenCalled()
  })

  it('passes /app/ navigations straight to the network', () => {
    const respondWith = navigate(worker.handlers, 'https://acme.kolberg.uz/app/requests/5')
    expect(respondWith).toHaveBeenCalledTimes(1)
    expect(worker.fetchStub).toHaveBeenCalledTimes(1)
    expect(worker.fetchStub.mock.calls[0][0]).toMatchObject({ url: 'https://acme.kolberg.uz/app/requests/5' })
  })

  it('does not use Cache Storage', () => {
    expect(swSource).not.toMatch(/\bcaches\b/)
  })
})

type Shown = { title: string; tag?: string; data?: { url?: string }; close: ReturnType<typeof vi.fn> }

/** Worker with notification, client and badging fakes on `self`, on the shared app host. */
function loadPushWorker(options: { windows?: Array<Record<string, unknown>>; badging?: boolean } = {}) {
  const handlers: Record<string, Handler> = {}
  const shown: Shown[] = []
  const showNotification = vi.fn(async (title: string, opts: { tag?: string; data?: { url?: string } }) => {
    // Like the browser: a notification with the same tag replaces the previous one.
    const index = shown.findIndex((n) => opts.tag && n.tag === opts.tag)
    const entry = { title, tag: opts.tag, data: opts.data, close: vi.fn() }
    if (index >= 0) shown.splice(index, 1, entry)
    else shown.push(entry)
  })
  const getNotifications = vi.fn(async () => [...shown])
  const setAppBadge = vi.fn().mockResolvedValue(undefined)
  const clearAppBadge = vi.fn().mockResolvedValue(undefined)
  const openWindow = vi.fn().mockResolvedValue(null)
  const matchAll = vi.fn().mockResolvedValue(options.windows ?? [])
  const fakeSelf = {
    location: { origin: 'https://app.kolberg.uz' },
    registration: { showNotification, getNotifications },
    navigator: options.badging === false ? {} : { setAppBadge, clearAppBadge },
    clients: { claim: vi.fn(), matchAll, openWindow },
    skipWaiting: vi.fn(),
    addEventListener: (type: string, handler: Handler) => {
      handlers[type] = handler
    },
  }
  new Function('self', 'fetch', swSource)(fakeSelf, vi.fn())
  return { handlers, shown, showNotification, setAppBadge, clearAppBadge, openWindow, matchAll }
}

async function dispatch(handler: Handler, event: Record<string, unknown>) {
  let work: Promise<unknown> = Promise.resolve()
  handler({ ...event, waitUntil: (p: Promise<unknown>) => (work = p) })
  await work
}

function pushEvent(payload: unknown) {
  return { data: { json: () => payload } }
}

const SHOW = {
  type: 'show',
  tag: 'alpha:request-12',
  title: 'Альфа: Оплата аренды',
  body: '1 500 000 UZS',
  url: '/app/requests/12?company=alpha',
  count: 2,
  active_tags: ['alpha:request-12', 'beta:request-7'],
}

describe('public/sw.js Web Push', () => {
  it('shows one notification with the object tag, title, amount and link (crit. 20)', async () => {
    const worker = loadPushWorker()
    await dispatch(worker.handlers.push, pushEvent(SHOW))
    expect(worker.showNotification).toHaveBeenCalledTimes(1)
    const [title, opts] = worker.showNotification.mock.calls[0]
    expect(title).toBe('Альфа: Оплата аренды')
    expect(opts).toMatchObject({ body: '1 500 000 UZS', tag: 'alpha:request-12' })
    expect(opts.data?.url).toBe('https://app.kolberg.uz/app/requests/12?company=alpha')
    expect(worker.setAppBadge).toHaveBeenCalledWith(2)
  })

  it('closes notifications whose tag is no longer active (crit. 21)', async () => {
    const worker = loadPushWorker()
    await dispatch(worker.handlers.push, pushEvent({ ...SHOW, tag: 'beta:request-7', active_tags: ['beta:request-7'] }))
    await dispatch(worker.handlers.push, pushEvent({ ...SHOW, tag: 'alpha:request-1', active_tags: ['alpha:request-1'] }))
    const stale = worker.shown.find((n) => n.tag === 'beta:request-7')
    const fresh = worker.shown.find((n) => n.tag === 'alpha:request-1')
    expect(stale?.close).toHaveBeenCalled()
    expect(fresh?.close).not.toHaveBeenCalled()
  })

  it('keeps every notification when active_tags is missing (payload too large)', async () => {
    const worker = loadPushWorker()
    await dispatch(worker.handlers.push, pushEvent({ ...SHOW, tag: 'beta:request-7' }))
    await dispatch(worker.handlers.push, pushEvent({ ...SHOW, active_tags: null }))
    expect(worker.shown.every((n) => n.close.mock.calls.length === 0)).toBe(true)
  })

  it('always shows a notification, even for an unreadable payload', async () => {
    const worker = loadPushWorker()
    await dispatch(worker.handlers.push, {
      data: {
        json: () => {
          throw new SyntaxError('bad')
        },
      },
    })
    expect(worker.showNotification).toHaveBeenCalledTimes(1)
    expect(worker.showNotification.mock.calls[0][0]).toBe('Kolberg')
    expect(worker.showNotification.mock.calls[0][1].data?.url).toBe('https://app.kolberg.uz/app/notifications')
    expect(worker.clearAppBadge).toHaveBeenCalled()
  })

  it('never opens a link outside the portal', async () => {
    const worker = loadPushWorker()
    await dispatch(worker.handlers.push, pushEvent({ ...SHOW, url: 'https://evil.example/app/x' }))
    await dispatch(worker.handlers.push, pushEvent({ ...SHOW, tag: 'x', url: '/app/tg/requests/1' }))
    const urls = worker.showNotification.mock.calls.map((call) => call[1].data?.url)
    expect(urls).toEqual(['https://app.kolberg.uz/app/notifications', 'https://app.kolberg.uz/app/notifications'])
  })

  it('works without the Badging API', async () => {
    const worker = loadPushWorker({ badging: false })
    await expect(dispatch(worker.handlers.push, pushEvent(SHOW))).resolves.toBeUndefined()
    expect(worker.showNotification).toHaveBeenCalledTimes(1)
  })

  it('a click focuses an open portal window and navigates it to the object', async () => {
    const navigate = vi.fn().mockResolvedValue(null)
    const client = { url: 'https://app.kolberg.uz/app/', focus: vi.fn(), navigate }
    client.focus.mockResolvedValue(client)
    const worker = loadPushWorker({ windows: [client] })
    const close = vi.fn()
    await dispatch(worker.handlers.notificationclick, {
      notification: { close, data: { url: 'https://app.kolberg.uz/app/requests/12?company=alpha' } },
    })
    expect(close).toHaveBeenCalled()
    expect(client.focus).toHaveBeenCalled()
    expect(navigate).toHaveBeenCalledWith('https://app.kolberg.uz/app/requests/12?company=alpha')
    expect(worker.openWindow).not.toHaveBeenCalled()
  })

  it('a click opens a new window when the portal is not open', async () => {
    const worker = loadPushWorker()
    await dispatch(worker.handlers.notificationclick, {
      notification: { close: vi.fn(), data: { url: 'https://app.kolberg.uz/app/requests/12' } },
    })
    expect(worker.openWindow).toHaveBeenCalledWith('https://app.kolberg.uz/app/requests/12')
  })

  it('a click opens a new window when the open one cannot be navigated', async () => {
    const client = { url: 'https://app.kolberg.uz/app/', focus: vi.fn(), navigate: vi.fn().mockRejectedValue(new TypeError('uncontrolled')) }
    client.focus.mockResolvedValue(client)
    const worker = loadPushWorker({ windows: [client] })
    await dispatch(worker.handlers.notificationclick, {
      notification: { close: vi.fn(), data: { url: 'https://app.kolberg.uz/app/requests/12' } },
    })
    expect(worker.openWindow).toHaveBeenCalledWith('https://app.kolberg.uz/app/requests/12')
  })

  it('the open portal closes stale notifications and updates the badge (message action-items)', async () => {
    const worker = loadPushWorker()
    await dispatch(worker.handlers.push, pushEvent({ ...SHOW, tag: 'beta:request-7', active_tags: ['beta:request-7'] }))
    worker.setAppBadge.mockClear()
    await dispatch(worker.handlers.message, { data: { type: 'action-items', tags: ['alpha:request-12'], count: 0 } })
    expect(worker.shown.find((n) => n.tag === 'beta:request-7')?.close).toHaveBeenCalled()
    expect(worker.clearAppBadge).toHaveBeenCalled()
    expect(worker.setAppBadge).not.toHaveBeenCalled()
  })

  it('ignores other messages', async () => {
    const worker = loadPushWorker()
    await dispatch(worker.handlers.push, pushEvent(SHOW))
    await dispatch(worker.handlers.message, { data: { type: 'other' } })
    await dispatch(worker.handlers.message, { data: null })
    expect(worker.shown[0].close).not.toHaveBeenCalled()
  })
})

describe('service worker build stamp', () => {
  it('makes sw.js differ between builds, so the browser installs the new worker after a deploy', () => {
    const first = stampServiceWorker(swSource, 'aaa111')
    const second = stampServiceWorker(swSource, 'bbb222')
    expect(first).not.toBe(second)
    expect(readServiceWorkerBuildId(first)).toBe('aaa111')
    expect(readServiceWorkerBuildId(second)).toBe('bbb222')
  })

  it('keeps one stamp when applied twice and leaves the worker working', () => {
    const stamped = stampServiceWorker(stampServiceWorker(swSource, 'old'), 'new')
    expect(stamped.match(/kolberg-build:/g)).toHaveLength(1)
    expect(readServiceWorkerBuildId(stamped)).toBe('new')
    const { handlers } = loadWorker(stamped)
    const respondWith = vi.fn()
    handlers.fetch({ request: { mode: 'navigate', url: 'https://acme.kolberg.uz/app/' }, respondWith })
    expect(respondWith).toHaveBeenCalledTimes(1)
  })

  it('rejects an empty build id', () => {
    expect(() => stampServiceWorker(swSource, '  ')).toThrow()
  })

  it('the source file itself carries no stamp, the build adds it', () => {
    expect(readServiceWorkerBuildId(swSource)).toBeNull()
    expect(viteConfigSource).toMatch(/serviceWorkerBuildStamp\(\)/)
    expect(viteConfigSource).toMatch(/stampServiceWorker\(/)
  })
})

describe('public/manifest.webmanifest', () => {
  const manifest = JSON.parse(manifestSource)

  it('is scoped to /app/ and starts there', () => {
    expect(manifest.scope).toBe('/app/')
    expect(manifest.start_url).toBe('/app/')
    expect(manifest.display).toBe('standalone')
  })

  it('has a name and 192, 512 and maskable icons under /app/', () => {
    expect(manifest.name).toBeTruthy()
    expect(manifest.short_name).toBeTruthy()
    const icons = manifest.icons as { src: string; sizes: string; purpose?: string }[]
    expect(icons.every((icon) => icon.src.startsWith('/app/icons/'))).toBe(true)
    expect(icons.some((icon) => icon.sizes === '192x192')).toBe(true)
    expect(icons.some((icon) => icon.sizes === '512x512' && icon.purpose === 'any')).toBe(true)
    expect(icons.some((icon) => icon.purpose === 'maskable')).toBe(true)
  })
})
