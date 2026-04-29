import { useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { ProLayout } from '@ant-design/pro-layout'
import type { MenuProps } from 'antd'
import { Button, Dropdown, Space, Typography } from 'antd'
import { Grid } from 'antd'
import {
  BankOutlined,
  BulbOutlined,
  ContactsOutlined,
  CommentOutlined,
  FundOutlined,
  RiseOutlined,
  SolutionOutlined,
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
import { AiQuestionsModal } from './ai/AiQuestionsModal'
import { useModuleAccess } from './moduleAccess'
import { filterInvestorMenuRoutes, type ShellMenuRoute } from './investorMenu'
import { getSettingsAccess } from '../lib/api'

export function AppShell() {
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md
  const location = useLocation()
  const navigate = useNavigate()
  const { logout, username } = useAuth()
  const { hasAccess } = useModuleAccess()
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [aiQuestionsOpen, setAiQuestionsOpen] = useState(false)
  const [passwordModalOpen, setPasswordModalOpen] = useState(false)
  const [canOpenSettings, setCanOpenSettings] = useState(false)
  const [canOpenAdmin, setCanOpenAdmin] = useState(false)
  const [roles, setRoles] = useState<string[]>([])
  const [tenantName, setTenantName] = useState<string>('')

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const data = await getSettingsAccess()
        if (!cancelled) {
          setTenantName(String(data.tenant_name || '').trim())
          setCanOpenSettings(Boolean(data.can_open_settings))
          setCanOpenAdmin(Boolean(data.can_open_admin))
          setRoles(Array.isArray(data.roles) ? data.roles : [])
        }
      } catch {
        if (!cancelled) {
          setTenantName('')
          setCanOpenSettings(false)
          setCanOpenAdmin(false)
          setRoles([])
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const isInvestor = roles.includes('investor')

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
        { path: '/investments', name: 'Инвестиции', icon: <RiseOutlined />, moduleKey: 'investments' },
        { path: '/clients-debt', name: 'Долги клиентов', icon: <ContactsOutlined />, moduleKey: 'clients_debt' },
        { path: '/budgets', name: 'Бюджеты', icon: <FundOutlined />, moduleKey: 'budgets' },
        { path: '/contracts', name: 'Договоры', icon: <SolutionOutlined />, moduleKey: 'contracts' },
        { path: '/training', name: 'Обучалка', icon: <ReadOutlined /> },
        ...(canOpenAdmin ? [{ path: '/admin', name: 'Админка', icon: <SafetyOutlined /> }] : []),
        ...(canOpenSettings ? [{ path: '/settings', name: 'Настройки', icon: <SettingOutlined /> }] : []),
      ] as ShellMenuRoute[])
        .filter((r) => !r.moduleKey || hasAccess(r.moduleKey))
        .filter((r) => filterInvestorMenuRoutes({ isInvestor, path: r.path })),
    [hasAccess, canOpenSettings, canOpenAdmin, isInvestor],
  )

  const profileMenu: MenuProps['items'] = [
    {
      key: 'password',
      label: 'Сменить пароль',
      onClick: () => setPasswordModalOpen(true),
    },
  ]

  const appTitle = tenantName || 'Portal'

  useEffect(() => {
    document.title = appTitle
  }, [appTitle])

  return (
    <ProLayout
      title={appTitle}
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
          <Button icon={<BulbOutlined />} onClick={() => setAiQuestionsOpen(true)}>
            Вопросы в ИИ
          </Button>
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
      <AiQuestionsModal open={aiQuestionsOpen} onClose={() => setAiQuestionsOpen(false)} />
      <ChangePasswordModal open={passwordModalOpen} onClose={() => setPasswordModalOpen(false)} />
      <Outlet />
    </ProLayout>
  )
}

