import { useState, useSyncExternalStore } from 'react'
import { Button, Typography, theme } from 'antd'
import { CloseOutlined, DownloadOutlined } from '@ant-design/icons'
import {
  canPromptInstall,
  dismissInstallPrompt,
  isInstallPromptDismissed,
  isIosSafari,
  isStandaloneDisplay,
  isTelegramWebAppContext,
  promptInstall,
  subscribeInstallPrompt,
} from '../lib/pwa'
import { usePortalMobileMode } from '../lib/useIsPhone'

/**
 * «Установить приложение» over the phone feed. Android (Chrome): a button that opens the browser's install dialog.
 * iOS: how to add the portal through «Поделиться → На экран Домой». Not shown on a desktop, in the installed app, in
 * the Telegram Mini App, or once closed on this device.
 */
export function InstallAppPromptWidget() {
  const { token } = theme.useToken()
  const isMobile = usePortalMobileMode()
  const [dismissed, setDismissed] = useState(() => isInstallPromptDismissed())
  const [installing, setInstalling] = useState(false)
  const canPrompt = useSyncExternalStore(subscribeInstallPrompt, canPromptInstall, canPromptInstall)

  if (!isMobile || dismissed || isStandaloneDisplay() || isTelegramWebAppContext()) return null
  const ios = !canPrompt && isIosSafari()
  if (!canPrompt && !ios) return null

  const close = () => {
    dismissInstallPrompt()
    setDismissed(true)
  }

  const install = async () => {
    setInstalling(true)
    try {
      const outcome = await promptInstall()
      if (outcome === 'accepted') close()
    } finally {
      setInstalling(false)
    }
  }

  return (
    <section
      aria-labelledby="install-app-title"
      data-testid="install-app-prompt"
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 12,
        marginBottom: 12,
        padding: 12,
        borderRadius: token.borderRadiusLG,
        border: `1px solid ${token.colorInfoBorder}`,
        background: token.colorInfoBg,
      }}
    >
      <DownloadOutlined aria-hidden style={{ fontSize: 20, color: token.colorInfo, marginTop: 2 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <Typography.Text strong id="install-app-title" style={{ display: 'block' }}>
          Установить приложение
        </Typography.Text>
        {ios ? (
          <Typography.Text style={{ display: 'block', color: token.colorTextSecondary }}>
            Нажмите «Поделиться», затем «На экран Домой»: портал откроется как приложение.
          </Typography.Text>
        ) : (
          <>
            <Typography.Text style={{ display: 'block', color: token.colorTextSecondary }}>
              Портал откроется с главного экрана, без адресной строки.
            </Typography.Text>
            <Button type="primary" onClick={() => void install()} loading={installing} style={{ marginTop: 8 }}>
              Установить
            </Button>
          </>
        )}
      </div>
      <Button type="text" icon={<CloseOutlined />} aria-label="Закрыть подсказку" onClick={close} />
    </section>
  )
}
