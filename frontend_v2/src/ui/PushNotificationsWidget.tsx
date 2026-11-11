import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Alert, Button, Space, Typography, theme } from 'antd'
import { BellOutlined } from '@ant-design/icons'
import { getSharedHost } from '../lib/portalMode'
import { isTelegramWebAppContext } from '../lib/pwa'
import {
  enablePush,
  getPushSupport,
  revokePushSubscription,
  syncPushSubscription,
  type PushSupport,
} from '../lib/webPush'

/**
 * Push notifications block of the notifications page: the "enable / disable" button on the shared app host, or the
 * reason why push is not available here. Permission is asked only from the button.
 */

type View = { support: PushSupport; subscribed: boolean }

function Muted({ children }: { children: ReactNode }) {
  const { token } = theme.useToken()
  return <Typography.Text style={{ color: token.colorTextSecondary }}>{children}</Typography.Text>
}

const UNAVAILABLE_TEXT: Partial<Record<PushSupport, string>> = {
  unsupported: 'Этот браузер не поддерживает push-уведомления.',
  'disabled-server': 'Push-уведомления сейчас недоступны.',
  denied:
    'Уведомления запрещены в настройках браузера. Разрешите их для этого сайта, затем обновите страницу.',
}

const ENABLE_ERROR_TEXT = 'Не удалось включить уведомления. Попробуйте ещё раз.'
const ENABLE_UNAVAILABLE_TEXT = 'Не удалось включить уведомления: сервис сейчас недоступен. Попробуйте позже.'
const DISABLE_ERROR_TEXT = 'Не удалось отключить уведомления. Попробуйте ещё раз.'

async function readView(): Promise<View> {
  const support = await getPushSupport()
  const subscribed = support === 'granted' ? await syncPushSubscription() : false
  return { support, subscribed }
}

export function PushNotificationsWidget() {
  const { token } = theme.useToken()
  const [view, setView] = useState<View | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    const next = await readView()
    setView(next)
    return next
  }, [])

  useEffect(() => {
    let alive = true
    readView().then((next) => {
      if (alive) setView(next)
    })
    return () => {
      alive = false
    }
  }, [])

  const enable = async () => {
    setBusy(true)
    setError(null)
    try {
      const result = await enablePush()
      if (result === 'error') setError(ENABLE_ERROR_TEXT)
      else if (result === 'unavailable') setError(ENABLE_UNAVAILABLE_TEXT)
      await reload()
    } finally {
      setBusy(false)
    }
  }

  const disable = async () => {
    setBusy(true)
    setError(null)
    try {
      // revokePushSubscription never rejects: a failure shows up only as a subscription that is still there.
      await revokePushSubscription()
      const next = await reload()
      if (next.support === 'granted' && next.subscribed) setError(DISABLE_ERROR_TEXT)
    } finally {
      setBusy(false)
    }
  }

  if (!view) {
    // Keep the block's height while support is checked, so the list below does not jump. No push in Telegram.
    if (isTelegramWebAppContext()) return null
    return <div aria-hidden data-push-loading style={{ minHeight: token.controlHeight }} />
  }
  if (view.support === 'telegram') return null

  const content = (() => {
    const { support, subscribed } = view
    if (support === 'subdomain-use-shared-host') {
      const host = getSharedHost() || 'app.kolberg.uz'
      return (
        <Muted>
          Уведомления доступны в приложении по адресу{' '}
          <Typography.Link href={`https://${host}/app/notifications`}>{host}</Typography.Link>
        </Muted>
      )
    }
    if (support === 'ios-needs-install') {
      return (
        <Muted>
          Чтобы получать уведомления на iPhone или iPad, установите портал: «Поделиться» → «На экран „Домой“», затем
          откройте его с экрана «Домой».
        </Muted>
      )
    }
    const reason = UNAVAILABLE_TEXT[support]
    if (reason) return <Muted>{reason}</Muted>
    if (support === 'granted' && subscribed) {
      return (
        <Space size={[12, 8]} wrap>
          <Muted>Уведомления включены на этом устройстве.</Muted>
          <Button onClick={() => void disable()} loading={busy}>
            Отключить уведомления
          </Button>
        </Space>
      )
    }
    return (
      <Space size={[12, 8]} wrap>
        <Button type="primary" icon={<BellOutlined aria-hidden />} onClick={() => void enable()} loading={busy}>
          Включить уведомления
        </Button>
        <Muted>Пришлём уведомление, когда понадобится ваше действие.</Muted>
      </Space>
    )
  })()

  return (
    <section aria-label="Push-уведомления" data-push-support={view.support}>
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        {content}
        {error ? <Alert type="error" showIcon message={error} /> : null}
      </Space>
    </section>
  )
}
