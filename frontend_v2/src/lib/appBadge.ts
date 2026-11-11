import { isTelegramWebAppContext } from './pwa'

/**
 * Badging API wrapper: the number on the installed app's icon (desktop Chrome/Edge show the number, Android a dot).
 * Unsupported browsers, rejected calls and the Telegram Mini App are silently ignored.
 */

type BadgingNavigator = Navigator & {
  setAppBadge?: (contents?: number) => Promise<void>
  clearAppBadge?: () => Promise<void>
}

function badgingNavigator(): BadgingNavigator | null {
  if (typeof navigator === 'undefined') return null
  if (isTelegramWebAppContext()) return null
  return navigator as BadgingNavigator
}

function swallow(call: () => Promise<void> | undefined): void {
  try {
    const result = call()
    if (result && typeof result.catch === 'function') result.catch(() => undefined)
  } catch {
    // Some browsers throw synchronously (e.g. not installed / insecure context).
  }
}

export function clearAppBadgeSafe(): void {
  const nav = badgingNavigator()
  if (!nav || typeof nav.clearAppBadge !== 'function') return
  swallow(() => nav.clearAppBadge?.())
}

export function syncAppBadge(count: number): void {
  const nav = badgingNavigator()
  if (!nav) return
  if (!count || count <= 0) {
    clearAppBadgeSafe()
    return
  }
  if (typeof nav.setAppBadge !== 'function') return
  swallow(() => nav.setAppBadge?.(count))
}
