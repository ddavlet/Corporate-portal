import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Alert, ConfigProvider, Skeleton } from 'antd'
import { Outlet, useLocation } from 'react-router-dom'
import { exchangeTelegramWebApp, setTgTokens } from '../../lib/api'
import { useAuth } from '../auth'
import { ModuleAccessProvider } from '../moduleAccess'
import { getTgAntdTheme } from './tgAntdTheme'
import { TgBottomNav } from './TgBottomNav'
import { useTgWebAppShell } from './useTgWebAppShell'
import './tgWebApp.css'

const NAV_VISIBLE_PATHS =
  /^\/tg\/((requests|cash|bank)(\/(all|expenses|revenues))?|investments(\/(companies|projects|schedule|returns))?)$/

function shouldShowBottomNav(pathname: string): boolean {
  const normalized = pathname.replace(/\/+$/, '') || '/'
  return NAV_VISIBLE_PATHS.test(normalized)
}

export function TgWebAppLayout() {
  const { login } = useAuth()
  const location = useLocation()
  const [antdTheme, setAntdTheme] = useState(() => getTgAntdTheme())
  const syncAntdTheme = useCallback(() => setAntdTheme(getTgAntdTheme()), [])
  useTgWebAppShell(syncAntdTheme)
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

  const showNav = useMemo(() => shouldShowBottomNav(location.pathname), [location.pathname])

  const shell = (node: ReactNode, opts?: { withNav?: boolean }) => (
    <ConfigProvider theme={antdTheme}>
      <div className={`tg-webapp-root${opts?.withNav ? ' tg-with-bottom-nav' : ''}`}>
        <div className="tg-webapp-inner">{node}</div>
        {opts?.withNav ? <TgBottomNav /> : null}
      </div>
    </ConfigProvider>
  )

  if (error) {
    return shell(<Alert type="error" showIcon message="Нет доступа" description={error} />)
  }

  if (!ready) {
    return shell(<Skeleton active title paragraph={{ rows: 4 }} />)
  }

  return (
    <ModuleAccessProvider>{shell(<Outlet />, { withNav: showNav })}</ModuleAccessProvider>
  )
}
