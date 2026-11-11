import { getVapidPublicKey, postPushSubscription, postPushUnsubscribe, type PushSubscriptionPayload } from './pushApi'
import { getSharedHost, isSharedAppMode } from './portalMode'
import { SW_SCOPE, isTelegramWebAppContext } from './pwa'

/**
 * Web Push in the browser: whether the device can get "action required" notifications, enabling them by a click and
 * revoking them on logout.
 *
 * Subscriptions live only on the shared app host (app.kolberg.uz): one subscription per device brings notifications of
 * all the user's companies. On a company subdomain the page points to the shared host instead of a button.
 * Permission is asked only from a click (enablePush), never on page load.
 */

export type PushSupport =
  /** No service worker, PushManager or Notification in this browser. */
  | 'unsupported'
  /** Telegram Mini App: no push there. */
  | 'telegram'
  /** Company subdomain while the shared app host exists: subscribe there. */
  | 'subdomain-use-shared-host'
  /** iPhone or iPad outside the installed app: push works only from the Home Screen (iOS 16.4+). */
  | 'ios-needs-install'
  /** Web Push is off on the server (no VAPID keys, no shared host) or its state could not be read. */
  | 'disabled-server'
  /** The user blocked notifications for this site. */
  | 'denied'
  /** Not asked yet: the button can ask. */
  | 'default'
  /** Notifications are allowed (a subscription may or may not exist). */
  | 'granted'

export type EnablePushResult = 'subscribed' | 'denied' | 'default' | 'unavailable' | 'error'

let vapidKeyPromise: Promise<string | null> | null = null

/** Public VAPID key, asked once per page; null when push is off on the server. A failed request is retried later. */
function loadVapidKey(): Promise<string | null> {
  if (!vapidKeyPromise) {
    vapidKeyPromise = getVapidPublicKey()
      .then((data) => (data.enabled ? data.public_key : null))
      .catch((error: unknown) => {
        vapidKeyPromise = null
        throw error
      })
  }
  return vapidKeyPromise
}

/** Test-only reset of the cached server key. */
export function resetWebPushStateForTests(): void {
  vapidKeyPromise = null
}

type IosNavigator = Navigator & { standalone?: boolean }

export function isIosDevice(): boolean {
  if (typeof navigator === 'undefined') return false
  const ua = navigator.userAgent || ''
  if (/iPad|iPhone|iPod/.test(ua)) return true
  // iPadOS reports itself as a Mac; touch points tell them apart.
  return navigator.platform === 'MacIntel' && (navigator.maxTouchPoints ?? 0) > 1
}

export function isStandaloneDisplay(): boolean {
  if (typeof window === 'undefined') return false
  if ((navigator as IosNavigator).standalone === true) return true
  try {
    return Boolean(window.matchMedia?.('(display-mode: standalone)').matches)
  } catch {
    return false
  }
}

function hasPushApis(): boolean {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return false
  return Boolean(navigator.serviceWorker) && 'PushManager' in window && 'Notification' in window
}

function notificationPermission(): NotificationPermission {
  try {
    return Notification.permission
  } catch {
    return 'default'
  }
}

/** What the notifications page can offer on this device. Never rejects. */
export async function getPushSupport(): Promise<PushSupport> {
  if (isTelegramWebAppContext()) return 'telegram'
  if (!isSharedAppMode()) return getSharedHost() ? 'subdomain-use-shared-host' : 'disabled-server'
  if (isIosDevice() && !isStandaloneDisplay()) return 'ios-needs-install'
  if (!hasPushApis()) return 'unsupported'
  try {
    if (!(await loadVapidKey())) return 'disabled-server'
  } catch {
    return 'disabled-server'
  }
  const permission = notificationPermission()
  if (permission === 'denied' || permission === 'granted') return permission
  return 'default'
}

async function portalRegistration(): Promise<ServiceWorkerRegistration | null> {
  if (!hasPushApis()) return null
  try {
    const registration = await navigator.serviceWorker.getRegistration(SW_SCOPE)
    if (!registration) return null
    if (registration.active) return registration
    // Installed but not active yet (first visit): pushManager.subscribe needs an active worker.
    return await navigator.serviceWorker.ready
  } catch {
    return null
  }
}

