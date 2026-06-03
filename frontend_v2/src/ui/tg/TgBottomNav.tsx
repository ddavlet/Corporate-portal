import { useLocation, useNavigate } from 'react-router-dom'
import {
  BankOutlined,
  CheckSquareOutlined,
  DollarOutlined,
  FileTextOutlined,
  RiseOutlined,
} from '@ant-design/icons'
import { useModuleAccess } from '../moduleAccess'
import { tgHaptic } from './tgHaptic'

type NavItem = {
  key: string
  label: string
  path: string
  moduleKey: string
  icon: React.ReactNode
}

const NAV_ITEMS: NavItem[] = [
  { key: 'requests', label: 'Заявки', path: '/tg/requests', moduleKey: 'requests', icon: <FileTextOutlined /> },
  { key: 'cash', label: 'Касса', path: '/tg/cash', moduleKey: 'cash', icon: <DollarOutlined /> },
  { key: 'bank', label: 'Банк', path: '/tg/bank', moduleKey: 'bank', icon: <BankOutlined /> },
  { key: 'investments', label: 'Инвестиции', path: '/tg/investments', moduleKey: 'investments', icon: <RiseOutlined /> },
  { key: 'tasks', label: 'Задачи', path: '/tg/tasks', moduleKey: 'tasks', icon: <CheckSquareOutlined /> },
]

function isActive(pathname: string, itemPath: string): boolean {
  if (pathname === itemPath) return true
  return pathname.startsWith(itemPath + '/')
}

export function TgBottomNav() {
  const location = useLocation()
  const navigate = useNavigate()
  const { hasAccess } = useModuleAccess()
  const visible = NAV_ITEMS.filter((item) => hasAccess(item.moduleKey))
  if (visible.length === 0) return null
  return (
    <nav className="tg-bottom-nav" role="navigation" aria-label="Основные модули">
      {visible.map((item) => {
        const active = isActive(location.pathname, item.path)
        return (
          <button
            key={item.key}
            type="button"
            className={`tg-bottom-nav-btn${active ? ' tg-bottom-nav-btn--active' : ''}`}
            onClick={() => {
              if (!active) { tgHaptic.tap(); navigate(item.path) }
            }}
            aria-current={active ? 'page' : undefined}
          >
            <span className="tg-bottom-nav-btn-icon" aria-hidden>
              {item.icon}
            </span>
            <span>{item.label}</span>
          </button>
        )
      })}
    </nav>
  )
}
