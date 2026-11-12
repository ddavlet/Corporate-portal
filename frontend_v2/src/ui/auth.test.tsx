import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from './auth'

const { revokePushMock } = vi.hoisted(() => ({ revokePushMock: vi.fn(() => Promise.resolve()) }))
vi.mock('../lib/webPush', () => ({ revokePushSubscription: revokePushMock }))

function wrapper({ children }: { children: ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>
}

describe('AuthProvider logout', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    revokePushMock.mockClear()
  })

  it('revokes the push subscription with the token of the session being closed (crit. 24)', () => {
    localStorage.setItem('kolberg_v2_tokens', JSON.stringify({ access: 'a', refresh: 'r', username: 'ivan' }))
    let tokensAtRevoke: string | null = 'unset'
    revokePushMock.mockImplementation(() => {
      tokensAtRevoke = localStorage.getItem('kolberg_v2_tokens')
      return Promise.resolve()
    })
    const { result } = renderHook(() => useAuth(), { wrapper })

    act(() => result.current.logout())

    expect(revokePushMock).toHaveBeenCalledTimes(1)
    expect(revokePushMock).toHaveBeenCalledWith({ accessToken: 'a' })
    expect(tokensAtRevoke).not.toBeNull()
    expect(localStorage.getItem('kolberg_v2_tokens')).toBeNull()
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
