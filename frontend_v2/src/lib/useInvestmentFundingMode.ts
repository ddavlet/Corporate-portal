import { useEffect, useState } from 'react'

import { getInvestmentFundingConfig } from './api'

/**
 * Включён ли инвестиционный режим тенанта. Пока грузится или при ошибке/403 конфига — false
 * (инвест-типы заявок скрыты).
 *
 * `active=false` — конфиг не запрашивается (результат false): для экранов, которым режим
 * нужен лишь для части записей.
 */
export function useInvestmentFundingMode(active: boolean = true): boolean {
  const [enabled, setEnabled] = useState(false)
  useEffect(() => {
    if (!active) {
      setEnabled(false)
      return
    }
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
  }, [active])
  return enabled
}
