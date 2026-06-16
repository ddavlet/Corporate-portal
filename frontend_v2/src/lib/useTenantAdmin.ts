import { useEffect, useState } from 'react'
import { getSettingsAccess } from './api'

/**
 * Кэш на уровне модуля: множество списков монтируют хук одновременно, не хотим
 * слать /api/settings-access/ на каждой странице. Совпадает с тем, как
 * AppShell/AdminRouteGate читают тот же флаг can_open_admin.
 */
let cachedAccessPromise: Promise<boolean> | null = null

function fetchIsAdmin(): Promise<boolean> {
  if (!cachedAccessPromise) {
    cachedAccessPromise = getSettingsAccess()
      .then((data) => Boolean(data.can_open_admin))
      .catch((e) => {
        // Не кэшируем неудачу: при следующем монтировании попробуем снова.
        cachedAccessPromise = null
        throw e
      })
  }
  return cachedAccessPromise
}

/** Сбрасывает кэш (напр. при logout / смене tenant). */
export function resetTenantAdminCache(): void {
  cachedAccessPromise = null
}

/**
 * Возвращает, является ли текущий пользователь администратором tenant
 * (роль admin → can_open_admin). Используется для показа админ-действий
 * прямо в списках, не заходя в Админку.
 */
export function useTenantAdmin(): { isAdmin: boolean; loading: boolean } {
  const [isAdmin, setIsAdmin] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    fetchIsAdmin()
      .then((value) => {
        if (active) setIsAdmin(value)
      })
      .catch(() => {
        if (active) setIsAdmin(false)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  return { isAdmin, loading }
}
