import { useSyncExternalStore } from 'react'
import { Grid } from 'antd'
import { isTelegramWebAppContext } from './pwa'

/** Below antd's `md` breakpoint (768 px): the same boundary as `!Grid.useBreakpoint().md`. */
export const PHONE_MEDIA_QUERY = '(max-width: 767.98px)'

/**
 * A touch-only screen whose short side is below 768 px: a phone turned to landscape. Without it a phone wider than
 * 768 px in landscape would switch to the desktop layout on rotation, remounting the page and losing what was typed.
 * Laptops with a touch screen keep a fine pointer with hover and are not matched.
 */
export const TOUCH_PHONE_LANDSCAPE_QUERY = '(hover: none) and (pointer: coarse) and (max-height: 767.98px)'

function getMediaQueryList(query: string): MediaQueryList | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null
  try {
    return window.matchMedia(query)
  } catch {
    return null
  }
}

function matchesMedia(query: string): boolean {
  return getMediaQueryList(query)?.matches ?? false
}

function subscribeTouchPhoneLandscape(onChange: () => void): () => void {
  const list = getMediaQueryList(TOUCH_PHONE_LANDSCAPE_QUERY)
  if (!list || typeof list.addEventListener !== 'function') return () => undefined
  list.addEventListener('change', onChange)
  return () => list.removeEventListener('change', onChange)
}

const readTouchPhoneLandscape = () => matchesMedia(TOUCH_PHONE_LANDSCAPE_QUERY)

/**
 * True on a phone: a screen narrower than 768 px, or a touch-only screen whose short side is below 768 px (so the
 * layout survives rotation). antd fills the breakpoints only after its first layout effect (the first render sees
 * `{}`), so until then the width is read synchronously: the first paint already shows the right branch.
 */
export function useIsPhone(): boolean {
  const screens = Grid.useBreakpoint()
  const touchPhoneLandscape = useSyncExternalStore(subscribeTouchPhoneLandscape, readTouchPhoneLandscape, () => false)
  if (touchPhoneLandscape) return true
  if (screens.md === undefined) return matchesMedia(PHONE_MEDIA_QUERY)
  return !screens.md
}

/**
 * The one place that decides whether the portal renders its mobile layout. The Telegram Mini App keeps its own
 * markup at any width: `variant="telegram"` and every page under /tg/ (or with Telegram initData) never turn it on.
 */
export function usePortalMobileMode(variant: 'portal' | 'telegram' = 'portal'): boolean {
  // Called unconditionally: the hook order must not depend on the variant.
  const isPhone = useIsPhone()
  if (variant === 'telegram') return false
  if (isTelegramWebAppContext()) return false
  return isPhone
}
