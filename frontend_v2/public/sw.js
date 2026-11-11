/*
 * Kolberg portal service worker (scope /app/).
 *
 * It exists so the portal can be installed as an app. It stores nothing: the Cache Storage API is not used,
 * /api/* and other origins are never intercepted, and page navigations under /app/ go straight to the
 * network. The Telegram Mini App (/app/tg/) is left alone entirely.
 *
 * Web Push ("action required"): every push shows a notification (browsers require a visible one), tagged with the
 * object (`<company>:<kind>-<id>`), then closes notifications whose tag is no longer in `active_tags` and puts `count`
 * on the app icon. There is no "close" push: a closed step disappears on the next push or when the open portal posts
 * the current tags (message 'action-items').
 */

const APP_PREFIX = '/app/'
const FALLBACK_URL = '/app/notifications'
const NOTIFICATION_ICON = '/app/icons/icon-192.png'

self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.mode !== 'navigate') return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return
  if (!url.pathname.startsWith('/app/') && url.pathname !== '/app') return
  if (url.pathname.startsWith('/app/tg/') || url.pathname === '/app/tg') return
  event.respondWith(fetch(req))
})

function isAppPath(pathname) {
  if (!pathname.startsWith(APP_PREFIX)) return false
  return !pathname.startsWith('/app/tg/')
}

/** Absolute URL of a portal page on this origin; anything else falls back to the notifications page. */
function safeAppUrl(raw) {
  try {
    const url = new URL(typeof raw === 'string' && raw ? raw : FALLBACK_URL, self.location.origin)
    if (url.origin === self.location.origin && isAppPath(url.pathname)) return url.href
  } catch (e) {
    // Malformed URL in the payload: open the notifications page.
  }
  return new URL(FALLBACK_URL, self.location.origin).href
}

function readPushData(event) {
  try {
    const data = event.data ? event.data.json() : null
    return data && typeof data === 'object' ? data : {}
  } catch (e) {
    return {}
  }
}

async function updateBadge(count) {
  const nav = self.navigator
  if (!nav) return
  try {
    if (typeof count === 'number' && count > 0) {
      if (typeof nav.setAppBadge === 'function') await nav.setAppBadge(count)
    } else if (typeof nav.clearAppBadge === 'function') {
      await nav.clearAppBadge()
    }
  } catch (e) {
    // Badging is optional (not installed, unsupported platform).
  }
}

/** Closes shown notifications whose tag is not active any more. `activeTags` must be an array. */
async function closeStaleNotifications(activeTags) {
  if (!self.registration || typeof self.registration.getNotifications !== 'function') return
  const active = new Set(activeTags.filter((tag) => typeof tag === 'string'))
  const shown = await self.registration.getNotifications()
  shown.forEach((notification) => {
    if (notification.tag && !active.has(notification.tag)) notification.close()
  })
}

async function handlePush(event) {
  const data = readPushData(event)
  const tag = typeof data.tag === 'string' && data.tag ? data.tag : undefined
  const title = typeof data.title === 'string' && data.title ? data.title : 'Kolberg'
  await self.registration.showNotification(title, {
    body: typeof data.body === 'string' ? data.body : '',
    tag,
    icon: NOTIFICATION_ICON,
    data: { url: safeAppUrl(data.url) },
  })
  // A payload too large for the push service comes without active_tags (null): then nothing is closed.
  if (Array.isArray(data.active_tags)) {
    try {
      await closeStaleNotifications(tag ? [...data.active_tags, tag] : data.active_tags)
    } catch (e) {
      // Closing stale notifications is best effort.
    }
  }
  await updateBadge(data.count)
}

self.addEventListener('push', (event) => {
  event.waitUntil(handlePush(event))
})

async function openFromNotification(rawUrl) {
  const url = safeAppUrl(rawUrl)
  const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
  const client = windows.find((c) => {
    try {
      const u = new URL(c.url)
      return u.origin === self.location.origin && isAppPath(u.pathname)
    } catch (e) {
      return false
    }
  })
  if (client) {
    try {
      const focused = await client.focus()
      const target = focused || client
      if (typeof target.navigate === 'function') {
        await target.navigate(url)
        return
      }
    } catch (e) {
      // An uncontrolled window cannot be navigated from here: open a new one.
    }
  }
  if (self.clients.openWindow) await self.clients.openWindow(url)
}

self.addEventListener('notificationclick', (event) => {
  const data = (event.notification && event.notification.data) || {}
  event.notification.close()
  event.waitUntil(openFromNotification(data.url))
})

self.addEventListener('message', (event) => {
  const data = event.data
  if (!data || data.type !== 'action-items' || !Array.isArray(data.tags)) return
  const work = Promise.all([closeStaleNotifications(data.tags).catch(() => undefined), updateBadge(data.count)])
  if (typeof event.waitUntil === 'function') event.waitUntil(work)
})
