import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { portal, api } = vi.hoisted(() => ({
  portal: { shared: true, host: 'app.kolberg.uz' as string | null },
  api: {
    getVapidPublicKey: vi.fn(),
    postPushSubscription: vi.fn(),
    postPushUnsubscribe: vi.fn(),
  },
}))

vi.mock('./portalMode', () => ({
  isSharedAppMode: () => portal.shared,
  getSharedHost: () => portal.host,
}))
vi.mock('./pushApi', () => api)

import {
  enablePush,
  getPushSupport,
  resetWebPushStateForTests,
  revokePushSubscription,
  syncPushSubscription,
  urlBase64ToUint8Array,
} from './webPush'

// The code under test does not check the P-256 key shape: any base64url string will do.
const VAPID_KEY = 'BOrVapidKey_-abc'

type FakeSubscription = {
  endpoint: string
  options: { applicationServerKey: ArrayBuffer | null }
  toJSON: () => { endpoint: string; keys: { p256dh: string; auth: string } }
  unsubscribe: ReturnType<typeof vi.fn>
}

function fakeSubscription(endpoint = 'https://push.example/abc'): FakeSubscription {
  return {
    endpoint,
    options: { applicationServerKey: urlBase64ToUint8Array(VAPID_KEY).buffer },
    toJSON: () => ({ endpoint, keys: { p256dh: 'p-key', auth: 'a-key' } }),
    unsubscribe: vi.fn().mockResolvedValue(true),
  }
}

type Env = {
  pushManager: { getSubscription: ReturnType<typeof vi.fn>; subscribe: ReturnType<typeof vi.fn> }
  requestPermission: ReturnType<typeof vi.fn>
  getRegistration: ReturnType<typeof vi.fn>
}

const win = window as unknown as Record<string, unknown>
const nav = navigator as unknown as Record<string, unknown>

function setUserAgent(ua: string) {
  Object.defineProperty(navigator, 'userAgent', { configurable: true, value: ua })
}

function installPushEnv(options: { permission?: NotificationPermission; existing?: FakeSubscription | null } = {}): Env {
  const pushManager = {
    getSubscription: vi.fn().mockResolvedValue(options.existing ?? null),
    subscribe: vi.fn().mockImplementation(async () => fakeSubscription()),
  }
  const registration = { active: {}, pushManager }
  const getRegistration = vi.fn().mockResolvedValue(registration)
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: { getRegistration, ready: Promise.resolve(registration) },
  })
  win.PushManager = function PushManager() {}
  const requestPermission = vi.fn().mockResolvedValue('granted')
  win.Notification = { permission: options.permission ?? 'default', requestPermission }
  return { pushManager, requestPermission, getRegistration }
}

