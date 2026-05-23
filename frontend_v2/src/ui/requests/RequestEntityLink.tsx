import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  REQUEST_ADMIN_VENDORS_PATH,
  REQUEST_CONTRACTS_PATH,
  REQUEST_FORM_CONFIG_PATH,
  REQUEST_USERS_SETTINGS_PATH,
  requestReturnState,
  type RequestReturnTo,
} from '../../lib/requestNavigation'

type RequestEntityLinkProps = {
  to: string
  returnTo?: RequestReturnTo
  children: ReactNode
}

type RequestDetailFieldValueProps = {
  variant?: 'default' | 'telegram'
  to?: string
  returnTo?: RequestReturnTo
  children: ReactNode
}

/** В Telegram WebApp — только текст; в портале — ссылка на связанный раздел. */
export function RequestDetailFieldValue({
  variant = 'default',
  to,
  returnTo,
  children,
}: RequestDetailFieldValueProps) {
  if (variant === 'telegram' || !to) {
    return <>{children}</>
  }
  return (
    <RequestEntityLink to={to} returnTo={returnTo}>
      {children}
    </RequestEntityLink>
  )
}

export function RequestEntityLink({ to, returnTo, children }: RequestEntityLinkProps) {
  return (
    <Link
      to={to}
      state={returnTo ? requestReturnState(returnTo) : undefined}
      style={{ color: 'var(--ant-color-link)' }}
    >
      {children}
    </Link>
  )
}

export function usersSettingsPath(userId?: number | null): string {
  if (userId == null) return REQUEST_USERS_SETTINGS_PATH
  return `${REQUEST_USERS_SETTINGS_PATH}?user=${userId}`
}

export function contractsPath(options?: { vendorId?: number | null; contractId?: number | null }): string {
  const params = new URLSearchParams()
  if (options?.vendorId != null) params.set('vendor', String(options.vendorId))
  if (options?.contractId != null) params.set('contract', String(options.contractId))
  const q = params.toString()
  return q ? `${REQUEST_CONTRACTS_PATH}?${q}` : REQUEST_CONTRACTS_PATH
}

export function vendorDirectoryPath(vendorRefId?: number | null): string {
  if (vendorRefId == null) return REQUEST_ADMIN_VENDORS_PATH
  return `${REQUEST_ADMIN_VENDORS_PATH}?source=vendors&row=${vendorRefId}`
}

export { REQUEST_FORM_CONFIG_PATH }
