import { getTelegramWebAppStartParam } from './tgPaymentApprovalId'

/** Parses request ID from start_param `req_<id>` or query `?request_id=`. */
export function resolveCommentRequestId(searchParams: URLSearchParams): number {
  const fromQuery = Number(searchParams.get('request_id') || 0)
  if (Number.isInteger(fromQuery) && fromQuery > 0) return fromQuery

  const sp = getTelegramWebAppStartParam()
  if (!sp) return 0

  const prefixed = /^req[_-]?(\d+)$/i.exec(sp)
  if (prefixed) {
    const n = Number(prefixed[1])
    if (Number.isInteger(n) && n > 0) return n
  }

  if (/^\d+$/.test(sp)) {
    const n = Number(sp)
    if (Number.isInteger(n) && n > 0) return n
  }

  return 0
}
