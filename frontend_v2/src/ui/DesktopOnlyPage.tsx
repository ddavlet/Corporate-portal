import { useState } from 'react'
import { useHref, useLocation, useNavigate } from 'react-router-dom'
import { Button, Space, Typography, theme } from 'antd'
import { BellOutlined, CopyOutlined, DesktopOutlined, FileTextOutlined } from '@ant-design/icons'
import { notifyApiError, notifyApiSuccess } from '../lib/apiNotify'
import { useModuleAccess } from './moduleAccess'
import { useMobileHeader } from './mobileShell'
import { findMobileSectionTitle } from './mobileMenu'

/** Full address of the current page, with the /app prefix of the router. */
function useCurrentPageUrl(): string {
  const location = useLocation()
  const href = useHref({ pathname: location.pathname, search: location.search })
  return typeof window === 'undefined' ? href : `${window.location.origin}${href}`
}

/**
 * Placeholder of the desktop-only sections on a phone: the page itself is not mounted, the viewer gets its address
 * to open on a computer and a way back to the requests (or to the notifications when the requests are not available
 * to the user). The phone header shows the section's name.
 */
export function DesktopOnlyPage() {
  const { token } = theme.useToken()
  const navigate = useNavigate()
  const location = useLocation()
  const url = useCurrentPageUrl()
  const { loading: modulesLoading, hasAccess } = useModuleAccess()
  useMobileHeader({ title: findMobileSectionTitle(location.pathname) ?? undefined })
  const [copying, setCopying] = useState(false)

  const copy = async () => {
    setCopying(true)
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard API is unavailable')
      await navigator.clipboard.writeText(url)
      notifyApiSuccess('Ссылка скопирована')
    } catch (e) {
      console.warn('Copy failed', e)
      notifyApiError('Не удалось скопировать ссылку. Выделите адрес и скопируйте вручную.')
    } finally {
      setCopying(false)
    }
  }

  return (
    <section
      aria-labelledby="desktop-only-title"
      data-testid="desktop-only-page"
      style={{ padding: '32px 4px', textAlign: 'center' }}
    >
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <DesktopOutlined aria-hidden style={{ fontSize: 48, color: token.colorPrimary }} />
        <Typography.Title level={4} id="desktop-only-title" style={{ margin: 0 }}>
          Раздел доступен на компьютере
        </Typography.Title>
        <Typography.Text style={{ color: token.colorTextSecondary }}>
          Мобильная версия этого раздела пока не готова. Откройте адрес на компьютере:
        </Typography.Text>
        <Typography.Text
          className="mono"
          data-testid="desktop-only-url"
          style={{
            display: 'block',
            padding: 12,
            borderRadius: token.borderRadius,
            background: token.colorFillTertiary,
            overflowWrap: 'anywhere',
            textAlign: 'left',
          }}
        >
          {url}
        </Typography.Text>
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Button block icon={<CopyOutlined />} onClick={() => void copy()} loading={copying}>
            Скопировать ссылку
          </Button>
          {/* Until the module list arrives every module reads as switched off: offer no way out rather than a wrong one. */}
          {modulesLoading ? null : hasAccess('requests') ? (
            <Button block type="primary" icon={<FileTextOutlined />} onClick={() => navigate('/requests')}>
              Перейти к заявкам
            </Button>
          ) : (
            <Button block type="primary" icon={<BellOutlined />} onClick={() => navigate('/notifications')}>
              Перейти к уведомлениям
            </Button>
          )}
        </Space>
      </Space>
    </section>
  )
}