/** The browser's push subscription of the portal worker, or null. Never rejects. */
export async function getCurrentPushSubscription(): Promise<PushSubscription | null> {
  const registration = await portalRegistration()
  if (!registration?.pushManager) return null
  try {
    return await registration.pushManager.getSubscription()
  } catch {
    return null
  }
}

export function urlBase64ToUint8Array(value: string): Uint8Array<ArrayBuffer> {
  const padded = value + '='.repeat((4 - (value.length % 4)) % 4)
  const raw = atob(padded.replace(/-/g, '+').replace(/_/g, '/'))
  const bytes = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i)
  return bytes
}

function sameKey(subscription: PushSubscription, key: Uint8Array): boolean {
  const current = subscription.options?.applicationServerKey
  if (!current) return true
  const bytes = new Uint8Array(current)
  return bytes.length === key.length && bytes.every((byte, i) => byte === key[i])
}

function toPayload(subscription: PushSubscription): PushSubscriptionPayload | null {
  const json = subscription.toJSON()
  const endpoint = json.endpoint ?? subscription.endpoint
  const p256dh = json.keys?.p256dh
  const auth = json.keys?.auth
  if (!endpoint || !p256dh || !auth) return null
  return { endpoint, keys: { p256dh, auth } }
}

async function askPermission(): Promise<NotificationPermission> {
  const current = notificationPermission()
  if (current !== 'default') return current
  try {
    return await Notification.requestPermission()
  } catch {
    return notificationPermission()
  }
}

/**
 * Asks for permission (only call it from a click), subscribes the device and registers it on the server.
 * Never rejects: the result says what happened.
 */
export async function enablePush(): Promise<EnablePushResult> {
  if (!isSharedAppMode() || isTelegramWebAppContext() || !hasPushApis()) return 'unavailable'
  // First thing in the click handler: Safari grants the prompt only to a user gesture.
  const permission = await askPermission()
  if (permission !== 'granted') return permission

  let key: string | null
  try {
    key = await loadVapidKey()
  } catch {
    return 'error'
  }
  if (!key) return 'unavailable'
  const registration = await portalRegistration()
  if (!registration?.pushManager) return 'unavailable'

  try {
    const serverKey = urlBase64ToUint8Array(key)
    let subscription = await registration.pushManager.getSubscription()
    if (subscription && !sameKey(subscription, serverKey)) {
      // The server key was rotated: the old subscription can no longer be used.
      await subscription.unsubscribe().catch(() => false)
      subscription = null
    }
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: serverKey })
    }
    const payload = toPayload(subscription)
    if (!payload) return 'error'
    await postPushSubscription(payload)
    return 'subscribed'
  } catch {
    return 'error'
  }
}

/**
 * Re-registers an existing browser subscription for the signed-in user (another user may have signed in on this device
 * after a logout that could not reach the server). Returns whether the device has a subscription. Never rejects.
 */
export async function syncPushSubscription(): Promise<boolean> {
  const subscription = await getCurrentPushSubscription()
  if (!subscription) return false
  // After a VAPID key rotation the old subscription can never be delivered: drop it instead of re-registering,
  // so the page offers "Включить" again rather than claiming notifications are on.
  let key: string | null = null
  try {
    key = await loadVapidKey()
  } catch {
    key = null
  }
  if (key && !sameKey(subscription, urlBase64ToUint8Array(key))) {
    await subscription.unsubscribe().catch(() => false)
    return false
  }
  const payload = toPayload(subscription)
  if (payload) await postPushSubscription(payload).catch(() => undefined)
  return true
}

type RevokeOptions = {
  /** Token captured before logout cleared the stored tokens. */
  accessToken?: string | null
}

/**
 * Revokes the device subscription: first on the server (while the token still works), then in the browser.
 * Never rejects; errors are swallowed so logout always completes.
 */
export async function revokePushSubscription(options: RevokeOptions = {}): Promise<void> {
  try {
    if (isTelegramWebAppContext()) return
    const subscription = await getCurrentPushSubscription()
    if (!subscription) return
    try {
      await postPushUnsubscribe(subscription.endpoint, { accessToken: options.accessToken })
    } catch {
      // Server unreachable or token expired: the browser subscription is still dropped below.
    }
    try {
      await subscription.unsubscribe()
    } catch {
      // Nothing more to do.
    }
  } catch {
    // Never break logout.
  }
}
