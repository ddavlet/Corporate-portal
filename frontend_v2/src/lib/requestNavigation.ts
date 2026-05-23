/** Куда вернуться после перехода из карточки заявки в связанный документ/справочник. */
export type RequestReturnTo = {
  pathname: string
  label: string
}

export function requestReturnState(returnTo: RequestReturnTo): { returnTo: RequestReturnTo } {
  return { returnTo }
}

export function readRequestReturnTo(state: unknown): RequestReturnTo | null {
  if (!state || typeof state !== 'object') return null
  const returnTo = (state as { returnTo?: unknown }).returnTo
  if (!returnTo || typeof returnTo !== 'object') return null
  const pathname = (returnTo as RequestReturnTo).pathname
  const label = (returnTo as RequestReturnTo).label
  if (typeof pathname !== 'string' || !pathname.trim()) return null
  if (typeof label !== 'string' || !label.trim()) return null
  return { pathname, label }
}

export function requestReturnToForDetail(
  requestId: number,
  options?: { telegram?: boolean; fromList?: boolean },
): RequestReturnTo {
  if (options?.fromList) {
    return options.telegram
      ? { pathname: '/tg/requests', label: 'Заявки' }
      : { pathname: '/requests', label: 'Заявки' }
  }
  return options?.telegram
    ? { pathname: `/tg/requests/${requestId}`, label: `Заявка #${requestId}` }
    : { pathname: `/requests/${requestId}`, label: `Заявка #${requestId}` }
}

export const REQUEST_FORM_CONFIG_PATH = '/settings/request-form-config'
export const REQUEST_USERS_SETTINGS_PATH = '/settings/users-roles'
export const REQUEST_CONTRACTS_PATH = '/contracts'
export const REQUEST_ADMIN_VENDORS_PATH = '/admin'
