import React, { createContext, useContext, useMemo, useState } from 'react'

type Tokens = {
  access: string
  refresh: string
}

type AuthState = Tokens & {
  username: string
}

type AuthContextValue = {
  accessToken: string | null
  refreshToken: string | null
  username: string | null
  login: (payload: { tokens: Tokens; username: string }) => void
  logout: () => void
}

const STORAGE_KEY = 'kolberg_v2_tokens'

function loadState(): AuthState | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<AuthState>
    if (!parsed.access || !parsed.refresh || !parsed.username) return null
    return { access: parsed.access, refresh: parsed.refresh, username: parsed.username }
  } catch {
    return null
  }
}

function saveState(state: AuthState | null) {
  if (!state) {
    localStorage.removeItem(STORAGE_KEY)
    return
  }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const initial = loadState()
  const [state, setState] = useState<AuthState | null>(initial)

  const value = useMemo<AuthContextValue>(
    () => ({
      accessToken: state?.access ?? null,
      refreshToken: state?.refresh ?? null,
      username: state?.username ?? null,
      login: ({ tokens, username }) => {
        const next: AuthState = { ...tokens, username }
        setState(next)
        saveState(next)
      },
      logout: () => {
        setState(null)
        saveState(null)
      },
    }),
    [state],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

