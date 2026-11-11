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
  if (installListenersAttached && typeof window !== 'undefined') {
    window.removeEventListener('beforeinstallprompt', onBeforeInstallPrompt)
    window.removeEventListener('appinstalled', onAppInstalled)
  }
  installListenersAttached = false
  deferredInstallPrompt = null
  installPromptListeners.clear()
  installPromptDismissedInMemory = false
}

// --- «Установить приложение» -------------------------------------------------------------------------------------

/** Chromium's install prompt event (Android Chrome, desktop Chrome/Edge); not in the DOM typings. */
type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform?: string }>
}

export type InstallPromptOutcome = 'accepted' | 'dismissed' | 'unavailable'

/** Set to "1" once the viewer closed the install hint: it is not shown on this device again. */
export const INSTALL_PROMPT_DISMISSED_KEY = 'kolberg_v2_install_prompt_dismissed'

let deferredInstallPrompt: BeforeInstallPromptEvent | null = null
let installListenersAttached = false
const installPromptListeners = new Set<() => void>()
/** Storage refused the flag: the hint still stays closed until the page reloads. */
let installPromptDismissedInMemory = false

function notifyInstallPrompt() {
  installPromptListeners.forEach((listener) => listener())
}

function onBeforeInstallPrompt(event: Event) {
  // Keep the browser's own mini-infobar away: the portal offers the install from its banner.
  event.preventDefault()
  deferredInstallPrompt = event as BeforeInstallPromptEvent
  notifyInstallPrompt()
}

function onAppInstalled() {
  deferredInstallPrompt = null
  notifyInstallPrompt()
}

/**
 * Starts listening for the browser's install prompt. Call it once at startup, before the first render: Chrome fires
 * `beforeinstallprompt` early. Repeated calls do nothing; inside the Telegram Mini App nothing is attached.
 */
export function captureInstallPrompt(): void {
  if (installListenersAttached) return
  if (typeof window === 'undefined') return
  if (isTelegramWebAppContext()) return
  window.addEventListener('beforeinstallprompt', onBeforeInstallPrompt)
  window.addEventListener('appinstalled', onAppInstalled)
  installListenersAttached = true
}

/** The browser handed over an install prompt that has not been used yet. */
export function canPromptInstall(): boolean {
  return deferredInstallPrompt !== null
}

export function subscribeInstallPrompt(listener: () => void): () => void {
  installPromptListeners.add(listener)
  return () => {
    installPromptListeners.delete(listener)
  }
}

/** Shows the browser's install dialog. A prompt can be used once, so it is forgotten whatever the answer. */
export async function promptInstall(): Promise<InstallPromptOutcome> {
  const event = deferredInstallPrompt
  if (!event) return 'unavailable'
  deferredInstallPrompt = null
  notifyInstallPrompt()
  try {
    await event.prompt()
    const choice = await event.userChoice
    return choice?.outcome === 'accepted' ? 'accepted' : 'dismissed'
  } catch (e) {
    console.warn('Install prompt failed', e)
    return 'dismissed'
  }
}

/** The portal runs as an installed app (home screen icon), not in a browser tab. */
export function isStandaloneDisplay(): boolean {
  if (typeof window === 'undefined') return false
  try {
    if (typeof window.matchMedia === 'function' && window.matchMedia('(display-mode: standalone)').matches) return true
  } catch {
    // An old browser without display-mode support: fall through to the iOS flag.
  }
  return (navigator as Navigator & { standalone?: boolean }).standalone === true
}

/**
 * iPhone or iPad browser (Safari and the other iOS browsers, which install through «Поделиться → На экран Домой»).
 * iPadOS reports itself as a Mac: it is told apart by touch support.
 */
export function isIosSafari(userAgent?: string, maxTouchPoints?: number): boolean {
  if (typeof navigator === 'undefined' && userAgent === undefined) return false
  const ua = userAgent ?? navigator.userAgent ?? ''
  if (/iPhone|iPad|iPod/i.test(ua)) return true
  const touchPoints = maxTouchPoints ?? (typeof navigator !== 'undefined' ? navigator.maxTouchPoints : 0)
  return /Macintosh/i.test(ua) && (touchPoints ?? 0) > 1
}

export function isInstallPromptDismissed(): boolean {
  if (installPromptDismissedInMemory) return true
  try {
    return window.localStorage.getItem(INSTALL_PROMPT_DISMISSED_KEY) === '1'
  } catch (e) {
    console.warn('Install prompt flag is unavailable', e)
    return false
  }
}

export function dismissInstallPrompt(): void {
  installPromptDismissedInMemory = true
  try {
    window.localStorage.setItem(INSTALL_PROMPT_DISMISSED_KEY, '1')
  } catch (e) {
    console.warn('Install prompt flag was not saved', e)
  }
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
