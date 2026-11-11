import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'
import { AuthProvider, useAuth } from './auth'

function wrapper({ children }: { children: ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>
}

describe('AuthProvider logout', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  it('forgets the company of this tab and keeps the device default', () => {
    localStorage.setItem('kolberg_v2_tokens', JSON.stringify({ access: 'a', refresh: 'r', username: 'ivan' }))
    sessionStorage.setItem('kolberg_v2_company', 'acme')
    localStorage.setItem('kolberg_v2_company_default', 'acme')

    const { result } = renderHook(() => useAuth(), { wrapper })
    expect(result.current.accessToken).toBe('a')

    act(() => result.current.logout())

    expect(result.current.accessToken).toBeNull()
    expect(sessionStorage.getItem('kolberg_v2_company')).toBeNull()
    expect(localStorage.getItem('kolberg_v2_company_default')).toBe('acme')
    expect(localStorage.getItem('kolberg_v2_tokens')).toBeNull()
  })
})
