import { createContext, useContext, useLayoutEffect, useMemo, type ReactNode } from 'react'

export type UserIdStatus = 'loading' | 'ready' | 'missing'

/** What a page puts into the phone header: its title, a «Назад» target instead of «Меню», one action. */
export type MobileHeaderConfig = {
  title?: string
  /** Where «Назад» leads when there is no earlier page of the portal in the history (opened from a link). */
  back?: string
  action?: ReactNode
}

export type MobileHeaderStore = {
  get: () => MobileHeaderConfig | null
  set: (config: MobileHeaderConfig | null) => void
  subscribe: (listener: () => void) => () => void
}

/**
 * Header state lives outside React state of the shell: a page that sets it re-renders only the header bar, so a new
 * `action` element on every render of the page cannot loop.
 */
export function createMobileHeaderStore(): MobileHeaderStore {
  let config: MobileHeaderConfig | null = null
  const listeners = new Set<() => void>()
  return {
    get: () => config,
    set: (next) => {
      config = next
      listeners.forEach((listener) => listener())
    },
    subscribe: (listener) => {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
  }
}

export type MobileShellContextValue = {
  userId: number | null
  userIdStatus: UserIdStatus
  openCompanySwitcher: () => void
  headerStore: MobileHeaderStore | null
}

const OUTSIDE_MOBILE_SHELL: MobileShellContextValue = {
  userId: null,
  userIdStatus: 'missing',
  openCompanySwitcher: () => undefined,
  headerStore: null,
}

export const MobileShellContext = createContext<MobileShellContextValue>(OUTSIDE_MOBILE_SHELL)

/**
 * The signed-in user's id (from /api/settings-access/) and the company switcher of the phone shell. Outside the phone
 * shell: no id (`missing`) and a switcher call that does nothing.
 */
export function useMobileShell(): Pick<MobileShellContextValue, 'userId' | 'userIdStatus' | 'openCompanySwitcher'> {
  const { userId, userIdStatus, openCompanySwitcher } = useContext(MobileShellContext)
  return useMemo(() => ({ userId, userIdStatus, openCompanySwitcher }), [userId, userIdStatus, openCompanySwitcher])
}

/** Sets the phone header while the calling page is mounted; outside the phone shell it does nothing. */
export function useMobileHeader({ title, back, action }: MobileHeaderConfig): void {
  const { headerStore } = useContext(MobileShellContext)
  useLayoutEffect(() => {
    headerStore?.set({ title, back, action })
  }, [headerStore, title, back, action])
  useLayoutEffect(
    () => () => {
      headerStore?.set(null)
    },
    [headerStore],
  )
}
