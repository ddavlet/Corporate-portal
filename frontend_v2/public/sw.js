/*
 * Kolberg portal service worker (scope /app/).
 *
 * It exists so the portal can be installed as an app. It stores nothing: the Cache Storage API is not used,
 * /api/* and other origins are never intercepted, and page navigations under /app/ go straight to the
 * network. The Telegram Mini App (/app/tg/) is left alone entirely.
 */

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
