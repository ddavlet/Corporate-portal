/**
 * approval_id для страницы выплаты в Mini App:
 * — query `?approval_id=` (кнопка web_app с полным URL);
 * — `start_param` / GET `tgWebAppStartParam` при открытии через Direct Link / main app: `?startapp=<id>` (см. Telegram Mini Apps).
 */
export function getTelegramWebAppStartParam(): string {
  if (typeof window === 'undefined') return ''
  const tw = window.Telegram?.WebApp
  const fromUnsafe = tw?.initDataUnsafe?.start_param
  if (typeof fromUnsafe === 'string' && fromUnsafe.trim()) return fromUnsafe.trim()

  const rawInit = (tw?.initData ?? '').trim()
  if (rawInit) {
    try {
      const fromSigned = new URLSearchParams(rawInit).get('start_param')
      if (typeof fromSigned === 'string' && fromSigned.trim()) return fromSigned.trim()
    } catch {
      /* ignore malformed initData */
    }
  }

  return new URLSearchParams(window.location.search).get('tgWebAppStartParam')?.trim() || ''
}

/** Разбор ID одобрения: сначала `approval_id`, иначе числовой или `approval_<id>` из start_param. */
export function resolvePaymentApprovalId(searchParams: URLSearchParams): number {
  const fromQuery = Number(searchParams.get('approval_id') || 0)
  if (Number.isInteger(fromQuery) && fromQuery > 0) return fromQuery

  const sp = getTelegramWebAppStartParam()
  if (!sp) return 0

  if (/^\d+$/.test(sp)) {
    const n = Number(sp)
    if (Number.isInteger(n) && n > 0) return n
  }

  const prefixed = /^approval[_-]?(\d+)$/i.exec(sp)
  if (prefixed) {
    const n = Number(prefixed[1])
    if (Number.isInteger(n) && n > 0) return n
  }

  return 0
}
