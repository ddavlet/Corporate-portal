import { useEffect, useState } from 'react'

import { getInvestmentFundingConfig } from './api'

/**
 * Включён ли инвестиционный режим тенанта. Пока грузится или при ошибке/403 конфига — false
 * (инвест-типы заявок скрыты).
 */
export function useInvestmentFundingMode(): boolean {
  const [enabled, setEnabled] = useState(false)
  useEffect(() => {
    let cancelled = false
    getInvestmentFundingConfig()
      .then((cfg) => {
        if (!cancelled) setEnabled(Boolean(cfg.is_enabled))
      })
      .catch(() => {
        if (!cancelled) setEnabled(false)
      })
    return () => {
      cancelled = true
    }
  }, [])
  return enabled
}
