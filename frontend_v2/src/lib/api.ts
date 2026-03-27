type Tokens = { access: string; refresh: string }

const STORAGE_KEY = 'kolberg_v2_tokens'

function getTokens(): Tokens | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Tokens>
    if (!parsed.access || !parsed.refresh) return null
    return { access: parsed.access, refresh: parsed.refresh }
  } catch {
    return null
  }
}

function setTokens(tokens: Tokens | null) {
  if (!tokens) {
    localStorage.removeItem(STORAGE_KEY)
    return
  }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(tokens))
}

async function refreshAccess(refresh: string): Promise<string | null> {
  const res = await fetch('/api/auth/token/refresh/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh }),
  })
  if (!res.ok) return null
  const data = (await res.json()) as { access?: string }
  return data.access ?? null
}

export async function apiFetch(input: string, init: RequestInit = {}) {
  const tokens = getTokens()
  const headers = new Headers(init.headers || {})
  headers.set('Accept', 'application/json')
  if (tokens?.access) headers.set('Authorization', `Bearer ${tokens.access}`)

  const doFetch = () =>
    fetch(input, {
      ...init,
      headers,
    })

  let res = await doFetch()

  // try refresh once
  if (res.status === 401 && tokens?.refresh) {
    const newAccess = await refreshAccess(tokens.refresh)
    if (newAccess) {
      setTokens({ access: newAccess, refresh: tokens.refresh })
      headers.set('Authorization', `Bearer ${newAccess}`)
      res = await doFetch()
    } else {
      setTokens(null)
    }
  }

  return res
}

