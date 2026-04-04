import { useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { ProLayout } from '@ant-design/pro-layout'
import type { MenuProps } from 'antd'
import { Button, Dropdown, Space, Typography } from 'antd'
import {
  BankOutlined,
  CommentOutlined,
  CreditCardOutlined,
  DashboardOutlined,
  DollarOutlined,
  FileTextOutlined,
  LogoutOutlined,
  SettingOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { useAuth } from './auth'
import { FeedbackModal } from './feedback/FeedbackModal'
import { ChangePasswordModal } from './user/ChangePasswordModal'

export function AppShell() {
  const location = useLocation()
  const navigate = useNavigate()
  const { logout, username } = useAuth()
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [passwordModalOpen, setPasswordModalOpen] = useState(false)

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
        routes: [
          { path: '/', name: 'Панель', icon: <DashboardOutlined /> },
          { path: '/requests', name: 'Заявки', icon: <FileTextOutlined /> },
          { path: '/cash', name: 'Касса', icon: <DollarOutlined /> },
          { path: '/bank', name: 'Банк', icon: <BankOutlined /> },
          { path: '/corporate-card', name: 'Корпоративная карта', icon: <CreditCardOutlined /> },
          { path: '/payroll', name: 'Начисления ЗП', icon: <TeamOutlined /> },
          { path: '/settings', name: 'Настройки', icon: <SettingOutlined /> },
        ],
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
          {username ? <Typography.Text type="secondary">{username}</Typography.Text> : null}
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

