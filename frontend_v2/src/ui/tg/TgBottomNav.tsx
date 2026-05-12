import { useState } from 'react'
import { Drawer, Typography } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  BankOutlined,
  DollarOutlined,
  EllipsisOutlined,
  FileTextOutlined,
  RiseOutlined,
} from '@ant-design/icons'
import { useModuleAccess } from '../moduleAccess'

type NavItem = {
  key: string
  label: string
  path: string
  moduleKey: string
  icon: React.ReactNode
}

const PRIMARY_ITEMS: NavItem[] = [
  { key: 'requests', label: 'Заявки', path: '/tg/requests', moduleKey: 'requests', icon: <FileTextOutlined /> },
  { key: 'cash', label: 'Касса', path: '/tg/cash', moduleKey: 'cash', icon: <DollarOutlined /> },
  { key: 'bank', label: 'Банк', path: '/tg/bank', moduleKey: 'bank', icon: <BankOutlined /> },
]

const SECONDARY_ITEMS: NavItem[] = [
  {
    key: 'investments',
    label: 'Инвестиции',
    path: '/tg/investments',
    moduleKey: 'investments',
    icon: <RiseOutlined />,
  },
]

function isActive(pathname: string, itemPath: string): boolean {
  if (pathname === itemPath) return true
  return pathname.startsWith(itemPath + '/')
}

function isAnyActive(pathname: string, items: NavItem[]): boolean {
  return items.some((item) => isActive(pathname, item.path))
}

export function TgBottomNav() {
  const location = useLocation()
  const navigate = useNavigate()
  const { hasAccess } = useModuleAccess()
  const [drawerOpen, setDrawerOpen] = useState(false)

  const visiblePrimary = PRIMARY_ITEMS.filter((item) => hasAccess(item.moduleKey))
  const visibleSecondary = SECONDARY_ITEMS.filter((item) => hasAccess(item.moduleKey))

  if (visiblePrimary.length === 0 && visibleSecondary.length === 0) return null

  const moreActive = isAnyActive(location.pathname, visibleSecondary)

  const handlePrimaryClick = (item: NavItem) => {
    if (!isActive(location.pathname, item.path)) navigate(item.path)
  }

  const handleSecondaryClick = (item: NavItem) => {
    setDrawerOpen(false)
    if (!isActive(location.pathname, item.path)) navigate(item.path)
  }

  return (
    <>
      <nav className="tg-bottom-nav" role="navigation" aria-label="Основные модули">
        {visiblePrimary.map((item) => {
          const active = isActive(location.pathname, item.path)
          return (
            <button
              key={item.key}
              type="button"
              className={`tg-bottom-nav-btn${active ? ' tg-bottom-nav-btn--active' : ''}`}
              onClick={() => handlePrimaryClick(item)}
              aria-current={active ? 'page' : undefined}
            >
              <span className="tg-bottom-nav-btn-icon" aria-hidden>
                {item.icon}
              </span>
              <span>{item.label}</span>
            </button>
          )
        })}
        {visibleSecondary.length > 0 ? (
          <button
            type="button"
            className={`tg-bottom-nav-btn${moreActive ? ' tg-bottom-nav-btn--active' : ''}`}
            onClick={() => setDrawerOpen(true)}
            aria-haspopup="dialog"
            aria-expanded={drawerOpen}
          >
            <span className="tg-bottom-nav-btn-icon" aria-hidden>
              <EllipsisOutlined />
            </span>
            <span>Ещё</span>
          </button>
        ) : null}
      </nav>

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        placement="bottom"
        height="auto"
        closable={false}
        styles={{
          body: { padding: 16 },
          content: { borderTopLeftRadius: 16, borderTopRightRadius: 16 },
        }}
      >
        <Typography.Title level={5} style={{ margin: '0 0 12px', fontWeight: 700 }}>
          Другие модули
        </Typography.Title>
        <div className="tg-section-landing">
          {visibleSecondary.map((item) => (
            <button
              key={item.key}
              type="button"
              className="tg-section-tile"
              onClick={() => handleSecondaryClick(item)}
            >
              <span className="tg-section-tile-icon" aria-hidden>
                {item.icon}
              </span>
              <span className="tg-section-tile-text">
                <span className="tg-section-tile-title">{item.label}</span>
              </span>
            </button>
          ))}
        </div>
      </Drawer>
    </>
  )
}
