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
  const fakeSelf = {
    location: { origin: 'https://acme.kolberg.uz' },
    clients: { claim },
    skipWaiting,
    addEventListener: (type: string, handler: Handler) => {
      handlers[type] = handler
    },
  }
  new Function('self', source)(fakeSelf)
  return { handlers, claim, skipWaiting }
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
  })

  it('does not use Cache Storage', () => {
    expect(swSource).not.toMatch(/\bcaches\b/)
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
