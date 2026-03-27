import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { ProLayout } from '@ant-design/pro-layout'
import { Button, Space, Typography } from 'antd'
import { BankOutlined, DashboardOutlined, DollarOutlined, FileTextOutlined, LogoutOutlined } from '@ant-design/icons'
import { useAuth } from './auth'

export function AppShell() {
  const location = useLocation()
  const navigate = useNavigate()
  const { logout, username } = useAuth()

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
      <Outlet />
    </ProLayout>
  )
}

