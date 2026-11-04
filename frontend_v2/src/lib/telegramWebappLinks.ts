// Direct Link Mini App (t.me/<bot>/<app>) helpers. Mirror of backend requests/telegram_webapp_links.py.

const TME_HOSTS = ['t.me', 'www.t.me', 'telegram.me', 'www.telegram.me']

function parseUrl(url: string): URL | null {
  const u = url.trim()
  if (!u) return null
  try {
    return new URL(u.includes('://') ? u : `https://${u}`)
  } catch {
    return null
  }
}

/** Bot username from a t.me link ('' when the path is empty), null for non-t.me URLs. */
export function tmeBotUsername(url: string): string | null {
  const parsed = parseUrl(url)
  if (!parsed || !TME_HOSTS.includes(parsed.hostname.toLowerCase())) return null
  return parsed.pathname.replace(/^\/+/, '').split('/')[0].replace(/^@/, '')
}

export function tmeLinkPrefix(botUsername: string): string {
  return `https://t.me/${botUsername.replace(/^@/, '').trim()}/`
}

/** Bot named in a t.me link when it differs from the tenant's bot; null if it matches or can't be checked. */
export function tmeLinkForeignBot(url: string, tenantBotUsername: string): string | null {
  const tenantBot = tenantBotUsername.replace(/^@/, '').trim()
  const linkBot = tmeBotUsername(url)
  if (!tenantBot || !linkBot) return null
  return linkBot.toLowerCase() === tenantBot.toLowerCase() ? null : linkBot
}
