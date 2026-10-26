import { useEffect, useState } from 'react'

import { getProjectInvestmentsBySourceRequest } from '../../lib/api'
import { CASH_REGISTER_TRANSFER_PAYMENT_PURPOSE, CASH_REGISTER_TRANSFER_PAYMENT_TYPE } from '../../lib/cashRegisterTransfer'
import { isInvestPaymentType } from '../../lib/requestPaymentTypes'

type RequestLike = { id: number; payment_type?: string | null; payment_purpose?: string | null }

export function canBeInvestmentSource(detail: RequestLike | null | undefined): boolean {
  if (!detail) return false
  const type = detail.payment_type || ''
  if (isInvestPaymentType(type)) return true
  return (
    type === CASH_REGISTER_TRANSFER_PAYMENT_TYPE &&
    (detail.payment_purpose || '').trim() === CASH_REGISTER_TRANSFER_PAYMENT_PURPOSE
  )
}

/** Номера вложений, в которые вошла заявка; при ошибке или для прочих заявок — пустой список. */
export function useRequestInvestmentIds(detail: RequestLike | null | undefined): number[] {
  const [ids, setIds] = useState<number[]>([])
  const requestId = detail?.id ?? null
  const eligible = canBeInvestmentSource(detail)
  useEffect(() => {
    if (requestId == null || !eligible) {
      setIds([])
      return
    }
    let cancelled = false
    getProjectInvestmentsBySourceRequest(requestId)
      .then((rows) => {
        if (!cancelled) setIds(rows.map((r) => r.id))
      })
      .catch(() => {
        if (!cancelled) setIds([])
      })
    return () => {
      cancelled = true
    }
  }, [requestId, eligible])
  return ids
}
