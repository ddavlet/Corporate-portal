/**
 * Installable-app support for the portal: service worker registration and the "new version is ready" flag.
 *
 * The worker (public/sw.js) caches nothing; it only makes the portal installable. Inside the Telegram Mini App
 * (/app/tg/ or a non-empty Telegram initData) nothing is registered, so the Mini App behaves as before.
 */

export const SW_URL = '/app/sw.js'
export const SW_SCOPE = '/app/'

/** True inside the Telegram Mini App: its routes live under /tg/ and Telegram passes initData. */
export function isTelegramWebAppContext(): boolean {
  if (typeof window === 'undefined') return false
  if (window.location.pathname.includes('/tg/')) return true
  return Boolean(window.Telegram?.WebApp?.initData?.trim())
}

let updateReady = false
const updateListeners = new Set<() => void>()

/** A newer service worker took over this page: the next route change should reload into the fresh build. */
export function isPwaUpdateReady(): boolean {
  return updateReady
}

export function subscribePwaUpdate(listener: () => void): () => void {
  updateListeners.add(listener)
  return () => {
    updateListeners.delete(listener)
  }
}

function markUpdateReady() {
  if (updateReady) return
  updateReady = true
  updateListeners.forEach((listener) => listener())
}

/** Test-only reset of the module state. */
export function resetPwaStateForTests(): void {
  updateReady = false
  updateListeners.clear()
}

type RegisterOptions = {
  /** Vite dev server: no worker, so stale builds never get in the way of HMR. */
  isDev?: boolean
}

/**
 * Registers the portal service worker and keeps it fresh: the browser is asked to look for a new sw.js whenever
 * the window gets focus or becomes visible. Returns the registration, or null when the worker is not used here.
 */
export async function registerPortalServiceWorker(
  options: RegisterOptions = {},
): Promise<ServiceWorkerRegistration | null> {
  const isDev = options.isDev ?? import.meta.env.DEV
  if (isDev) return null
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return null
  if (isTelegramWebAppContext()) return null
  if (!('serviceWorker' in navigator) || !navigator.serviceWorker) return null

  const container = navigator.serviceWorker
  // On the very first install there is no controller yet: clients.claim() then is not an update.
  let hadController = Boolean(container.controller)
  container.addEventListener('controllerchange', () => {
    if (hadController) markUpdateReady()
    hadController = true
  })

  let registration: ServiceWorkerRegistration
  try {
    registration = await container.register(SW_URL, { scope: SW_SCOPE })
  } catch (e) {
    console.warn('Service worker registration failed', e)
    return null
  }

  const checkForUpdate = () => {
    registration.update().catch(() => undefined)
  }
  window.addEventListener('focus', checkForUpdate)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') checkForUpdate()
  })

  return registration
}