describe('webPush', () => {
  beforeEach(() => {
    portal.shared = true
    portal.host = 'app.kolberg.uz'
    window.history.replaceState(null, '', '/app/notifications')
    delete window.Telegram
    resetWebPushStateForTests()
    api.getVapidPublicKey.mockReset().mockResolvedValue({ enabled: true, public_key: VAPID_KEY })
    api.postPushSubscription.mockReset().mockResolvedValue(undefined)
    api.postPushUnsubscribe.mockReset().mockResolvedValue(undefined)
    setUserAgent('Mozilla/5.0 (X11; Linux x86_64) Chrome/130.0')
  })

  afterEach(() => {
    delete nav.serviceWorker
    delete win.PushManager
    delete win.Notification
  })

  describe('getPushSupport', () => {
    it('reports unsupported without PushManager and throws nothing (crit. 18)', async () => {
      Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: { getRegistration: vi.fn() } })
      await expect(getPushSupport()).resolves.toBe('unsupported')
      await expect(enablePush()).resolves.toBe('unavailable')
      await expect(revokePushSubscription()).resolves.toBeUndefined()
      expect(api.getVapidPublicKey).not.toHaveBeenCalled()
    })

    it('is off in the Telegram Mini App', async () => {
      installPushEnv()
      window.history.replaceState(null, '', '/app/tg/requests')
      await expect(getPushSupport()).resolves.toBe('telegram')
    })

    it('points a company subdomain to the shared app host', async () => {
      installPushEnv()
      portal.shared = false
      await expect(getPushSupport()).resolves.toBe('subdomain-use-shared-host')
      await expect(enablePush()).resolves.toBe('unavailable')
      expect(api.postPushSubscription).not.toHaveBeenCalled()
    })

    it('is disabled on a subdomain when the shared host is off', async () => {
      portal.shared = false
      portal.host = null
      await expect(getPushSupport()).resolves.toBe('disabled-server')
    })

    it('asks iPhone users outside the installed app to add it to the Home Screen', async () => {
      setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/604.1')
      // Safari outside the Home Screen app has no PushManager at all.
      await expect(getPushSupport()).resolves.toBe('ios-needs-install')
    })

    it('treats the installed iPhone app as a regular push context', async () => {
      setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/604.1')
      Object.defineProperty(navigator, 'standalone', { configurable: true, value: true })
      installPushEnv()
      try {
        await expect(getPushSupport()).resolves.toBe('default')
      } finally {
        delete nav.standalone
      }
    })

    it('reports disabled-server when the server has no VAPID key', async () => {
      installPushEnv()
      api.getVapidPublicKey.mockResolvedValue({ enabled: false, public_key: null })
      await expect(getPushSupport()).resolves.toBe('disabled-server')
    })

    it('reports disabled-server and retries later when the key request fails', async () => {
      installPushEnv()
      api.getVapidPublicKey.mockRejectedValueOnce(new Error('offline'))
      await expect(getPushSupport()).resolves.toBe('disabled-server')
      await expect(getPushSupport()).resolves.toBe('default')
      expect(api.getVapidPublicKey).toHaveBeenCalledTimes(2)
    })

    it('mirrors the notification permission', async () => {
      installPushEnv({ permission: 'denied' })
      await expect(getPushSupport()).resolves.toBe('denied')
      installPushEnv({ permission: 'granted' })
      await expect(getPushSupport()).resolves.toBe('granted')
    })

    it('never asks for permission by itself', async () => {
      const env = installPushEnv()
      await getPushSupport()
      expect(env.requestPermission).not.toHaveBeenCalled()
    })
  })

  describe('enablePush', () => {
    it('asks permission, subscribes with userVisibleOnly and registers the device (crit. 19)', async () => {
      const env = installPushEnv()
      await expect(enablePush()).resolves.toBe('subscribed')
      expect(env.requestPermission).toHaveBeenCalledTimes(1)
      expect(env.pushManager.subscribe).toHaveBeenCalledTimes(1)
      const [options] = env.pushManager.subscribe.mock.calls[0]
      expect(options.userVisibleOnly).toBe(true)
      expect(Array.from(options.applicationServerKey as Uint8Array)).toEqual(Array.from(urlBase64ToUint8Array(VAPID_KEY)))
      expect(api.postPushSubscription).toHaveBeenCalledWith({
        endpoint: 'https://push.example/abc',
        keys: { p256dh: 'p-key', auth: 'a-key' },
      })
    })

    it('stops when the user does not allow notifications', async () => {
      const env = installPushEnv()
      env.requestPermission.mockResolvedValue('denied')
      await expect(enablePush()).resolves.toBe('denied')
      expect(env.pushManager.subscribe).not.toHaveBeenCalled()
      expect(api.postPushSubscription).not.toHaveBeenCalled()
    })

    it('reuses an existing browser subscription instead of creating a second one', async () => {
      const env = installPushEnv({ permission: 'granted', existing: fakeSubscription() })
      await expect(enablePush()).resolves.toBe('subscribed')
      expect(env.requestPermission).not.toHaveBeenCalled()
      expect(env.pushManager.subscribe).not.toHaveBeenCalled()
      expect(api.postPushSubscription).toHaveBeenCalledTimes(1)
    })

    it('reports an error when the server refuses the subscription', async () => {
      installPushEnv()
      api.postPushSubscription.mockRejectedValue(new Error('409'))
      await expect(enablePush()).resolves.toBe('error')
    })

    it('is unavailable without a registered service worker', async () => {
      const env = installPushEnv()
      env.getRegistration.mockResolvedValue(undefined)
      await expect(enablePush()).resolves.toBe('unavailable')
      expect(api.postPushSubscription).not.toHaveBeenCalled()
    })
  })

  describe('syncPushSubscription', () => {
    it('re-registers an existing subscription for the signed-in user', async () => {
      installPushEnv({ permission: 'granted', existing: fakeSubscription() })
      await expect(syncPushSubscription()).resolves.toBe(true)
      expect(api.postPushSubscription).toHaveBeenCalledTimes(1)
    })

    it('does nothing without a subscription', async () => {
      installPushEnv({ permission: 'granted' })
      await expect(syncPushSubscription()).resolves.toBe(false)
      expect(api.postPushSubscription).not.toHaveBeenCalled()
    })

    it('drops a subscription made with an old VAPID key instead of re-registering it', async () => {
      const stale = fakeSubscription()
      stale.options.applicationServerKey = urlBase64ToUint8Array('BOldVapidKey_-xyz').buffer
      installPushEnv({ permission: 'granted', existing: stale })
      await expect(syncPushSubscription()).resolves.toBe(false)
      expect(stale.unsubscribe).toHaveBeenCalledTimes(1)
      expect(api.postPushSubscription).not.toHaveBeenCalled()
    })

    it('keeps re-registering when the server key cannot be loaded', async () => {
      installPushEnv({ permission: 'granted', existing: fakeSubscription() })
      api.getVapidPublicKey.mockRejectedValue(new Error('offline'))
      await expect(syncPushSubscription()).resolves.toBe(true)
      expect(api.postPushSubscription).toHaveBeenCalledTimes(1)
    })
  })

  describe('revokePushSubscription (crit. 24)', () => {
    it('revokes on the server first, then in the browser', async () => {
      const subscription = fakeSubscription()
      installPushEnv({ permission: 'granted', existing: subscription })
      const order: string[] = []
      api.postPushUnsubscribe.mockImplementation(async () => {
        order.push('server')
      })
      subscription.unsubscribe.mockImplementation(async () => {
        order.push('browser')
        return true
      })
      await revokePushSubscription({ accessToken: 'tok' })
      expect(api.postPushUnsubscribe).toHaveBeenCalledWith('https://push.example/abc', { accessToken: 'tok' })
      expect(order).toEqual(['server', 'browser'])
    })

    it('still drops the browser subscription after a network error and never rejects', async () => {
      const subscription = fakeSubscription()
      installPushEnv({ permission: 'granted', existing: subscription })
      api.postPushUnsubscribe.mockRejectedValue(new TypeError('Failed to fetch'))
      await expect(revokePushSubscription()).resolves.toBeUndefined()
      expect(subscription.unsubscribe).toHaveBeenCalledTimes(1)
    })

    it('does nothing without a subscription', async () => {
      installPushEnv({ permission: 'granted' })
      await revokePushSubscription()
      expect(api.postPushUnsubscribe).not.toHaveBeenCalled()
    })
  })
})
