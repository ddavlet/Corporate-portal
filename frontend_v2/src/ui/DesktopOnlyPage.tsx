import { useLocation, useNavigate } from 'react-router-dom'
import { Button, Space, Typography, theme } from 'antd'
import { AppstoreOutlined, HomeOutlined } from '@ant-design/icons'
import { useMobileHeader } from './mobileShell'
import { findMobileSectionTitle } from './mobileMenu'

/**
 * Placeholder of the sections without a phone layout, opened on a phone by a link: the page itself is not mounted;
 * the viewer is told the section is not available in the app and gets a way back to the start screen (`/`, which the
 * phone turns into its start page). The phone header shows the section's name.
 */
export function DesktopOnlyPage() {
  const { token } = theme.useToken()
  const navigate = useNavigate()
  const location = useLocation()
  useMobileHeader({ title: findMobileSectionTitle(location.pathname) ?? undefined })

  return (
    <section
      aria-labelledby="desktop-only-title"
      data-testid="desktop-only-page"
      style={{ padding: '32px 4px', textAlign: 'center' }}
    >
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <AppstoreOutlined aria-hidden style={{ fontSize: 48, color: token.colorTextSecondary }} />
        <Typography.Title level={4} id="desktop-only-title" style={{ margin: 0 }}>
          Раздел недоступен в приложении
        </Typography.Title>
        <Button block type="primary" icon={<HomeOutlined />} onClick={() => navigate('/')}>
          На главный экран
        </Button>
      </Space>
    </section>
  )
}
