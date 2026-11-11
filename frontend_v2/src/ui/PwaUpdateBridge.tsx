import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { isPwaUpdateReady } from '../lib/pwa'

type Props = {
  /** Injected in tests; defaults to a full page reload. */
  reload?: () => void
}

/**
 * Picks up a new portal build without interrupting the user: once a newer service worker has taken over, the page
 * reloads on the next route change of a visible tab. Nothing is reloaded mid-screen, so an open form or modal is not
 * lost; list pages keep their filters in sessionStorage (useListPageSession) and survive the reload.
 */
export function PwaUpdateBridge({ reload }: Props) {
  const location = useLocation()
  const routeKey = `${location.pathname}${location.search}`
  const previousRoute = useRef(routeKey)

  useEffect(() => {
    if (previousRoute.current === routeKey) return
    previousRoute.current = routeKey
    if (!isPwaUpdateReady()) return
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
    if (reload) reload()
    else window.location.reload()
  }, [routeKey, reload])

  return null
}
