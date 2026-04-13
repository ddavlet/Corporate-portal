import { useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { ProLayout } from '@ant-design/pro-layout'
import type { MenuProps } from 'antd'
import { Button, Dropdown, Space, Typography } from 'antd'
import { Grid } from 'antd'
import {
  BankOutlined,
  ContactsOutlined,
  CommentOutlined,
  CreditCardOutlined,
  DashboardOutlined,
  DollarOutlined,
  FileTextOutlined,
  BarChartOutlined,
  LogoutOutlined,
  SettingOutlined,
  SafetyOutlined,
  TeamOutlined,
  ReadOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { useAuth } from './auth'
import { FeedbackModal } from './feedback/FeedbackModal'
import { ChangePasswordModal } from './user/ChangePasswordModal'
import { useModuleAccess } from './moduleAccess'
import { getSettingsAccess } from '../lib/api'

export function AppShell() {
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md
  const location = useLocation()
  const navigate = useNavigate()
  const { logout, username } = useAuth()
  const { hasAccess } = useModuleAccess()
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [passwordModalOpen, setPasswordModalOpen] = useState(false)
  const [canOpenSettings, setCanOpenSettings] = useState(false)
  const [canOpenAdmin, setCanOpenAdmin] = useState(false)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const data = await getSettingsAccess()
        if (!cancelled) {
          setCanOpenSettings(Boolean(data.can_open_settings))
          setCanOpenAdmin(Boolean(data.can_open_admin))
        }
      } catch {
        if (!cancelled) {
          setCanOpenSettings(false)
          setCanOpenAdmin(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  type MenuRoute = {
    path: string
    name: string
    icon: JSX.Element
    moduleKey?: string
  }

  const menuRoutes = useMemo(
    () =>
      ([
        { path: '/', name: 'Панель', icon: <DashboardOutlined /> },
        { path: '/requests', name: 'Заявки', icon: <FileTextOutlined />, moduleKey: 'requests' },
        { path: '/cash', name: 'Касса', icon: <DollarOutlined />, moduleKey: 'cash' },
        { path: '/bank', name: 'Банк', icon: <BankOutlined />, moduleKey: 'bank' },
        { path: '/corporate-card', name: 'Корпоративная карта', icon: <CreditCardOutlined />, moduleKey: 'corporate_card' },
        { path: '/payroll', name: 'Начисления ЗП', icon: <TeamOutlined />, moduleKey: 'payroll' },
        { path: '/reports', name: 'Отчеты', icon: <BarChartOutlined />, moduleKey: 'reports' },
        { path: '/clients-debt', name: 'Долги клиентов', icon: <ContactsOutlined />, moduleKey: 'clients_debt' },
        { path: '/training', name: 'Обучалка', icon: <ReadOutlined /> },
        ...(canOpenAdmin ? [{ path: '/admin', name: 'Админка', icon: <SafetyOutlined /> }] : []),
        ...(canOpenSettings ? [{ path: '/settings', name: 'Настройки', icon: <SettingOutlined /> }] : []),
      ] as MenuRoute[]).filter((r) => !r.moduleKey || hasAccess(r.moduleKey)),
    [hasAccess, canOpenSettings, canOpenAdmin],
  )

  const profileMenu: MenuProps['items'] = [
    {
      key: 'password',
      label: 'Сменить пароль',
      onClick: () => setPasswordModalOpen(true),
    },
  ]

  return (
    <ProLayout
      title="Kolberg v2"
      logo={false}
      location={{ pathname: location.pathname }}
      route={{
        routes: menuRoutes,
      }}
      menuItemRender={(item, dom) => (
        <a
          onClick={(e) => {
            e.preventDefault()
            if (item.path) navigate(item.path)
          }}
        >
          {dom}
        </a>
      )}
      rightContentRender={() => (
        <Space size="middle">
          {!isMobile && username ? <Typography.Text type="secondary">{username}</Typography.Text> : null}
          <Button icon={<CommentOutlined />} onClick={() => setFeedbackOpen(true)}>
            Обратная связь
          </Button>
          <Dropdown menu={{ items: profileMenu }} trigger={['click']}>
            <Button icon={<UserOutlined />}>Профиль</Button>
          </Dropdown>
          <Button
            icon={<LogoutOutlined />}
            onClick={() => {
              logout()
              navigate('/login', { replace: true })
            }}
          >
            Выйти
          </Button>
        </Space>
      )}
      footerRender={false}
      fixSiderbar
      layout="mix"
      contentStyle={{ padding: 24 }}
    >
      <FeedbackModal open={feedbackOpen} onClose={() => setFeedbackOpen(false)} pagePath={location.pathname} />
      <ChangePasswordModal open={passwordModalOpen} onClose={() => setPasswordModalOpen(false)} />
      <Outlet />
    </ProLayout>
  )
}

