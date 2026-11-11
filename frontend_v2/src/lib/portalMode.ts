/**
 * Portal mode: a tenant subdomain (acme.kolberg.uz) or the shared app host (app.kolberg.uz) where the company is
 * picked in the header and sent as `X-Tenant`.
 *
 * The mode comes from the server (`GET /api/portal/config/` → `{shared_host}`), not from the hostname alone, so
 * clearing PORTAL_SHARED_HOST on the backend also switches the SPA off. The answer is cached in localStorage:
 * - the Telegram Mini App (`/tg/`) never asks and always works as a subdomain;
 * - with a cached answer the app renders at once and asks again in the background; when the mode for this host has
 *   changed, the cache is updated and the page reloads;
 * - without a cache (first visit on this origin) the start waits at most PORTAL_CONFIG_WAIT_MS; a timeout or an error
 *   means subdomain mode (a late answer that turns the mode on still updates the cache and reloads).
 */

export const PORTAL_CONFIG_CACHE_KEY = 'kolberg_v2_portal_config'
export const PORTAL_CONFIG_URL = '/api/portal/config/'
export const PORTAL_CONFIG_WAIT_MS = 1500

type PortalConfig = { shared_host: string | null }

let sharedHost: string | null = null

function normalizeHost(host: string): string {
  return host.trim().toLowerCase().split(':')[0].replace(/\.$/, '')
}

function pathIsTgWebApp(): boolean {
  if (typeof window === 'undefined') return false
  return window.location.pathname.includes('/tg/')
}

function currentHost(): string {
  if (typeof window === 'undefined') return ''
  return normalizeHost(window.location.hostname || '')
}

function parseConfig(value: unknown): PortalConfig | null {
  if (!value || typeof value !== 'object') return null
  const raw = (value as { shared_host?: unknown }).shared_host
  if (raw === null || raw === undefined) return { shared_host: null }
  if (typeof raw !== 'string') return null
  const host = normalizeHost(raw)
  return { shared_host: host || null }
}

function readCache(): PortalConfig | null {
  try {
    const raw = localStorage.getItem(PORTAL_CONFIG_CACHE_KEY)
    if (!raw) return null
    return parseConfig(JSON.parse(raw))
  } catch {
    return null
  }
}

/** False when the answer could not be saved (no storage, private mode): the next start waits for the server again. */
function writeCache(config: PortalConfig): boolean {
  try {
    localStorage.setItem(PORTAL_CONFIG_CACHE_KEY, JSON.stringify(config))
    return true
  } catch {
    return false
  }
}

function isSharedFor(config: PortalConfig | null): boolean {
  return Boolean(config?.shared_host) && config?.shared_host === currentHost()
}

/** Public and tenantless: plain fetch, no apiFetch, no Authorization, no X-Tenant. */
async function fetchConfig(): Promise<PortalConfig> {
  const res = await fetch(PORTAL_CONFIG_URL, { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
  if (!res.ok) throw new Error(`portal config HTTP ${res.status}`)
  const config = parseConfig(await res.json())
  if (!config) throw new Error('portal config: bad payload')
  return config
}

function reloadPage(): void {
  try {
    window.location.reload()
  } catch {
    // jsdom and odd embeddings: the next start picks up the cached mode.
  }
}

/**
 * Applies a server answer that arrived after the app has rendered: keep the cache fresh and reload only when the
 * mode on this host flips (subdomain ↔ shared), since the whole tree depends on it. Without storage a reload would
 * find no cache, render in the old mode again and reload again, so the mode is then applied in memory only.
 */
function applyLateConfig(fresh: PortalConfig): void {
  const wasShared = isSharedAppMode()
  const saved = writeCache(fresh)
  if (saved && isSharedFor(fresh) !== wasShared) {
    reloadPage()
    return
  }
  sharedHost = fresh.shared_host
}

/** Resolves when the app may render. Never rejects. */
export function initPortalMode(): Promise<void> {
  sharedHost = null
  if (pathIsTgWebApp()) return Promise.resolve()

  const cached = readCache()
  if (cached) {
    sharedHost = cached.shared_host
    fetchConfig().then(applyLateConfig, () => undefined)
    return Promise.resolve()
  }

  return new Promise<void>((resolve) => {
    let settled = false
    const timer = setTimeout(() => {
      settled = true
      resolve()
    }, PORTAL_CONFIG_WAIT_MS)
    fetchConfig().then(
      (config) => {
        if (settled) {
          applyLateConfig(config)
          return
        }
        settled = true
        clearTimeout(timer)
        writeCache(config)
        sharedHost = config.shared_host
        resolve()
      },
      () => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        resolve()
      },
    )
  })
}

/** The shared app host from the server (e.g. "app.kolberg.uz"), or null when the mode is off. */
export function getSharedHost(): string | null {
  return sharedHost
}

/** True on the shared app host (outside the Mini App): the company comes from the switcher, not from the subdomain. */
export function isSharedAppMode(): boolean {
  if (pathIsTgWebApp()) return false
  return Boolean(sharedHost) && sharedHost === currentHost()
}

export function resetPortalModeForTests(): void {
  sharedHost = null
}
