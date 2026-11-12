import { useEffect, useState } from 'react'

import { getInvestmentFundingConfig } from './api'

export type InvestmentFundingModeStatus = {
  /** The tenant's config is still being requested. */
  loading: boolean
  /** The investment mode is on; false on an error or 403, as in useInvestmentFundingMode. */
  enabled: boolean
}

/**
 * Включён ли инвестиционный режим тенанта — вместе с признаком загрузки, для экранов, которые до ответа не должны
 * показывать ни одну из веток (useInvestmentFundingMode до ответа отдаёт false). `active=false` — конфиг не
 * запрашивается: `{ loading: false, enabled: false }`.
 */
export function useInvestmentFundingModeStatus(active: boolean = true): InvestmentFundingModeStatus {
  // The answer for the current activation; null until it comes. Kept apart from `active`, so the render in which
  // `active` turns true (before the effect runs) is already «loading», not «off».
  const [result, setResult] = useState<{ enabled: boolean } | null>(null)
  useEffect(() => {
    setResult(null)
    if (!active) return
    let cancelled = false
    getInvestmentFundingConfig()
      .then((cfg) => {
        if (!cancelled) setResult({ enabled: Boolean(cfg.is_enabled) })
      })
      .catch(() => {
        if (!cancelled) setResult({ enabled: false })
      })
    return () => {
      cancelled = true
    }
  }, [active])
  if (!active) return { loading: false, enabled: false }
  return { loading: result === null, enabled: result?.enabled ?? false }
}
