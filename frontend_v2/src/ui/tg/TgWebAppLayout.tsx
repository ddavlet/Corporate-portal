import { useEffect, useState } from 'react'
import { Alert, ConfigProvider, Skeleton } from 'antd'
import { Outlet } from 'react-router-dom'
import { exchangeTelegramWebApp, setTgTokens } from '../../lib/api'
import { useAuth } from '../auth'
import { useTgWebAppShell } from './useTgWebAppShell'
import './tgWebApp.css'

export function TgWebAppLayout() {
  const { login } = useAuth()
  useTgWebAppShell()
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
        const tokens = { access: auth.access, refresh: auth.refresh }
        setTgTokens(tokens)
        login({ tokens, username: auth.username })
        setReady(true)
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка входа')
      }
    })()

    return () => {
      cancelled = true
    }
  }, [login])

  if (error) {
    return (
      <div className="tg-webapp-root">
        <div className="tg-webapp-inner">
          <Alert type="error" showIcon message="Нет доступа" description={error} />
        </div>
      </div>
    )
  }

  if (!ready) {
    return (
      <div className="tg-webapp-root">
        <div className="tg-webapp-inner">
          <Skeleton active title paragraph={{ rows: 4 }} />
        </div>
      </div>
    )
  }

  return (
    <ConfigProvider
      theme={{
        token: {
          borderRadius: 12,
          borderRadiusLG: 14,
          controlHeight: 44,
          controlHeightLG: 48,
          fontSize: 15,
        },
      }}
    >
      <div className="tg-webapp-root">
        <div className="tg-webapp-inner">
          <Outlet />
        </div>
      </div>
    </ConfigProvider>
  )
}
