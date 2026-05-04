import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Card } from 'antd'
import { getSettingsAccess } from '../../lib/api'
import { AdminModulePage } from './AdminModulePage'

/**
 * Раздел «Админка» в портале — только для пользователя с ролью admin у текущего tenant
 * (`can_open_admin` из `/api/settings-access/`).
 */
export function AdminRouteGate() {
  const [phase, setPhase] = useState<'loading' | 'allow' | 'deny'>('loading')

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const data = await getSettingsAccess()
        if (cancelled) return
        setPhase(data.can_open_admin ? 'allow' : 'deny')
      } catch {
        if (!cancelled) setPhase('deny')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  if (phase === 'loading') {
    return <Card loading style={{ maxWidth: 480 }} />
  }
  if (phase === 'deny') {
    return <Navigate to="/requests" replace />
  }
  return <AdminModulePage />
}
