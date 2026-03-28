import { useEffect, useState } from 'react'
import { Alert, Skeleton } from 'antd'
import { Outlet } from 'react-router-dom'
import { exchangeTelegramWebApp, setTgTokens } from '../../lib/api'

export function TgWebAppLayout() {
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const tw = typeof window !== 'undefined' ? window.Telegram?.WebApp : undefined
    tw?.ready()
    tw?.expand?.()

    const initData = tw?.initData ?? ''
    if (!initData.trim()) {
      setError('Откройте мини-приложение из Telegram. Для отладки в браузере нужен тестовый initData.')
      return
    }

    let cancelled = false
    ;(async () => {
      try {
        const auth = await exchangeTelegramWebApp(initData)
        if (cancelled) return
        setTgTokens({ access: auth.access, refresh: auth.refresh })
        setReady(true)
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка входа')
      }
    })()

    return () => {
      cancelled = true
    }
  }, [])

  if (error) {
    return (
      <div style={{ padding: 16 }}>
        <Alert type="error" showIcon message="Нет доступа" description={error} />
      </div>
    )
  }

  if (!ready) {
    return (
      <div style={{ padding: 16 }}>
        <Skeleton active title paragraph={{ rows: 4 }} />
      </div>
    )
  }

  return (
    <div style={{ padding: 12, maxWidth: 720, margin: '0 auto' }}>
      <Outlet />
    </div>
  )
}
